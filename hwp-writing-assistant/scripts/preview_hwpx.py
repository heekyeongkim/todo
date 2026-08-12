#!/usr/bin/env python3
"""preview_hwpx.py — hwpx를 터미널에서 미리 보기

한글을 켜지 않고도 결과를 확인하기 위한 도구다. 표는 ASCII 격자로 그리고,
--detail 을 주면 눈에 보이지 않는 서식(내어쓰기·장평)까지 표시한다.

사용법:
    python preview_hwpx.py <문서.hwpx> [--detail] [--width 80]

--detail 로 확인할 수 있는 것
    [내어쓰기 -2100]  이어지는 줄이 본문 시작 위치에 정렬됨 (값이 없으면 미적용)
    [장평 96%]        어절 줄바꿈을 맞추려고 장평이 조정된 문단
"""
import sys, re, zipfile, html, unicodedata

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def dw(s):
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in s)


def pad(s, w):
    return s + " " * max(0, w - dw(s))


def cut(s, w):
    out = ""
    for ch in s:
        if dw(out + ch) > w:
            return out
        out += ch
    return out


def load(path):
    with zipfile.ZipFile(path) as z:
        hdr = z.read("Contents/header.xml").decode("utf-8")
        secs = [z.read(n).decode("utf-8") for n in sorted(z.namelist())
                if re.match(r"Contents/section\d+\.xml$", n)]
    return hdr, secs


def parse_header(hdr):
    """paraPr → intent, charPr → 장평 을 뽑아 둔다."""
    intent, left = {}, {}
    for m in re.finditer(r'<hh:paraPr id="(\d+)".*?</hh:paraPr>', hdr, re.S):
        v = re.search(r'<hc:intent value="(-?\d+)"', m.group(0))
        intent[m.group(1)] = int(v.group(1)) if v else 0
        l = re.search(r'<hc:left value="(-?\d+)"', m.group(0))
        left[m.group(1)] = int(l.group(1)) if l else 0
    ratio, spacing, height = {}, {}, {}
    for m in re.finditer(r'<hh:charPr id="(\d+)".*?</hh:charPr>', hdr, re.S):
        v = re.search(r'<hh:ratio hangul="(\d+)"', m.group(0))
        ratio[m.group(1)] = int(v.group(1)) if v else 100
        s = re.search(r'<hh:spacing hangul="(-?\d+)"', m.group(0))
        spacing[m.group(1)] = int(s.group(1)) if s else 0
        hh = re.search(r'height="(\d+)"', m.group(0))
        height[m.group(1)] = int(hh.group(1)) if hh else 1500
    return intent, left, ratio, spacing, height


def para_text(p):
    return html.unescape("".join(re.findall(r"<hp:t[^>]*>([^<]*)</hp:t>", p)))


