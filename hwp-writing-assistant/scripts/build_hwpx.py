#!/usr/bin/env python3
"""
build_hwpx.py — AI 친화적 행정문서 가이드라인에 맞춘 HWPX(한글) 문서 생성기

사용법:
    python build_hwpx.py <입력.md> <출력.hwpx> [--template 파일.hwpx]

서식은 하나다 — 행안부 가이드라인 기반 + 실제 부처 계획서 서식.
    개조식 명사형 종결(마침표 없음), 제목 아래 번호 없는 요약, 그 다음부터 1. 2. 3.
    계층: 1. = □ (0수준) → ○ → - → · , 부연 ※ · 각주 * 는 위 항목보다 한 칸 안쪽
    15pt 함초롬바탕(※·표는 12pt 맑은 고딕), 여백 좌우 20mm 상하 10mm, [참고N] 별지는 새 쪽

입력 파일(.md)의 줄 단위 마크업:
    # 제목            → 문서 제목
    > 요약문장        → 요약 문단 (문서 앞부분, 서술식)
    1. / 가. 로 시작  → 번호 항목(대제목, 굵게)
    □ 또는 [] 로 시작 → □ 대항목
    ○ 또는 * 로 시작  → ○ 중항목
    - 로 시작         → - 세부항목
    · 또는 . 로 시작  → · 세부항목
    ※ 로 시작         → ※ 근거·출처·정량 데이터
    (그 외 일반 줄)   → 서술식 본문 문단 (주어·서술어를 갖춘 문장)

규칙: 특수기호(□ ○ - · ※)는 유니코드 문자로 출력하며, 글꼴은 템플릿의 함초롬바탕을 따른다.

생성 직후 반드시 scripts/hwpx_polish.py 를 이어서 실행할 것
(내어쓰기·어절 줄바꿈·레이아웃 캐시 제거는 이 스크립트가 하지 않는다).
"""
import sys, os, re, html, zipfile, shutil, tempfile

# 한글 윈도우 콘솔(cp949)에서 —, ※ 등이 UnicodeEncodeError를 내지 않게 한다
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ---------------------------------------------------------------- 서식 (단일)
# 행안부 「AI 시대 행정문서 작성 가이드라인」을 바탕으로, 실제 부처 계획서의
# 서식·문체를 반영한 하나의 서식이다. ID 는 template-field.hwpx 에서 추출했다.
TEMPLATE = "template-field.hwpx"
STYLE = {
    "title":   ("38", "13"),   # 20pt 명조 가운데 — 한 줄 제목
    "sheet":   ("23", "14"),   # 18pt 명조 가운데 — [참고N] 별지 제목 (새 쪽에서 시작)
    "summary": ("40", "16"),   # 제목 아래 번호 없는 요약 본문 (기호 없음)
    "hnum":    ("39", "15"),   # 1. 2. 3. — 15pt 함초롬바탕 굵게
    "box":     ("39", "15"),   # □ 는 1. 과 동급
    "bullet":  ("43", "16"),   # ○ — 15pt 함초롬바탕
    "dash":    ("28", "16"),   # -
    "dot":     ("28", "16"),   # ·
    "note":    ("41", "19"),   # ※ 부연 — 12pt 맑은 고딕
    "star":    ("41", "19"),   # * 각주 — 12pt 맑은 고딕
    "body":    ("43", "16"),
    "cell":    ("26", "27"),   # 표 셀 — 12pt 맑은 고딕
}
# 계층은 선행 공백이 아니라 paraPr 의 left 로 표현한다 — hwpx_polish 가 기호를 보고 넣는다.
# 요약 본문에는 기호를 달지 않으므로 mark 에 summary 키가 없다.
MARK = {"box": "□ ", "bullet": "○ ", "dash": "- ", "dot": "· ",
        "note": "※ ", "star": "* "}


def esc(t):
    return html.escape(t, quote=False)


