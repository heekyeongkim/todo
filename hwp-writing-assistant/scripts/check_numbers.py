#!/usr/bin/env python3
"""check_numbers.py — 행정문서 원고의 숫자 검증

사용법:
    python check_numbers.py <원고.md 또는 문서.hwpx> [--strict]

검증 항목
    A. 표 합계     — '계/합계/총계/소계' 행·열이 나머지 항목의 합과 맞는가
    B. 백분율 합   — 비율·구성비 열의 합이 100%인가
    C. 괄호 내역   — '총 100명(A 40명, B 50명)' 형태의 내역 합이 총계와 맞는가
    D. 증감률      — 'A에서 B로 N% 증가/감소'의 N이 실제 계산값과 맞는가
    E. 날짜·기간   — 존재하지 않는 날짜, 시작>종료 역전, 명시된 개월수 불일치
    F. 표기 일관성 — 천단위 쉼표 혼용
    G. 근거 표기   — 조사·통계 수치에 ※ 출처가 달려 있는가

종료 코드: 오류(❌)가 하나라도 있으면 1, 아니면 0. --strict 를 주면 경고(⚠)도 1로 처리한다.
공문서 관례에 따라 △ 와 ▽ 는 음수로 해석한다.
"""
import sys, os, re, calendar

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

TOTAL_WORDS = ("계", "합계", "총계", "소계", "누계", "총합", "합")
PCT_WORDS = ("%", "％", "비율", "구성비", "비중", "점유율")
STAT_WORDS = ("조사", "통계", "설문", "실태", "집계", "분석 결과", "조사에 따르면",
              "나타났", "나타남", "응답", "평균")

ERR, WARN, INFO = "❌", "⚠", "·"


class Report:
    def __init__(self):
        self.items = []

    def add(self, level, cat, line, msg):
        self.items.append((level, cat, line, msg))

    def counts(self):
        return (sum(1 for i in self.items if i[0] == ERR),
                sum(1 for i in self.items if i[0] == WARN))


# ------------------------------------------------------------------ 수치 파싱
NUM_RE = re.compile(r"[△▽▲]?\s*\d[\d,]*(?:\.\d+)?")


def to_num(s):
    """'1,234' → 1234.0 / '△5.2' → -5.2 / 숫자가 아니면 None"""
    if s is None:
        return None
    t = s.strip()
    if not t:
        return None
    neg = t[0] in "△▽"
    t = t.lstrip("△▽▲").strip()
    m = re.fullmatch(r"(\d[\d,]*(?:\.\d+)?)\s*[^\d]*", t)
    if not m:
        return None
    try:
        v = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    return -v if neg else v


def is_total_label(s):
    t = re.sub(r"[\s()（）]", "", s or "")
    return t in TOTAL_WORDS or any(t.endswith(w) for w in ("합계", "총계", "소계", "누계"))


def decimals(vals):
    d = 0
    for v in vals:
        s = f"{v}"
        if "." in s:
            d = max(d, len(s.split(".")[1].rstrip("0")))
    return d


def tol_for(vals):
    """반올림 누적 오차 허용치. 정수만 있으면 0, 소수가 있으면 자릿수 기준."""
    d = decimals(vals)
    if d == 0:
        return 0.0
    return 0.5 * len(vals) * (10 ** -d) + 1e-9


# ------------------------------------------------------------------ 표 파싱
def parse_tables(lines):
    """마크다운 파이프 표를 (시작줄번호, [[셀]]) 목록으로 뽑는다."""
    tables, i = [], 0
    while i < len(lines):
        if lines[i].strip().startswith("|"):
            start, rows = i, []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                    rows.append(cells)
                i += 1
            if len(rows) >= 2:
                tables.append((start + 1, rows))
        else:
            i += 1
    return tables


