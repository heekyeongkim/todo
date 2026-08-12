#!/usr/bin/env python3
"""make.py — 원고(.md) 하나로 전체 파이프라인을 돌린다. (make.ps1의 파이썬 판)

    python make.py 원고.md               검증 → 생성 → 후처리 → 미리보기
    python make.py 원고.md --out 보고서.hwpx
    python make.py 원고.md --no-shift-tab  한글 실측 내어쓰기 단계를 끔
    python make.py 원고.md --force       숫자 오류가 있어도 계속 진행
    python make.py 원고.md --open        완료 후 한글로 열기 (Windows)

숫자 검증에서 오류(❌)가 나오면 기본적으로 여기서 멈춘다.
틀린 숫자로 hwpx를 만들면 고친 뒤 다시 만들어야 하므로 두 번 일이 된다.

Windows/macOS/Linux, ChatGPT 코드 인터프리터 어디서나 동작한다.
표준 라이브러리만 사용하므로 설치할 것이 없다.
"""
import os
import subprocess
import sys
import tempfile

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "scripts")


def run(script, *args):
    """scripts/ 아래 스크립트를 실행하고 종료 코드를 돌려준다."""
    path = os.path.join(SCRIPTS, script)
    if not os.path.exists(path):
        print(f"스크립트를 찾을 수 없음: {path}", file=sys.stderr)
        print("scripts/ 폴더가 make.py 와 같은 위치에 있는지 확인할 것.", file=sys.stderr)
        return 127
    # 하위 프로세스와 출력 순서가 뒤엉키지 않도록 먼저 비운다
    sys.stdout.flush()
    sys.stderr.flush()
    return subprocess.run([sys.executable, path, *args]).returncode


def open_file(path):
    try:
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.run(["open", path])
        else:
            subprocess.run(["xdg-open", path])
    except Exception as e:
        print(f"열기 실패 ({e}) — 파일을 직접 여시오: {path}")


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 1

    src = args[0]
    if not os.path.exists(src):
        print(f"원고를 찾을 수 없음: {src}", file=sys.stderr)
        return 1

    force = "--force" in argv
    do_open = "--open" in argv
    if "--out" in argv:
        out = argv[argv.index("--out") + 1]
    else:
        out = os.path.splitext(src)[0] + ".hwpx"
    # 서식 프로파일과 라벨 내어쓰기는 각 단계로 그대로 넘긴다
    polish_opt = ["--label-indent"] if "--label-indent" in argv else []
    # 한글이 있는 Windows 에서는 내어쓰기를 계산값 대신 한글 실측값으로 바꾼다.
    # 한글이 없으면 그 단계가 알아서 건너뛰므로 기본으로 켜 둔다.
    shift_tab = "--no-shift-tab" not in argv

    fd, draft = tempfile.mkstemp(suffix=".hwpx", prefix="_draft_")
    os.close(fd)

    try:
        print("\n[1/4] 숫자 검증")
        if run("check_numbers.py", src) != 0 and not force:
            print("\n숫자 오류가 있어 중단함. 고친 뒤 다시 실행하거나, "
                  "그대로 만들려면 --force 를 붙일 것.", file=sys.stderr)
            return 1

        print("\n[2/4] HWPX 생성")
        if run("build_hwpx.py", src, draft) != 0:
            return 1

        print("\n[3/4] 레이아웃 후처리")
        if run("hwpx_polish.py", draft, out, *polish_opt) != 0:
            return 1

        if shift_tab:
            print("\n[4/5] Shift+Tab 내어쓰기 (한글 실측)")
            rc = run("hwpx_shifttab.py", out)
            if rc == 2:
                print("      → 한글을 쓸 수 없는 환경이라 계산값 그대로 둠")

        print(f"\n[{'5/5' if shift_tab else '4/4'}] 미리보기")
        run("preview_hwpx.py", out, "--detail")
    finally:
        try:
            os.remove(draft)
        except OSError:
            pass

    print(f"\n완료: {out}")
    print("한글에서 확인할 것: ① 줄바꿈이 어절 경계인가 ② 이어지는 줄이 기호 뒤에 "
          "정렬됐는가 ③ 글자 겹침이 없는가 ④ 표 테두리·열 너비")

    if do_open:
        open_file(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