def classify(line, style=None):
    style = style or STYLE
    s = line.strip()
    if not s:
        return None, ""
    if s.startswith("## "):
        return "hnum", s[3:].strip()   # 번호 없는 절 제목 (`## 요약`)
    if s.startswith("# "):
        return "title", s[2:].strip()
    if s.startswith("> "):
        return "summary", s[2:].strip()
    if s.startswith("[참고") and "sheet" in style:
        return "sheet", s          # [참고1] … 별지 제목
    if re.match(r"^(\d+\.|[가-힣]\.)\s", s):
        return "hnum", s
    if s.startswith("□") or s.startswith("[]"):
        return "box", re.sub(r"^(□|\[\])\s*", "", s)
    if s.startswith("* "):
        # 실무 서식에서 * 는 각주, 가이드라인 서식에서는 ○ 의 대체 표기다
        return ("star" if "star" in style else "bullet"), s[2:].strip()
    if s.startswith("○"):
        return "bullet", re.sub(r"^○\s*", "", s)
    if s.startswith("- "):
        return "dash", s[2:].strip()
    if s.startswith("·") or s.startswith(". "):
        return "dot", re.sub(r"^(·|\.)\s*", "", s)
    if s.startswith("※"):
        return "note", re.sub(r"^※\s*", "", s)
    return "body", s


def make_p(kind, text, pid, style=None, mark=None):
    style, mark = style or STYLE, mark if mark is not None else MARK
    para, char = style.get(kind, style["body"])
    marker = mark.get(kind, "")
    body = esc(marker + text)
    # 별지([참고N])는 새 쪽에서 시작한다 — 실무 문서가 별지를 별도 쪽으로 뺀다
    brk = "1" if kind == "sheet" else "0"
    return (f'<hp:p id="{pid}" paraPrIDRef="{para}" styleIDRef="0" '
            f'pageBreak="{brk}" columnBreak="0" merged="0">'
            f'<hp:run charPrIDRef="{char}"><hp:t>{body}</hp:t></hp:run></hp:p>')


def make_title_p(secpr, text, pid, style=None):
    para, char = (style or STYLE)["title"]
    return (f'<hp:p id="{pid}" paraPrIDRef="{para}" styleIDRef="0" '
            f'pageBreak="0" columnBreak="0" merged="0">'
            f'<hp:run charPrIDRef="{char}">{secpr}</hp:run>'
            f'<hp:run charPrIDRef="{char}"><hp:t>{esc(text)}</hp:t></hp:run></hp:p>')


# ---------------------------------------------------------------- 표 생성
# OWPML 표 구조는 실제 한글 저장 파일에서 확인한 순서를 따른다.
#   <hp:tbl> : 속성 → <hp:sz> <hp:pos> <hp:outMargin> <hp:inMargin> → <hp:tr>*
#   <hp:tc>  : <hp:subList> → <hp:cellAddr> → <hp:cellSpan> → <hp:cellSz> → <hp:cellMargin>
# (subList가 cellAddr보다 앞에 온다. 순서가 틀리면 한글이 파일을 열지 못한다.)

CELL_MARGIN = '<hp:cellMargin left="510" right="510" top="141" bottom="141"/>'
ROW_H = 2800  # 한 줄 기준 셀 높이. linesegarray가 없으므로 한글이 열 때 재계산한다.

BORDER_BODY = (
    '<hh:borderFill id="{id}" threeD="0" shadow="0" centerLine="NONE" breakCellSeparateLine="0">'
    '<hh:slash type="NONE" Crooked="0" isCounter="0"/>'
    '<hh:backSlash type="NONE" Crooked="0" isCounter="0"/>'
    '<hh:leftBorder type="SOLID" width="0.12 mm" color="#000000"/>'
    '<hh:rightBorder type="SOLID" width="0.12 mm" color="#000000"/>'
    '<hh:topBorder type="SOLID" width="0.12 mm" color="#000000"/>'
    '<hh:bottomBorder type="SOLID" width="0.12 mm" color="#000000"/>'
    '<hh:diagonal type="SOLID" width="0.1 mm" color="#000000"/>'
    '</hh:borderFill>')

BORDER_HEAD = (
    '<hh:borderFill id="{id}" threeD="0" shadow="0" centerLine="NONE" breakCellSeparateLine="0">'
    '<hh:slash type="NONE" Crooked="0" isCounter="0"/>'
    '<hh:backSlash type="NONE" Crooked="0" isCounter="0"/>'
    '<hh:leftBorder type="SOLID" width="0.12 mm" color="#000000"/>'
    '<hh:rightBorder type="SOLID" width="0.12 mm" color="#000000"/>'
    '<hh:topBorder type="SOLID" width="0.12 mm" color="#000000"/>'
    '<hh:bottomBorder type="SOLID" width="0.12 mm" color="#000000"/>'
    '<hh:diagonal type="SOLID" width="0.1 mm" color="#000000"/>'
    '<hc:fillBrush><hc:winBrush faceColor="#E8E8E8" hatchColor="#999999" alpha="0"/></hc:fillBrush>'
    '</hh:borderFill>')


