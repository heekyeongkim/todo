# -*- coding: utf-8 -*-
"""엔드투엔드 검증 (LLM 스텁 사용 — API 키 없이 파이프라인·재검증 흐름을 검사).

    python test_flow.py
"""
import base64
import io
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core
import pipeline

SKILL_SAMPLE = os.path.join(pipeline.SKILL_DIR, "sample.md")

BAD_MANUSCRIPT = """\
# 예산 계획(안)
## 요약
> 숫자 검증 재수정 흐름 테스트
1. 소요 예산
○ 총 300백만원 소요
| 구분 | 2026년 | 계 |
| --- | --- | --- |
| 교육비 | 100 | 100 |
| 자료비 | 50 | 50 |
| 합계 | 200 | 200 |
"""

FIXED_MANUSCRIPT = BAD_MANUSCRIPT.replace("| 합계 | 200 | 200 |", "| 합계 | 150 | 150 |")


class StubLLM:
    """generate → 지정 원고, fix → 지정 목록을 순서대로 반환."""
    def __init__(self, first, fixes=()):
        self.first = first
        self.fixes = list(fixes)
        self.fix_calls = 0

    def generate_manuscript(self, title, content, attachment_text=None):
        return self.first

    def fix_manuscript(self, manuscript, report):
        self.fix_calls += 1
        return self.fixes.pop(0) if self.fixes else manuscript

    def adjust_manuscript(self, manuscript, mode):
        return manuscript


def check_hwpx_zip(b64):
    data = base64.b64decode(b64)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        first = z.infolist()[0]
        assert first.filename == "mimetype", f"mimetype이 선두가 아님: {first.filename}"
        assert first.compress_type == zipfile.ZIP_STORED, "mimetype이 무압축(STORED)이 아님"
        assert z.read("mimetype") == b"application/hwp+zip"
        assert z.testzip() is None


def test_1_sample_e2e():
    manuscript = open(SKILL_SAMPLE, encoding="utf-8").read()
    result = core.generate_document("t", "c" * 20, llm=StubLLM(manuscript))
    assert result["check_passed"], result["check_report"]
    assert result["fix_retries"] == 0
    check_hwpx_zip(result["hwpx_base64"])
    for margin in ("좌여백 750", "좌여백 1500", "좌여백 2250"):
        assert margin in result["preview"], f"미리보기에 '{margin}' 없음"
    assert "내어쓰기 -" in result["preview"], "음수 내어쓰기가 미리보기에 없음"
    print("[1] sample.md 엔드투엔드 + 좌여백/내어쓰기 확인: OK")


def test_2_autofix_flow():
    stub = StubLLM(BAD_MANUSCRIPT, fixes=[FIXED_MANUSCRIPT])
    result = core.generate_document("t", "c" * 20, llm=stub)
    assert stub.fix_calls == 1
    assert result["fix_retries"] == 1
    assert result["check_passed"] and not result["forced"]
    check_hwpx_zip(result["hwpx_base64"])
    print("[2] 숫자 오류 → 자동 수정 → 재검증 통과: OK")


def test_3_force_after_retries():
    stub = StubLLM(BAD_MANUSCRIPT)  # fix가 원고를 못 고침
    result = core.generate_document("t", "c" * 20, llm=stub)
    assert stub.fix_calls == core.MAX_FIX_RETRIES == result["fix_retries"]
    assert result["forced"] and not result["check_passed"]
    assert "❌" in result["check_report"]
    check_hwpx_zip(result["hwpx_base64"])  # 오류가 남아도 파일은 만들어진다
    print("[3] 2회 재시도 실패 → 경고와 함께 강행 생성: OK")


def test_4_assumptions_and_filename():
    ms = open(SKILL_SAMPLE, encoding="utf-8").read() + "\n<!-- 가정: 연도를 2026년으로 보완 -->\n"
    result = core.generate_document("계획/안:*?", "c" * 20, llm=StubLLM(ms))
    assert result["assumptions"] == ["연도를 2026년으로 보완"]
    assert "<!--" not in result["manuscript"]
    assert "/" not in result["filename"] and result["filename"].endswith(".hwpx")
    print("[4] 가정 주석 추출 + 파일명 금지문자 치환: OK")


if __name__ == "__main__":
    test_1_sample_e2e()
    test_2_autofix_flow()
    test_3_force_after_retries()
    test_4_assumptions_and_filename()
    print("\n모든 검증 통과")
