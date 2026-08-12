#!/usr/bin/env python3
"""hwpx_shifttab.py — 한글에게 Shift+Tab(커서 위치 내어쓰기)을 직접 시킨다.

공무원이 실제로 하는 작업이다. 글머리(○, -, ※ …) 문단마다 본문 시작점에 커서를 두고
Shift+Tab 을 눌러 이어지는 줄을 그 위치에 정확히 맞춘다.

왜 계산으로 못 하는가:
    같은 `○ ` 접두부인데도 문단마다 값이 다르다(-3018 / -3413 / -3307).
    양쪽정렬이 첫 줄의 공백을 늘린 만큼 커서의 실제 x좌표가 달라지기 때문이다.
    줄 나눔과 양쪽정렬 결과는 한글만 알고 있으므로, 한글에게 시키는 것이 유일한 정답이다.
    hwpx_polish.py 의 내어쓰기는 글자폭 모델로 낸 근사값이고, 이쪽은 실측값이다.

주의 — 한글은 저장하면서 문단 왼쪽 여백(계층 들여쓰기)을 지우는 경우가 있다.
    특히 내어쓰기가 없는 문단(기호를 달지 않는 '요약' 본문 등)이 그렇다.
    그래서 열기 전에 모든 본문 문단의 left 를 기억해 두었다가, 저장 후 되돌려 놓는다.
    내어쓰기(intent)는 한글이 새로 잰 값이므로 그대로 둔다.

필요 조건: Windows + 한글(HWP) 설치 + pywin32.
    조건이 안 되면 아무것도 하지 않고 종료 코드 2 로 끝난다(파이프라인을 막지 않는다).

사용법:
    python hwpx_shifttab.py 문서.hwpx              # 제자리에서 적용
    python hwpx_shifttab.py 입력.hwpx 출력.hwpx
"""
import html
import os
import re
import shutil
import sys
import tempfile
import zipfile

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 한글이 커서 위치로 내어쓰기를 잡는 액션. 실측으로 확인함(2026-08).
ACTION = "ParagraphShapeIndentAtCaret"
BULLET = re.compile(r"^(\s*[○□◦\-−–·※*]\s+)")
P_RE = r"<hp:p\b.*?</hp:p>"


def _sections(z):
    return [n for n in sorted(z.namelist())
            if re.match(r"Contents/section\d+\.xml$", n)]


def _stash_tables(sec):
    """표 안의 문단은 본문 문단이 아니다. 표를 통째로 빼두고 나중에 되돌린다."""
    tbls = []

    def keep(m):
        tbls.append(m.group(0))
        return "<!--TBL%d-->" % (len(tbls) - 1)

    return re.sub(r"<hp:tbl\b.*?</hp:tbl>", keep, sec, flags=re.S), tbls


def _restore_tables(sec, tbls):
    return re.sub(r"<!--TBL(\d+)-->", lambda m: tbls[int(m.group(1))], sec)


def _geom_map(hdr):
    """paraPr id → (좌여백, 내어쓰기)"""
    out = {}
    for m in re.finditer(r'<hh:paraPr id="(\d+)".*?</hh:paraPr>', hdr, re.S):
        l = re.search(r'<hc:left value="(-?\d+)"', m.group(0))
        i = re.search(r'<hc:intent value="(-?\d+)"', m.group(0))
        out[m.group(1)] = (int(l.group(1)) if l else 0, int(i.group(1)) if i else 0)
    return out


def scan(path):
    """(글머리 문단 목록, 문단별 (좌여백, 내어쓰기)) — 둘 다 본문 문단 index 기준."""
    with zipfile.ZipFile(path) as z:
        names = _sections(z)
        if not names:
            return [], {}
        hdr = z.read("Contents/header.xml").decode("utf-8")
        sec, _ = _stash_tables(z.read(names[0]).decode("utf-8"))
    geom_by_pr = _geom_map(hdr)
    bullets, geom = [], {}
    for i, p in enumerate(re.findall(P_RE, sec, re.S)):
        pid = (re.search(r'paraPrIDRef="(\d+)"', p) or [None, "0"])[1]
        geom[i] = geom_by_pr.get(pid, (0, 0))
        t = html.unescape("".join(re.findall(r"<hp:t[^>]*>([^<]*)</hp:t>", p)))
        m = BULLET.match(t)
        if m:
            bullets.append((i, len(m.group(1))))
    return bullets, geom