def _bump(hdr, tag, n):
    """<hh:{tag} itemCnt="N"> 의 개수를 n 만큼 늘린다."""
    m = re.search(r'(<hh:%s itemCnt=")(\d+)(")' % tag, hdr)
    if not m:
        return hdr
    return hdr[:m.start()] + m.group(1) + str(int(m.group(2)) + n) + m.group(3) + hdr[m.end():]


def make_cell_parapr(src_pr, new_id, align):
    """템플릿 paraPr을 복제해 표 셀용으로 만든다.
    셀 안에서는 내어쓰기(intent)와 문단 위 간격(prev)이 있으면 안 되므로 0으로 지운다."""
    pr = re.sub(r'(<hh:paraPr id=")\d+(")', r'\g<1>%s\g<2>' % new_id, src_pr, count=1)
    pr = re.sub(r'(<hh:align horizontal=")\w+(")', r'\g<1>%s\g<2>' % align, pr, count=1)
    pr = re.sub(r'(<hc:intent value=")-?\d+(")', r'\g<1>0\g<2>', pr)
    pr = re.sub(r'(<hc:prev value=")-?\d+(")', r'\g<1>0\g<2>', pr)
    return pr


def _disp_w(s):
    """열 너비 배분용 표시폭. 전각 2, 반각 1."""
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in s)


def col_widths(rows, total):
    """열별 최대 표시폭에 비례해 너비를 나누되, 합이 정확히 total이 되게 맞춘다."""
    ncol = max(len(r) for r in rows)
    want = []
    for c in range(ncol):
        w = max((_disp_w(r[c]) for r in rows if c < len(r)), default=0)
        want.append(max(w, 4) + 2)   # 최소폭 + 좌우 여백 몫
    s = sum(want)
    ws = [max(2000, int(total * w / s)) for w in want]
    ws[-1] += total - sum(ws)        # 반올림 오차를 마지막 열에 흡수 → 합 == total 보장
    return ws


def make_table(rows, has_header, total_w, bf_body, bf_head, pp_c, pp_l, char, tid, pid0):
    widths = col_widths(rows, total_w)
    ncol, nrow = len(widths), len(rows)
    pid = pid0
    trs = []
    for r, row in enumerate(rows):
        tcs = []
        for c in range(ncol):
            text = row[c] if c < len(row) else ""
            head = has_header and r == 0
            bf = bf_head if head else bf_body
            pp = pp_c if (head or _is_num(text) or not text) else pp_l
            tcs.append(
                f'<hp:tc name="" header="{1 if head else 0}" hasMargin="0" protect="0" '
                f'editable="0" dirty="0" borderFillIDRef="{bf}">'
                f'<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER" '
                f'linkListIDRef="0" linkListNextIDRef="0" textWidth="0" textHeight="0" '
                f'hasTextRef="0" hasNumRef="0">'
                f'<hp:p id="{pid}" paraPrIDRef="{pp}" styleIDRef="0" pageBreak="0" '
                f'columnBreak="0" merged="0">'
                f'<hp:run charPrIDRef="{char}"><hp:t>{esc(text)}</hp:t></hp:run></hp:p>'
                f'</hp:subList>'
                f'<hp:cellAddr colAddr="{c}" rowAddr="{r}"/>'
                f'<hp:cellSpan colSpan="1" rowSpan="1"/>'
                f'<hp:cellSz width="{widths[c]}" height="{ROW_H}"/>'
                f'{CELL_MARGIN}</hp:tc>')
            pid += 1
        trs.append("<hp:tr>" + "".join(tcs) + "</hp:tr>")

    tbl = (f'<hp:tbl id="{tid}" zOrder="0" numberingType="TABLE" textWrap="TOP_AND_BOTTOM" '
           f'textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" pageBreak="CELL" '
           f'repeatHeader="{1 if has_header else 0}" rowCnt="{nrow}" colCnt="{ncol}" '
           f'cellSpacing="0" borderFillIDRef="{bf_body}" noAdjust="0">'
           f'<hp:sz width="{total_w}" widthRelTo="ABSOLUTE" height="{nrow * ROW_H}" '
           f'heightRelTo="ABSOLUTE" protect="0"/>'
           f'<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" '
           f'holdAnchorAndSO="0" vertRelTo="PARA" horzRelTo="PARA" vertAlign="TOP" '
           f'horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
           f'<hp:outMargin left="283" right="283" top="283" bottom="283"/>'
           f'<hp:inMargin left="510" right="510" top="141" bottom="141"/>'
           + "".join(trs) + '</hp:tbl>')

    p = (f'<hp:p id="{pid}" paraPrIDRef="{pp_l}" styleIDRef="0" pageBreak="0" '
         f'columnBreak="0" merged="0"><hp:run charPrIDRef="{char}">{tbl}</hp:run></hp:p>')
    return p, pid + 1