def draw_table(tbl, width, out):
    grid, spans = {}, {}
    for tc in re.findall(r"<hp:tc\b.*?</hp:tc>", tbl, re.S):
        a = re.search(r'<hp:cellAddr colAddr="(\d+)" rowAddr="(\d+)"', tc)
        if not a:
            continue
        c, r = int(a.group(1)), int(a.group(2))
        grid[(r, c)] = html.unescape(
            "".join(re.findall(r"<hp:t[^>]*>([^<]*)</hp:t>", tc))).strip()
        sz = re.search(r'<hp:cellSz width="(\d+)"', tc)
        if sz and r == 0:
            spans[c] = int(sz.group(1))
    if not grid:
        return
    nrow = max(r for r, _ in grid) + 1
    ncol = max(c for _, c in grid) + 1
    hdr_row = 'header="1"' in tbl

    # 실제 셀 너비(HWPUNIT) 비율대로 화면 폭을 나눈다 → 한글에서 볼 모습에 가깝게
    tot = sum(spans.get(c, 1) for c in range(ncol)) or 1
    avail = width - (ncol + 1)
    cw = [max(4, int(avail * spans.get(c, 1) / tot)) for c in range(ncol)]
    cw[-1] += avail - sum(cw)

    bar = "+" + "+".join("-" * w for w in cw) + "+"
    out.append(bar)
    for r in range(nrow):
        cells = [cut(grid.get((r, c), ""), cw[c] - 2) for c in range(ncol)]
        out.append("|" + "|".join(" " + pad(cells[c], cw[c] - 2) + " "
                                  for c in range(ncol)) + "|")
        if r == 0 and hdr_row:
            out.append("+" + "+".join("=" * w for w in cw) + "+")
    out.append(bar)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 1
    detail = "--detail" in sys.argv
    width = 80
    if "--width" in sys.argv:
        width = int(sys.argv[sys.argv.index("--width") + 1])

    hdr, secs = load(args[0])
    intent, left, ratio, spacing, height = parse_header(hdr)
    out, ntbl, nind, nratio = [], 0, 0, 0

    def emit(chunk):
        emit_paras(chunk, intent, left, ratio, spacing, height, detail, width, out)

    for xml in secs:
        pos = 0
        for m in re.finditer(r"<hp:tbl\b.*?</hp:tbl>", xml, re.S):
            emit(xml[pos:m.start()])
            draw_table(m.group(0), width, out)
            ntbl += 1
            pos = m.end()
        emit(xml[pos:])

    for p in re.findall(r"<hp:p\b[^>]*>", "".join(secs)):
        pid = re.search(r'paraPrIDRef="(\d+)"', p)
        if pid and intent.get(pid.group(1), 0) < 0:
            nind += 1
    for c in set(re.findall(r'charPrIDRef="(\d+)"', "".join(secs))):
        if ratio.get(c, 100) != 100:
            nratio += 1

    print("\n".join(out))
    print()
    print("-" * width)
    print(f"문단 {sum(1 for l in out if l and not l.startswith(('+', '|')))}개 · "
          f"표 {ntbl}개 · 내어쓰기 적용 문단 {nind}개 · 장평 조정된 글자모양 {nratio}종")
    print("※ 터미널 근사 표시다. 줄바꿈 위치와 글꼴은 한글에서 열어야 정확하다.")
    return 0


def emit_paras(xml, intent, left, ratio, spacing, height, detail, width, out):
    for p in re.findall(r"<hp:p\b.*?</hp:p>", xml, re.S):
        t = para_text(p)
        if not t.strip():
            continue
        pid_m = re.search(r'paraPrIDRef="(\d+)"', p)
        cid_m = re.search(r'charPrIDRef="(\d+)"', p)
        pid = pid_m.group(1) if pid_m else "0"
        h = height.get(cid_m.group(1), 1500) if cid_m else 1500
        # 화면 1칸 = 반각 = 글자크기의 절반. 수준별 들여쓰기를 눈에 보이게 옮긴다.
        lead = " " * int(round(left.get(pid, 0) / max(1, h // 2)))
        tag = ""
        if detail:
            bits = []
            if left.get(pid, 0):
                bits.append(f"좌여백 {left[pid]}")
            if intent.get(pid, 0) < 0:
                bits.append(f"내어쓰기 {intent[pid]}")
            # 자간·장평은 run 마다 다를 수 있으므로 문단 전체의 범위를 보여준다
            cids = re.findall(r'charPrIDRef="(\d+)"', p)
            for label, table, base, unit in (("자간", spacing, 0, ""),
                                             ("장평", ratio, 100, "%")):
                vals = sorted({table.get(c, base) for c in cids})
                if vals and vals != [base]:
                    rng = f"{vals[0]}" if len(vals) == 1 else f"{vals[0]}~{vals[-1]}"
                    bits.append(f"{label} {rng}{unit}")
            if bits:
                tag = "   [" + ", ".join(bits) + "]"
        # 좌여백(수준)과 내어쓰기를 화면에서도 흉내내어 실제 시작점을 보이게 한다
        m = re.match(r"^(\s*[□○\-·※*]\s+)", t)
        ind = lead + " " * (dw(m.group(1)) if m else 0)
        first, rest = True, t
        while rest:
            pre = lead if first else ind
            lim = width - dw(pre)
            chunk = cut(rest, lim)
            if len(chunk) < len(rest):
                sp = chunk.rfind(" ")
                if sp > lim // 3:
                    chunk = chunk[:sp]
            out.append(pre + (chunk if first else chunk.strip()))
            rest = rest[len(chunk):].lstrip()
            first = False
        if tag:
            out[-1] += tag
        out.append("")


if __name__ == "__main__":
    sys.exit(main())
