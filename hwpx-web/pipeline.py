# -*- coding: utf-8 -*-
"""hwp-writing-assistant 스킬 파이프라인 어댑터.

스킬 폴더(레포 루트의 hwp-writing-assistant/)의 스크립트를 수정 없이
서브프로세스로 호출한다. 순서 고정: check_numbers → build_hwpx → hwpx_polish.
hwpx_shifttab(Windows+한글 전용)은 웹 서버에서 호출하지 않는다.
"""
import os
import subprocess
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL_DIR = os.path.join(REPO_ROOT, "hwp-writing-assistant")
SCRIPTS = os.path.join(SKILL_DIR, "scripts")


class PipelineError(RuntimeError):
    def __init__(self, step, log):
        super().__init__(f"{step} 단계 실패:\n{log}")
        self.step = step
        self.log = log


def _run(script, *args):
    """scripts/ 아래 스크립트를 실행하고 (returncode, 출력 텍스트)를 돌려준다."""
    path = os.path.join(SCRIPTS, script)
    proc = subprocess.run(
        [sys.executable, path, *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120,
    )
    out = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")
    return proc.returncode, out.strip()


def check_numbers(md_path):
    """숫자 검증. (통과 여부, 리포트 텍스트)를 돌려준다."""
    rc, report = _run("check_numbers.py", md_path)
    return rc == 0, report


def build_hwpx(manuscript_text, out_path):
    """원고 → build → polish. polish 리포트 텍스트를 돌려준다.

    hwpx_polish는 절대 생략하지 않는다(생략 시 한글에서 글자 겹침 —
    layout-rules.md 1장).
    """
    with tempfile.TemporaryDirectory(prefix="hwpx_") as tmp:
        md_path = os.path.join(tmp, "manuscript.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(manuscript_text)

        draft = os.path.join(tmp, "draft.hwpx")
        rc, log = _run("build_hwpx.py", md_path, draft)
        if rc != 0:
            raise PipelineError("HWPX 생성(build_hwpx)", log)

        rc, polish_report = _run("hwpx_polish.py", draft, out_path)
        if rc != 0:
            raise PipelineError("레이아웃 후처리(hwpx_polish)", polish_report)

    return polish_report


def preview_hwpx(hwpx_path):
    """QA용 미리보기(근사). 실패해도 치명적이지 않으므로 텍스트만 돌려준다."""
    rc, out = _run("preview_hwpx.py", hwpx_path, "--detail")
    return out if rc == 0 else f"(미리보기 생성 실패)\n{out}"


def save_manuscript_to_tempfile(manuscript_text):
    fd, path = tempfile.mkstemp(suffix=".md", prefix="hwpx_ms_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(manuscript_text)
    return path