def _is_num(s):
    return bool(re.fullmatch(r"[△▽▲-]?[\d,]+(\.\d+)?\s*[%원명건개년월일차%]*", s.strip()))


def parse_table_rows(block):
    """마크다운 파이프 표 → 행 목록. |---|---| 구분선이 있으면 첫 행이 머리행."""
    rows, has_header = [], False
    for ln in block:
        s = ln.strip().strip("|")
        cells = [c.strip() for c in s.split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            has_header = True          # 구분선 자체는 행으로 넣지 않는다
            continue
        rows.append(cells)
    return rows, has_header


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    pos = [a for i, a in enumerate(sys.argv[1:], 1)
           if not a.startswith("--") and not sys.argv[i - 1].startswith("--")]
    src, out = pos[0], pos[1]

    style, mark = STYLE, MARK
    tpl = TEMPLATE
    if "--template" in sys.argv:
        tpl = sys.argv[sys.argv.index("--template") + 1]
    here = os.path.dirname(os.path.abspath(__file__))
    if not os.path.isabs(tpl) and not os.path.exists(tpl):
        # scripts/ 하위에서 실행되므로 스킬 루트(상위 디렉터리)도 함께 찾는다
        for cand in (os.path.join(here, tpl), os.path.join(here, os.pardir, tpl)):
            if os.path.exists(cand):
                tpl = os.path.abspath(cand)
                break
    if not os.path.exists(tpl):
        print(f"템플릿을 찾을 수 없음: {tpl}", file=sys.stderr)
        sys.exit(1)

    lines = open(src, encoding="utf-8").read().splitlines()
    tmp = tempfile.mkdtemp()
    with zipfile.ZipFile(tpl) as z:
        z.extractall(tmp)

    sec_path = os.path.join(tmp, "Contents", "section0.xml")
    xml = open(sec_path, encoding="utf-8").read()

    # 헤더(선언 + <hs:sec ...>) 추출
    head = xml[:xml.index("<hp:p")]
    # secPr 블록 추출 (페이지 설정 유지)
    m = re.search(r"<hp:secPr\b.*?</hp:secPr>", xml, re.S)
    secpr = m.group(0) if m else ""

    # 표에 쓸 자원(테두리·셀 문단모양)을 header.xml에 추가
    hdr_path = os.path.join(tmp, "Contents", "header.xml")
    hdr = open(hdr_path, encoding="utf-8").read()
    bf_ids = [int(i) for i in re.findall(r'<hh:borderFill id="(\d+)"', hdr)]
    pp_ids = [int(i) for i in re.findall(r'<hh:paraPr id="(\d+)"', hdr)]
    bf_body, bf_head = str(max(bf_ids) + 1), str(max(bf_ids) + 2)
    pp_c, pp_l = str(max(pp_ids) + 1), str(max(pp_ids) + 2)
    base_pr = re.search(r'<hh:paraPr id="%s".*?</hh:paraPr>' % style["cell"][0], hdr, re.S).group(0)

    # 요약 본문은 기호를 달지 않는다. 기호가 없으니 내어쓰기도 필요 없고, 대신
    # 절 제목보다 한 수준 안쪽(글자크기의 반 칸)에서 시작하도록 좌여백만 준다.
    extra_prs = []
    if True:
        spr = re.search(r'<hh:paraPr id="%s".*?</hh:paraPr>' % style["summary"][0], hdr, re.S)
        hm = re.search(r'<hh:charPr id="%s"[^>]*height="(\d+)"' % style["summary"][1], hdr)
        if spr and hm:
            pp_sum = str(max(pp_ids) + 3)
            c = re.sub(r'(<hh:paraPr id=")\d+(")', r'\g<1>%s\g<2>' % pp_sum, spr.group(0), count=1)
            # paraPr 은 <hp:switch> 안에 case/default 두 벌이 들어 있다. 한 벌만 고치면
            # 한글이 나머지 한 벌을 읽어 되돌려 버리므로 반드시 전부 바꾼다.
            c = re.sub(r'(<hc:left value=")-?\d+(")',
                       r'\g<1>%d\g<2>' % (int(hm.group(1)) // 2), c)
            c = re.sub(r'(<hc:intent value=")-?\d+(")', r'\g<1>0\g<2>', c)
            extra_prs.append(c)
            style = dict(style)
            style["summary"] = (pp_sum, style["summary"][1])

    # 표 너비 = 본문 폭(용지 폭 - 좌우 여백)
    pw = re.search(r'<hp:pagePr[^>]*width="(\d+)"', xml)
    mg = re.search(r'<hp:margin[^>]*left="(\d+)"[^>]*right="(\d+)"', xml)
    total_w = (int(pw.group(1)) - int(mg.group(1)) - int(mg.group(2))) if (pw and mg) else 48190

    # 본문 구성 — 연속된 `|` 줄은 하나의 표 블록으로 묶는다
    paras, pid, tid = [], 1000, 5000
    title_done, ntbl = False, 0
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.strip().startswith("|"):
            block = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                block.append(lines[i])
                i += 1
            rows, has_header = parse_table_rows(block)
            if rows:
                p, pid = make_table(rows, has_header, total_w, bf_body, bf_head,
                                    pp_c, pp_l, style["cell"][1], tid, pid)
                paras.append(p)
                tid += 1
                ntbl += 1
            continue
        kind, text = classify(ln, style)
        i += 1
        if kind is None:
            continue
        if kind == "title" and not title_done:
            paras.append(make_title_p(secpr, text, pid, style))
            title_done = True
        elif kind == "title":
            paras.append(make_p("hnum", text, pid, style, mark))
        else:
            paras.append(make_p(kind, text, pid, style, mark))
        pid += 1

    # 제목이 없으면 빈 secPr 문단을 맨 앞에 삽입
    if not title_done:
        paras.insert(0, make_title_p(secpr, "", pid, style))

    if ntbl:
        hdr = hdr.replace("</hh:borderFills>",
                          BORDER_BODY.format(id=bf_body) + BORDER_HEAD.format(id=bf_head)
                          + "</hh:borderFills>")
        hdr = _bump(hdr, "borderFills", 2)
        extra_prs += [make_cell_parapr(base_pr, pp_c, "CENTER"),
                      make_cell_parapr(base_pr, pp_l, "LEFT")]
    if extra_prs:
        hdr = hdr.replace("</hh:paraProperties>",
                          "".join(extra_prs) + "</hh:paraProperties>")
        hdr = _bump(hdr, "paraProperties", len(extra_prs))
    if ntbl or extra_prs:
        open(hdr_path, "w", encoding="utf-8").write(hdr)

    new_xml = head + "".join(paras) + "</hs:sec>"
    open(sec_path, "w", encoding="utf-8").write(new_xml)

    # 재패키징 (mimetype은 무압축·최상단)
    if os.path.exists(out):
        os.remove(out)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(os.path.join(tmp, "mimetype"), "mimetype",
                compress_type=zipfile.ZIP_STORED)
        for root, _, files in os.walk(tmp):
            for f in files:
                full = os.path.join(root, f)
                rel = os.path.relpath(full, tmp)
                if rel == "mimetype":
                    continue
                z.write(full, rel)
    shutil.rmtree(tmp)
    print(f"생성 완료: {out} (문단 {len(paras)}개, 표 {ntbl}개)")


if __name__ == "__main__":
    main()