def restore_geom(path, wanted):
    """한글이 바꿔놓은 문단 여백을 되돌린다. wanted = {문단index: (좌여백, 내어쓰기|None)}

    내어쓰기가 None 이면 좌여백만 되돌린다 — Shift+Tab 을 먹인 글머리 문단이 그렇다.
    그 문단의 내어쓰기는 한글이 방금 잰 실측값이므로 건드리면 안 된다.
    반대로 기호 없는 문단(요약 본문 등)은 한글이 엉뚱한 문단모양에 붙여버리는 일이 있어
    좌여백과 내어쓰기를 모두 되돌린다. 바꾼 문단 수를 돌려준다."""
    tmp = tempfile.mkdtemp()
    try:
        with zipfile.ZipFile(path) as z:
            z.extractall(tmp)
            names = _sections(z)
        if not names:
            return 0
        hdr_path = os.path.join(tmp, "Contents", "header.xml")
        sec_path = os.path.join(tmp, *names[0].split("/"))
        hdr = open(hdr_path, encoding="utf-8").read()
        sec_raw = open(sec_path, encoding="utf-8").read()
        sec, tbls = _stash_tables(sec_raw)

        blocks = {m.group(1): m.group(0) for m in
                  re.finditer(r'<hh:paraPr id="(\d+)".*?</hh:paraPr>', hdr, re.S)}
        cur = _geom_map(hdr)
        max_id = max(int(i) for i in blocks)
        made, new_defs, fixed = {}, [], [0]

        def fix(m):
            i = fix.idx
            fix.idx += 1
            p = m.group(0)
            want = wanted.get(i)
            pid_m = re.search(r'paraPrIDRef="(\d+)"', p)
            if want is None or not pid_m:
                return p
            pid = pid_m.group(1)
            w_left, w_intent = want
            c_left, c_intent = cur.get(pid, (0, 0))
            if c_left == w_left and (w_intent is None or c_intent == w_intent):
                return p
            key = (pid, w_left, w_intent)
            if key not in made:
                nid = made[key] = str(max_id + 1 + len(made))
                # paraPr 은 <hp:switch> 안에 case/default 두 벌이 들어 있다 — 전부 바꾼다
                clone = re.sub(r'(<hh:paraPr id=")\d+(")', r"\g<1>%s\g<2>" % nid,
                               blocks[pid], count=1)
                clone = re.sub(r'(<hc:left value=")-?\d+(")', r"\g<1>%d\g<2>" % w_left, clone)
                if w_intent is not None:
                    clone = re.sub(r'(<hc:intent value=")-?\d+(")',
                                   r"\g<1>%d\g<2>" % w_intent, clone)
                new_defs.append(clone)
            fixed[0] += 1
            return re.sub(r'(paraPrIDRef=")\d+(")', r"\g<1>%s\g<2>" % made[key], p, count=1)

        fix.idx = 0
        sec = re.sub(P_RE, fix, sec, flags=re.S)
        if not new_defs:
            return 0
        hdr = hdr.replace("</hh:paraProperties>", "".join(new_defs) + "</hh:paraProperties>")
        m = re.search(r'(<hh:paraProperties itemCnt=")(\d+)(")', hdr)
        if m:
            hdr = hdr[:m.start()] + m.group(1) + str(int(m.group(2)) + len(new_defs)) + \
                m.group(3) + hdr[m.end():]
        open(hdr_path, "w", encoding="utf-8").write(hdr)
        open(sec_path, "w", encoding="utf-8").write(_restore_tables(sec, tbls))

        os.remove(path)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            mt = os.path.join(tmp, "mimetype")
            if os.path.exists(mt):
                z.write(mt, "mimetype", compress_type=zipfile.ZIP_STORED)
            for root, _, files in os.walk(tmp):
                for f in files:
                    full = os.path.join(root, f)
                    rel = os.path.relpath(full, tmp).replace("\\", "/")
                    if rel != "mimetype":
                        z.write(full, rel)
        return fixed[0]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 1
    src = os.path.abspath(args[0])
    dst = os.path.abspath(args[1]) if len(args) > 1 else src
    if not os.path.exists(src):
        print(f"파일이 없음: {src}", file=sys.stderr)
        return 1

    targets, geom = scan(src)
    if not targets:
        print("글머리 문단이 없어 건너뜀")
        return 0

    try:
        import win32com.client
    except ImportError:
        print("건너뜀: pywin32 가 없음 (Windows + 한글 환경에서만 동작)", file=sys.stderr)
        return 2
    try:
        hwp = win32com.client.Dispatch("HWPFrame.HwpObject")
    except Exception as e:
        print(f"건너뜀: 한글을 띄울 수 없음 ({e})", file=sys.stderr)
        return 2
    try:
        hwp.RegisterModule("FilePathCheckDLL", "FilePathChecker")
    except Exception:
        pass  # 보안 모듈이 없어도 대개 열린다

    try:
        if not hwp.Open(src, "HWPX", "forceopen:true"):
            print(f"한글이 파일을 열지 못함: {src}", file=sys.stderr)
            return 1
        done = 0
        for para, plen in targets:
            try:
                if hwp.SetPos(0, para, plen) and hwp.HAction.Run(ACTION):
                    done += 1
            except Exception:
                pass          # 한 문단 실패가 전체를 막지 않게 한다
        hwp.SaveAs(dst, "HWPX", "")
        hwp.Clear(1)
    finally:
        try:
            hwp.Quit()
        except Exception:
            pass

    print(f"Shift+Tab 내어쓰기 — {done}/{len(targets)}개 문단에 한글 실측값 적용")
    # 글머리 문단은 좌여백만(내어쓰기는 방금 한글이 잰 값), 나머지는 둘 다 되돌린다
    hit = {i for i, _ in targets}
    want = {i: (left, None if i in hit else intent)
            for i, (left, intent) in geom.items()}
    back = restore_geom(dst, want)
    if back:
        print(f"한글이 바꾼 문단 여백 {back}개 복원")
    print(f"저장: {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