def check_tables(tables, rep):
    for ln, rows in tables:
        head, body = rows[0], rows[1:]
        ncol = max(len(r) for r in rows)

        # --- A-1. 합계 '행' 검증
        tot_rows = [r for r in body if r and is_total_label(r[0])]
        item_rows = [r for r in body if r and not is_total_label(r[0])]
        for tr in tot_rows:
            for c in range(1, ncol):
                tv = to_num(tr[c]) if c < len(tr) else None
                if tv is None:
                    continue
                parts = [to_num(r[c]) for r in item_rows if c < len(r)]
                parts = [p for p in parts if p is not None]
                if len(parts) < 2:
                    continue
                s = sum(parts)
                col = head[c] if c < len(head) else f"{c+1}열"
                if abs(s - tv) > tol_for(parts + [tv]):
                    rep.add(ERR, "표 합계", ln,
                            f"'{col}' 열의 합계가 맞지 않음 — 표기 {tr[c]}, 항목 합 {fmt(s)} "
                            f"(차이 {fmt(s - tv)})")
                else:
                    rep.add(INFO, "표 합계", ln, f"'{col}' 열 합계 일치 ({fmt(tv)})")

        # --- A-2. 합계 '열' 검증
        tcols = [c for c in range(ncol) if c < len(head) and is_total_label(head[c])]
        for tc in tcols:
            for r in body:
                tv = to_num(r[tc]) if tc < len(r) else None
                if tv is None:
                    continue
                parts = [to_num(r[c]) for c in range(1, ncol)
                         if c != tc and c < len(r) and c not in tcols]
                parts = [p for p in parts if p is not None]
                if len(parts) < 2:
                    continue
                s = sum(parts)
                if abs(s - tv) > tol_for(parts + [tv]):
                    rep.add(ERR, "표 합계", ln,
                            f"'{r[0]}' 행의 합계가 맞지 않음 — 표기 {r[tc]}, 항목 합 {fmt(s)} "
                            f"(차이 {fmt(s - tv)})")

        # --- B. 백분율 열의 합
        for c in range(ncol):
            h = head[c] if c < len(head) else ""
            if not any(w in h for w in PCT_WORDS):
                continue
            parts = [to_num(r[c]) for r in item_rows if c < len(r)]
            parts = [p for p in parts if p is not None]
            if len(parts) < 2:
                continue
            s = sum(parts)
            if abs(s - 100) <= max(0.5, 0.1 * len(parts)):
                rep.add(INFO, "백분율", ln, f"'{h}' 열 합 {fmt(s)}% (100% 부합)")
            elif 90 <= s <= 110:
                rep.add(WARN, "백분율", ln,
                        f"'{h}' 열의 합이 {fmt(s)}% — 100%와 어긋남. 반올림 때문인지 확인 필요")
            else:
                rep.add(ERR, "백분율", ln, f"'{h}' 열의 합이 {fmt(s)}% 로 100%가 아님")


def fmt(v):
    if abs(v - round(v)) < 1e-9:
        return f"{int(round(v)):,}"
    return f"{v:,.2f}".rstrip("0").rstrip(".")


# ------------------------------------------------------------------ C. 괄호 내역
BREAKDOWN = re.compile(
    r"(?:총|계|모두|전체)\s*([\d,]+(?:\.\d+)?)\s*(명|건|개|억원|만원|천원|원|개소|시간|일|명분)?"
    r"\s*[(（]([^)）]*)[)）]")


def check_breakdown(lines, rep):
    for i, ln in enumerate(lines, 1):
        for m in BREAKDOWN.finditer(ln):
            total = to_num(m.group(1))
            unit = m.group(2) or ""
            inner = m.group(3)
            if total is None:
                continue
            # 괄호 안에서 '라벨 숫자단위' 조각을 뽑는다
            if unit:
                parts = [to_num(x) for x in re.findall(r"([\d,]+(?:\.\d+)?)\s*" + re.escape(unit), inner)]
            else:
                parts = [to_num(x) for x in re.findall(r"[\d,]+(?:\.\d+)?", inner)]
            parts = [p for p in parts if p is not None]
            if len(parts) < 2:
                continue
            s = sum(parts)
            if abs(s - total) > tol_for(parts + [total]):
                rep.add(ERR, "괄호 내역", i,
                        f"'총 {m.group(1)}{unit}'인데 괄호 내역 합은 {fmt(s)}{unit} "
                        f"(차이 {fmt(s - total)}{unit}) — \"{m.group(0)[:50]}\"")
            else:
                rep.add(INFO, "괄호 내역", i, f"총 {fmt(total)}{unit} = 내역 합 일치")


# ------------------------------------------------------------------ D. 증감률
CHANGE = re.compile(
    r"([\d,]+(?:\.\d+)?)\s*(?:명|건|개|억원|만원|천원|원|%)?\s*(?:에서|→)\s*"
    r"([\d,]+(?:\.\d+)?)\s*(?:명|건|개|억원|만원|천원|원|%)?\s*(?:으?로)?[^.。\n]{0,20}?"
    r"([\d,]+(?:\.\d+)?)\s*(?:%|％|퍼센트)\s*(증가|감소|상승|하락|늘|줄)")

