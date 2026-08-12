# -*- coding: utf-8 -*-
"""생성 플로우 오케스트레이션.

원고 생성(LLM) → 숫자 검증(check_numbers) → 오류 시 LLM 되먹임 재수정(최대 2회)
→ 그래도 오류면 경고와 함께 강행(build+polish) → 결과 리포트 반환.
"""
import base64
import io
import os
import re
import tempfile
import zipfile

import pipeline

MAX_FIX_RETRIES = 2


def extract_attachment_text(filename, data):
    """TXT/DOCX/PDF에서 텍스트를 추출한다. 실패 시 ValueError."""
    name = (filename or "").lower()
    if name.endswith(".txt"):
        for enc in ("utf-8", "cp949"):
            try:
                return data.decode(enc)
            except UnicodeDecodeError:
                continue
        raise ValueError("TXT 파일 인코딩을 해석할 수 없습니다 (UTF-8/CP949 지원).")
    if name.endswith(".docx"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                xml = z.read("word/document.xml").decode("utf-8", "replace")
        except (zipfile.BadZipFile, KeyError):
            raise ValueError("DOCX 파일을 해석할 수 없습니다.")
        # 문단 경계를 줄바꿈으로 살리고 태그를 걷어낸다
        xml = re.sub(r"</w:p>", "\n", xml)
        return re.sub(r"<[^>]+>", "", xml).strip()
    if name.endswith(".pdf"):
        try:
            from pypdf import PdfReader
        except ImportError:
            raise ValueError("PDF 추출에는 pypdf 설치가 필요합니다 (pip install pypdf).")
        reader = PdfReader(io.BytesIO(data))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
        if not text.strip():
            raise ValueError("PDF에서 텍스트를 추출하지 못했습니다 (스캔본일 수 있음).")
        return text
    raise ValueError("지원하지 않는 파일 형식입니다 (TXT/PDF/DOCX).")


def _extract_assumptions(manuscript):
    """원고 안의 `<!-- 가정: … -->` 주석을 뽑아 (본문, 가정 목록)으로 돌려준다."""
    assumptions = re.findall(r"<!--\s*가정[::]\s*(.*?)\s*-->", manuscript)
    cleaned = re.sub(r"<!--.*?-->\n?", "", manuscript, flags=re.S).strip() + "\n"
    return cleaned, assumptions


def sanitize_filename(title):
    name = re.sub(r'[\\/:*?"<>|\r\n]+', "_", (title or "").strip()).strip(" .")
    return name or "행정문서_초안"


def generate_document(title, content, attachment_text=None, mode=None,
                      base_manuscript=None, llm=None):
    """전체 플로우를 돌리고 결과 dict를 돌려준다.

    mode: None(신규 생성) | "concise" | "detailed" (base_manuscript 보정)
    llm: 주입 가능한 LLM 모듈(테스트용). 기본은 llm.py.
    """
    if llm is None:
        import llm as llm_module
        llm = llm_module

    if mode and base_manuscript:
        manuscript = llm.adjust_manuscript(base_manuscript, mode)
    else:
        manuscript = llm.generate_manuscript(title, content, attachment_text)

    manuscript, assumptions = _extract_assumptions(manuscript)

    # 숫자 검증 → 오류 시 LLM 되먹임 재수정(최대 MAX_FIX_RETRIES회)
    retries = 0
    check_passed, check_report = _check(manuscript)
    while not check_passed and retries < MAX_FIX_RETRIES:
        retries += 1
        manuscript = llm.fix_manuscript(manuscript, check_report)
        manuscript, more = _extract_assumptions(manuscript)
        assumptions += more
        check_passed, check_report = _check(manuscript)

    # 검증 실패여도 생성을 막지 않고 강행하되, 경고를 함께 돌려준다
    forced = not check_passed

    fd, out_path = tempfile.mkstemp(suffix=".hwpx", prefix="hwpx_out_")
    os.close(fd)
    try:
        polish_report = pipeline.build_hwpx(manuscript, out_path)
        preview = pipeline.preview_hwpx(out_path)
        with open(out_path, "rb") as f:
            hwpx_b64 = base64.b64encode(f.read()).decode("ascii")
    finally:
        try:
            os.remove(out_path)
        except OSError:
            pass

    return {
        "manuscript": manuscript,
        "hwpx_base64": hwpx_b64,
        "filename": sanitize_filename(title) + ".hwpx",
        "check_passed": check_passed,
        "check_report": check_report,
        "fix_retries": retries,
        "forced": forced,
        "polish_report": polish_report,
        "preview": preview,
        "assumptions": assumptions,
    }


def _check(manuscript):
    md_path = pipeline.save_manuscript_to_tempfile(manuscript)
    try:
        return pipeline.check_numbers(md_path)
    finally:
        try:
            os.remove(md_path)
        except OSError:
            pass