# '2025년' 같은 연도는 비교 대상 수치가 아니므로 마스킹한다.
# (마스킹하지 않으면 "2024년 300억원에서 2025년 370억원으로" 에서 연도 2025를 값으로 잡는다)
YEAR_TOKEN = re.compile(r"(?:19|20)\d{2}\s*년도?")


def check_change_rate(lines, rep):
    for i, raw in enumerate(lines, 1):
        ln = YEAR_TOKEN.sub(lambda m: " " * len(m.group(0)), raw)
        for m in CHANGE.finditer(ln):
            a, b, claimed = to_num(m.group(1)), to_num(m.group(2)), to_num(m.group(3))
            if None in (a, b, claimed) or a == 0:
                continue
            actual = abs(b - a) / a * 100
            direction = m.group(4)
            up = direction in ("증가", "상승", "늘")
            if (b > a) != up:
                rep.add(ERR, "증감 방향", i,
                        f"{fmt(a)} → {fmt(b)} 인데 '{direction}'으로 서술됨")
            elif abs(actual - claimed) > max(0.5, actual * 0.02):
                rep.add(ERR, "증감률", i,
                        f"{fmt(a)} → {fmt(b)} 의 실제 변화율은 {actual:.1f}% 인데 "
                        f"{fmt(claimed)}%로 표기됨")
            else:
                rep.add(INFO, "증감률", i, f"{fmt(a)} → {fmt(b)} = {actual:.1f}% 부합")


# ------------------------------------------------------------------ E. 날짜·기간
DATE = re.compile(r"(\d{4})\s*[.\-년]\s*(\d{1,2})\s*[.\-월]\s*(\d{1,2})\s*[.일]?")
YM = re.compile(r"(\d{4})\s*[.\-년]\s*(\d{1,2})\s*월?")
PERIOD_M = re.compile(r"[(（]\s*(?:총\s*)?(\d{1,3})\s*(?:개월|개월간)\s*[)）]")


def check_dates(lines, rep):
    for i, ln in enumerate(lines, 1):
        for m in DATE.finditer(ln):
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if not (1 <= mo <= 12):
                rep.add(ERR, "날짜", i, f"존재하지 않는 월: {m.group(0).strip()}")
                continue
            last = calendar.monthrange(y, mo)[1]
            if not (1 <= d <= last):
                rep.add(ERR, "날짜", i,
                        f"존재하지 않는 날짜: {m.group(0).strip()} ({y}년 {mo}월은 {last}일까지)")

        # 기간 역전 + 개월수
        if "~" in ln or "∼" in ln:
            seg = re.split(r"[~∼]", ln)
            if len(seg) >= 2:
                a = YM.search(seg[0][::-1][:60][::-1])
                b = YM.search(seg[1][:60])
                if a and b:
                    ay, am = int(a.group(1)), int(a.group(2))
                    by, bm = int(b.group(1)), int(b.group(2))
                    if (by, bm) < (ay, am):
                        rep.add(ERR, "기간", i,
                                f"기간이 역전됨: {ay}.{am} ~ {by}.{bm}")
                    else:
                        months = (by - ay) * 12 + (bm - am)
                        pm = PERIOD_M.search(ln)
                        if pm:
                            claimed = int(pm.group(1))
                            # 시작·종료월 포함 여부에 따라 months 또는 months+1
                            if claimed not in (months, months + 1):
                                rep.add(ERR, "기간", i,
                                        f"{ay}.{am} ~ {by}.{bm} 은 {months}~{months+1}개월인데 "
                                        f"{claimed}개월로 표기됨")
                            else:
                                rep.add(INFO, "기간", i, f"{claimed}개월 표기 부합")


# ------------------------------------------------------------------ F. 표기 일관성
def check_comma_style(lines, rep):
    plain, commaed = [], []
    for i, ln in enumerate(lines, 1):
        body = re.sub(r"(19|20)\d{2}\s*년?", "", ln)          # 연도 제외
        body = re.sub(r"\d+\s*(?:개월|시간|세|급|호|차|쪽|면)", "", body)  # 소수 단위 제외
        for m in re.finditer(r"(?<![\d,.])(\d{4,})(?![\d,.])", body):
            plain.append((i, m.group(1)))
        for m in re.finditer(r"\d{1,3}(?:,\d{3})+", body):
            commaed.append((i, m.group(0)))
    if plain and commaed:
        ex_p = ", ".join(f"{v}(줄 {l})" for l, v in plain[:3])
        ex_c = ", ".join(f"{v}(줄 {l})" for l, v in commaed[:3])
        rep.add(WARN, "표기 일관성", plain[0][0],
                f"천단위 쉼표가 혼용됨 — 없는 예: {ex_p} / 있는 예: {ex_c}")


# ------------------------------------------------------------------ G. 근거 표기
def check_sources(lines, rep):
    for i, ln in enumerate(lines, 1):
        s = ln.strip()
        if s.startswith("※") or s.startswith("|"):
            continue
        if not NUM_RE.search(s):
            continue
        if not any(w in s for w in STAT_WORDS):
            continue
        nearby = " ".join(lines[i - 1:i + 2])   # 바로 다음 줄까지 ※ 를 찾는다
        if "※" not in nearby:
            rep.add(WARN, "근거 표기", i,
                    f"통계·조사 수치로 보이는데 ※ 출처가 없음 — \"{s[:45]}…\"")


# ------------------------------------------------------------------ 입력
def _hwpx_paras(xml, out, unesc):
    for p in re.findall(r"<hp:p\b.*?</hp:p>", xml, re.S):
        t = "".join(re.findall(r"<hp:t[^>]*>([^<]*)</hp:t>", p))
        if t.strip():
            out.append(unesc(t))


def _hwpx_table(tbl, out, unesc):
    """hwpx 표를 마크다운 파이프 행으로 되살려 표 합계 검증이 걸리게 한다."""
    grid = {}
    for tc in re.findall(r"<hp:tc\b.*?</hp:tc>", tbl, re.S):
        addr = re.search(r'<hp:cellAddr colAddr="(\d+)" rowAddr="(\d+)"', tc)
        if not addr:
            continue
        col, row = int(addr.group(1)), int(addr.group(2))
        txt = "".join(re.findall(r"<hp:t[^>]*>([^<]*)</hp:t>", tc))
        grid[(row, col)] = unesc(txt).strip()
    if not grid:
        return
    nrow = max(r for r, _ in grid) + 1
    ncol = max(c for _, c in grid) + 1
    for r in range(nrow):
        out.append("| " + " | ".join(grid.get((r, c), "") for c in range(ncol)) + " |")


def load_text(path):
    if path.lower().endswith(".hwpx"):
        import zipfile, html as _h
        out = []
        with zipfile.ZipFile(path) as z:
            for n in sorted(x for x in z.namelist()
                            if re.match(r"Contents/section\d+\.xml$", x)):
                xml = z.read(n).decode("utf-8")
                pos = 0
                for m in re.finditer(r"<hp:tbl\b.*?</hp:tbl>", xml, re.S):
                    _hwpx_paras(xml[pos:m.start()], out, _h.unescape)
                    _hwpx_table(m.group(0), out, _h.unescape)
                    pos = m.end()
                _hwpx_paras(xml[pos:], out, _h.unescape)
        return out
    return open(path, encoding="utf-8").read().splitlines()


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 1
    path = args[0]
    if not os.path.exists(path):
        print(f"파일을 찾을 수 없음: {path}")
        return 1
    lines = load_text(path)
    rep = Report()

    check_tables(parse_tables(lines), rep)
    check_breakdown(lines, rep)
    check_change_rate(lines, rep)
    check_dates(lines, rep)
    check_comma_style(lines, rep)
    check_sources(lines, rep)

    print(f"숫자 검증: {path}")
    print("=" * 64)
    errs, warns = rep.counts()
    for level in (ERR, WARN, INFO):
        group = [i for i in rep.items if i[0] == level]
        if not group:
            continue
        if level == INFO:
            print(f"\n[검증 통과 {len(group)}건]")
            for _, cat, ln, msg in group:
                print(f"  · (줄 {ln}) {cat}: {msg}")
        else:
            label = "오류" if level == ERR else "확인 필요"
            print(f"\n[{label} {len(group)}건]")
            for _, cat, ln, msg in group:
                print(f"  {level} (줄 {ln}) {cat}: {msg}")

    print("\n" + "=" * 64)
    if errs == 0 and warns == 0:
        print("검증 결과: 발견된 문제 없음")
    else:
        print(f"검증 결과: 오류 {errs}건, 확인 필요 {warns}건")
    print("※ 자동 검증은 문서 내부의 산술·형식 정합성만 본다. "
          "출처 원문과의 대조는 사람이 해야 한다.")

    if errs:
        return 1
    if warns and "--strict" in sys.argv:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
