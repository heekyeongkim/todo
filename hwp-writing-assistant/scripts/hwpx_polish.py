#!/usr/bin/env python3
"""hwpx 공문서 후처리 v2
0) 레이아웃 캐시(linesegarray) 제거 — 글자 겹침 방지
1) 어절 줄바꿈 설정 (breakNonLatinWord="BREAK_WORD" — 반전 매핑 주의, polish_header_break 참고)
2) ▲ 나열 -> ①②③ 치환 + 금지문자 리포트
3) 글머리(□/○/-/·/※) 문단 내어쓰기(hanging indent) 자동 적용
4) 줄 단위 자간·장평 맞춤 — 어절 중간 줄바꿈 제거 + 자간을 조여 줄 벌어짐 제거
사용법: python hwpx_polish.py input.hwpx output.hwpx [--no-indent]
"""
import sys, re, zipfile, shutil, tempfile, os
import xml.etree.ElementTree as ET

# 한글 윈도우 콘솔(cp949)에서 —, ※ 등이 UnicodeEncodeError를 내지 않게 한다
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

CIRCLED = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮'
BANNED = '◆■●▶▷☞'
# 수준별 (left, intent) HWPUNIT — 통과본 실측 기반 기본값 (14pt 기준)
LEVELS = {1: (2615, -2615), 2: (5230, -2615), 3: (7300, -2070)}

def polish_section_symbols(xml):
    def para_sub(m):
        p = m.group(0)
        if '▲' not in p:
            return p
        idx = [0]
        def t_sub(tm):
            body = tm.group(2)
            out = []
            for ch in body:
                if ch == '▲':
                    out.append(CIRCLED[idx[0]] if idx[0] < len(CIRCLED) else '·')
                    idx[0] += 1
                else:
                    out.append(ch)
            return tm.group(1) + ''.join(out) + tm.group(3)
        return re.sub(r'(<hp:t[^>]*>)([^<]*)(</hp:t>)', t_sub, p)
    return re.sub(r'<hp:p [^>]*>.*?</hp:p>', para_sub, xml, flags=re.S)

def strip_lineseg(xml):
    """프로그램으로 텍스트를 바꾼 문단의 레이아웃 캐시(linesegarray)를 제거해
    HWP가 열 때 줄배치를 재계산하도록 한다. 캐시가 남아 있으면 글자 겹침이 발생."""
    return re.sub(r'<hp:linesegarray>.*?</hp:linesegarray>', '', xml, flags=re.S)

def polish_header_break(xml):
    """어절 줄바꿈 설정. 주의(실증으로 확인된 반전 매핑):
    breakNonLatinWord="BREAK_WORD" = 어절, "KEEP_WORD" = 글자.
    (2026-07 사용자 HWP 왕복 저장 diff로 확정 — 이름과 의미가 반대다)"""
    return re.sub(r'(<hh:breakSetting\b[^>]*breakNonLatinWord=")KEEP_WORD(")',
                  r'\1BREAK_WORD\2', xml)

def apply_hanging_indent(sec_xml, hdr_xml, tol_ratio=0.25, label_indent=False):
    """글머리 문단 내어쓰기 검증·교정 (범용).
    원리: 내어쓰기 시 이어지는 줄 위치 = left + |intent|. 이 값이 문단 접두부
    (선행공백+기호+한 칸)의 실제 폭 W와 일치해야 '기호 뒤 첫 글자 시작점 정렬'이 된다.
    - 각 글머리 문단에 대해 W를 계산(전각 1.0/반각 0.5 x 첫 run 글자크기)
    - 기존 paraPr의 (left+|intent|)가 W와 오차(글자크기 x tol_ratio) 이내면 보존(수작업 존중)
    - 벗어나면 left=0, intent=-W 인 교정 paraPr을 만들어 연결 (선행 공백은 유지)"""
    paraprs = {m.group(1): m.group(0) for m in
               re.finditer(r'<hh:paraPr id="(\d+)".*?</hh:paraPr>', hdr_xml, re.S)}
    char_h = {m.group(1): int(m.group(2)) for m in
              re.finditer(r'<hh:charPr id="(\d+)"[^>]*height="(\d+)"', hdr_xml)}

    def pr_geom(pid):
        body = paraprs.get(pid, '')
        l = re.search(r'<hc:left value="(-?\d+)"', body)
        i = re.search(r'<hc:intent value="(-?\d+)"', body)
        return (int(l.group(1)) if l else 0), (int(i.group(1)) if i else 0)

    max_id = max(int(i) for i in paraprs)
    new_defs, made = [], {}
    BULLETS = '○□◦·※-−–*' + '①②③④⑤⑥⑦⑧⑨⑩⑪⑫'
    HALF = '-−–·*'
    # 계층 수준(고정). 번호항목 `1.` 과 `□` 는 동급인 0수준이고, 그 아래로 한 칸씩 들여쓴다.
    # 문서에 어떤 기호가 쓰였든 같은 기호는 항상 같은 시작점을 갖는다.
    RANK = {'□': 0, '○': 1, '◦': 1, '-': 2, '−': 2, '–': 2, '·': 3}
    ANNOT = '※*'          # 근거·각주 — 바로 위 항목보다 한 칸 더 안쪽

    def bullet_of(text):
        s = text.replace('\u00a0', ' ').replace('\t', '  ').lstrip(' ')
        return s[0] if s and s[0] in BULLETS else None

    def prefix_units(text):
        s = text.replace('\u00a0', ' ').replace('\t', '  ')
        units, i = 0.0, 0
        while i < len(s) and s[i] == ' ':
            units += 0.5; i += 1
        if i >= len(s) or s[i] not in BULLETS:
            return None
        units += 0.5 if s[i] in HALF else 1.0
        i += 1
        if i < len(s) and s[i] == ' ':
            units += 0.5
            i += 1
        # \ub77c\ubca8 \ud504\ub9ac\ud53d\uc2a4 \u2014 `\u25cb (\ub300\uc0c1) 1\ucc28 \uc8fc\uc694 \u2026` \ucc98\ub7fc \uad04\ud638 \ub77c\ubca8\uc774 \ubd99\uc73c\uba74 \uc774\uc5b4\uc9c0\ub294 \uc904\uc744
        # \uae30\ud638 \ub4a4\uac00 \uc544\ub2c8\ub77c \ub77c\ubca8 \ub4a4\uc5d0 \ub9de\ucd98\ub2e4(\uc2e4\ubb34 \ubb38\uc11c\uc758 \ub0b4\uc5b4\uc4f0\uae30 -7572\uac00 \uc774 \uacbd\uc6b0\ub2e4).
        # \ub2e4\ub9cc \uc2e4\ubb34 \ubb38\uc11c\ub3c4 \uc774\uac78 \uc9e7\uc740 \ub77c\ubca8\uc5d0\ub9cc \uace8\ub77c \uc4f0\ubbc0\ub85c \uae30\ubcf8\uac12\uc740 \ub054(--label-indent).
        if label_indent and i < len(s) and s[i] == '(':
            close = s.find(')', i)
            if 0 < close - i <= 6:           # `(\ub300\uc0c1)` \uc815\ub3c4\uc758 \uc9e7\uc740 \ub77c\ubca8\ub9cc
                lab = s[i:close + 1]
                w = sum(1.0 if unicodedata.east_asian_width(c) in ('W', 'F') else 0.5
                        for c in lab)
                if units + w + 0.5 <= 5.5:   # \ubcf8\ubb38 \ud3ed\uc744 \ub108\ubb34 \uc7a1\uc544\uba39\uc9c0 \uc54a\ub294 \uc120\uae4c\uc9c0\ub9cc
                    units += w
                    if close + 1 < len(s) and s[close + 1] == ' ':
                        units += 0.5
        return units

    # --- 계층 들여쓰기 준비 ------------------------------------------------
    # 한 수준 = 본문 글자크기의 반 칸. 본문 크기는 글머리 문단에서 가장 많이 쓰인 크기로
    # 잡는다(※ 는 12pt 라 작으므로 이걸 기준으로 삼으면 계단이 어긋난다).
    heights = []
    for _m in re.finditer(r'<hp:p [^>]*>.*?</hp:p>', sec_xml, re.S):
        _t = ''.join(re.findall(r'<hp:t[^>]*>([^<]*)</hp:t>', _m.group(0)))
        if bullet_of(_t) in (None,) or bullet_of(_t) in ANNOT:
            continue
        _c = re.search(r'charPrIDRef="(\d+)"', _m.group(0))
        heights.append(char_h.get(_c.group(1), 1500) if _c else 1500)
    step = (max(set(heights), key=heights.count) if heights else 1500) / 2.0

    # ※ · * 는 바로 위 항목에 붙는 부연이므로 그 항목보다 한 칸 더 안쪽에 둔다.
    last_level = [0]

    def left_for(b):
        if b in ANNOT:
            lv = last_level[0] + 1
        else:
            lv = RANK.get(b, 0)
            last_level[0] = lv
        return int(round(lv * step))

    stats = {'kept': 0, 'fixed': 0}
    def para_sub(m):
        p = m.group(0)
        ts = re.findall(r'<hp:t[^>]*>([^<]*)</hp:t>', p)
        if not ts:
            return p
        units = prefix_units(''.join(ts))
        if units is None:
            return p
        pid_m = re.search(r'paraPrIDRef="(\d+)"', p)
        cid_m = re.search(r'charPrIDRef="(\d+)"', p)
        if not pid_m:
            return p
        pid = pid_m.group(1)
        h = char_h.get(cid_m.group(1), 1400) if cid_m else 1400
        W = int(round(units * h))
        L = left_for(bullet_of(''.join(ts)) or '')   # 수준별 시작점
        left, intent = pr_geom(pid)
        if (intent < 0 and abs(left - L) <= h * tol_ratio
                and abs(-intent - W) <= h * tol_ratio):
            stats['kept'] += 1
            return p  # 이미 정렬됨(수작업 등) — 보존
        key = (pid, W, L)
        if key not in made:
            nid = made[key] = str(max_id + 1 + len(made))
            src = paraprs[pid]
            clone = re.sub(r'(<hh:paraPr id=")\d+(")', r'\g<1>%s\g<2>' % nid, src, count=1)
            # paraPr 은 <hp:switch> 안에 case/default 두 벌이 들어 있다. 한 벌만 고치면
            # 한글이 나머지 한 벌을 읽어 값을 되돌리므로 반드시 전부 바꾼다.
            clone = re.sub(r'(<hc:left value=")-?\d+(")', r'\g<1>%d\g<2>' % L, clone)
            if '<hc:intent' in clone:
                clone = re.sub(r'(<hc:intent value=")-?\d+(")', r'\g<1>-%d\g<2>' % W, clone)
            new_defs.append(clone)
        newp = re.sub(r'(paraPrIDRef=")\d+(")', r'\g<1>%s\g<2>' % made[key], p, count=1)
        stats['fixed'] += 1
        return newp

    sec_xml = re.sub(r'<hp:p [^>]*>.*?</hp:p>', para_sub, sec_xml, flags=re.S)
    if new_defs:
        hdr_xml = hdr_xml.replace('</hh:paraProperties>',
                                  ''.join(new_defs) + '</hh:paraProperties>')
        m = re.search(r'(<hh:paraProperties itemCnt=")(\d+)(")', hdr_xml)
        if m:
            hdr_xml = hdr_xml[:m.start()] + m.group(1) + str(int(m.group(2)) + len(new_defs)) + m.group(3) + hdr_xml[m.end():]
    return sec_xml, hdr_xml, stats, len(new_defs)


import unicodedata

def _char_w(ch, h, ratio, spacing):
    if ch == '\t':
        ch = ' '
    ea = unicodedata.east_asian_width(ch)
    base = h if ea in ('W', 'F') else h * 0.5
    return base * (ratio / 100.0) + base * (spacing / 100.0)

NARROW = set("iljIftr.,'`()[]!|:;- ")
WIDE = set('mwMW@%&')

def _lat_u(ch):
    if ch in NARROW: return 0.30
    if ch in WIDE: return 0.72
    if ch.isupper(): return 0.62
    return 0.50

def _units(ch):
    c = ' ' if ch == '\t' else ch
    if unicodedata.east_asian_width(c) in ('W', 'F'):
        return 1.0
    return _lat_u(c)

# 자간·장평 허용 범위 (공문서 관례: 자간 0~-9, 장평 90~104)
# 자간 상한을 0 으로 둔 것은 의도적이다. 자간을 벌리면 줄이 성기게 보이는데,
# 이 후처리의 목적이 바로 그 벌어짐을 없애는 것이기 때문이다. 넓혀야 할 때는
# 장평만 쓴다.
SP_MIN, SP_MAX = -9, 0
RATIO_MIN, RATIO_MAX = 90, 104
# 다음 어절을 끌어올리려고 감수할 실효배율 변화량. 자간 하한(-9)까지 허용해
# '늘려서 밀어내기'보다 '조여서 끌어올리기'가 먼저 선택되도록 한다.
PULL_BUDGET = 9.0


def _decompose(e, base_r, base_sp):
    """목표 실효배율 e(= 장평 + 자간)를 (장평, 자간)으로 나눈다.

    폭 모델에서 장평과 자간은 더해지는 값이라 수치상 등가지만, 눈에 보이는 결과는 다르다.
    - 조일 때는 자간을 먼저 쓴다. 글자 모양을 찌그러뜨리지 않고 사이만 좁히기 때문이다.
    - 늘릴 때는 장평을 먼저 쓴다. 자간을 벌리면 줄이 성기게 보인다.
    한쪽 한계에 닿으면 남은 몫을 다른 쪽이 받는다."""
    d = e - (base_r + base_sp)
    if d <= 0:
        sp = max(SP_MIN, base_sp + d)
        r = max(RATIO_MIN, base_r + (d - (sp - base_sp)))
    else:
        r = min(RATIO_MAX, base_r + d)
        sp = min(SP_MAX, base_sp + (d - (r - base_r)))
    return int(round(r)), int(round(sp))


def auto_fit_ratio(sec_xml, hdr_xml, delta=0.018):
    """줄 단위 어절 맞춤 v4 — 자간 우선 + 줄 채움.

    v3.2는 장평만 움직였고, 회랑 안에서 '기준값에 가장 가까운' 후보를 골랐다.
    그 결과 줄 끝에 빈 공간이 남아도 그대로 두었고, 양쪽정렬이 그 빈 칸을
    어절 사이로 밀어 넣어 줄이 성기게 벌어졌다.

    v4는 두 가지를 바꾼다.
    1) 자간을 조여 다음 어절을 끌어올린다 — 회랑을 만족하는 후보 중 가장 멀리 가는
       경계를 고른다(예산 PULL_BUDGET 이내). 줄이 꽉 차므로 벌어짐이 사라진다.
    2) 필요한 변화량을 장평이 아니라 자간으로 먼저 흡수한다(_decompose).

    회랑 조건은 그대로다: [줄 폭 <= cap*(1-delta)] AND [다음 어절 첫 글자까지 >= cap*(1+delta)].
    폭 모델 오차(±delta)가 있어도 실제 렌더링에서 줄바꿈이 어절 경계에 오도록 보장한다.
    영문 비중이 큰 줄은 HWP가 단어 단위로 처리하므로 건드리지 않는다."""
    import html as _h
    charprs = {m.group(1): m.group(0) for m in
               re.finditer(r'<hh:charPr id="(\d+)".*?</hh:charPr>', hdr_xml, re.S)}
    def cp_attrs(cid):
        b = charprs.get(cid, '')
        h = re.search(r'height="(\d+)"', b)
        r = re.search(r'<hh:ratio hangul="(\d+)"', b)
        sp = re.search(r'<hh:spacing hangul="(-?\d+)"', b)
        return (int(h.group(1)) if h else 1400,
                int(r.group(1)) if r else 100,
                int(sp.group(1)) if sp else 0)
    paraprs = {m.group(1): m.group(0) for m in
               re.finditer(r'<hh:paraPr id="(\d+)".*?</hh:paraPr>', hdr_xml, re.S)}
    def pr_geom(pid):
        b = paraprs.get(pid, '')
        l = re.search(r'<hc:left value="(-?\d+)"', b)
        i = re.search(r'<hc:intent value="(-?\d+)"', b)
        return (int(l.group(1)) if l else 0), (int(i.group(1)) if i else 0)

    pw = re.search(r'<hp:pagePr[^>]*width="(\d+)"', sec_xml)
    mg = re.search(r'<hp:margin[^>]*left="(\d+)"[^>]*right="(\d+)"', sec_xml)
    page_w = int(pw.group(1)) if pw else 59528
    ml, mr = (int(mg.group(1)), int(mg.group(2))) if mg else (8504, 8504)
    body_cap = page_w - ml - mr
    cells = []
    for m in re.finditer(r'<hp:tc .*?</hp:tc>', sec_xml, re.S):
        w = re.search(r'<hp:cellSz width="(\d+)"', m.group(0))
        if not w:
            continue
        cm = re.search(r'<hp:cellMargin[^>]*left="(\d+)"[^>]*right="(\d+)"', m.group(0))
        pad = (int(cm.group(1)) + int(cm.group(2))) if cm else 1020
        cells.append((m.start(), m.end(), int(w.group(1)) - pad))
    def cap_for(pos):
        best = None
        for a, b, w in cells:
            if a <= pos < b and (best is None or b - a < best[0]):
                best = (b - a, w)
        return best[1] if best else body_cap

    changed_lines, manual_lines, pulled_lines = [0], [0], [0]
    new_charprs, made_cp = [], {}
    max_cid = [max(int(i) for i in charprs)]
    SEVEN = ['hangul', 'latin', 'hanja', 'japanese', 'other', 'symbol', 'user']

    def _set7(clone, tag, val):
        """<hh:ratio .../> 또는 <hh:spacing .../> 의 7개 속성을 한 값으로 덮어쓴다."""
        return re.sub(
            r'(<hh:%s )hangul="-?\d+" latin="-?\d+" hanja="-?\d+" japanese="-?\d+"'
            r' other="-?\d+" symbol="-?\d+" user="-?\d+"' % tag,
            r'\g<1>' + ' '.join('%s="%d"' % (k, val) for k in SEVEN), clone, count=1)

    def clone_cp(cid, r, sp):
        key = (cid, r, sp)
        if key not in made_cp:
            ncid = made_cp[key] = str(max_cid[0] + 1 + len(made_cp))
            clone = re.sub(r'(<hh:charPr id=")\d+(")', r'\g<1>%s\g<2>' % ncid, charprs[cid], count=1)
            clone = _set7(clone, 'ratio', r)
            clone = _set7(clone, 'spacing', sp)
            new_charprs.append(clone)
        return made_cp[key]

    def para_sub(m):
        p = m.group(0)
        if '<hp:ctrl' in p or '<hp:tbl' in p:
            return p
        run_ms = list(re.finditer(r'<hp:run charPrIDRef="(\d+)"[^>]*>((?:<hp:t[^>]*>[^<]*</hp:t>)*)</hp:run>', p, re.S))
        if not run_ms:
            return p
        head = p[:run_ms[0].start()]
        tail = p[run_ms[-1].end():]
        mid = p[run_ms[0].start():run_ms[-1].end()]
        if re.sub(r'<hp:run charPrIDRef="\d+"[^>]*>(?:<hp:t[^>]*>[^<]*</hp:t>)*</hp:run>', '', mid).strip():
            return p
        chars = []
        for rm in run_ms:
            cid = rm.group(1)
            for t in re.findall(r'<hp:t[^>]*>([^<]*)</hp:t>', rm.group(2)):
                for ch in _h.unescape(t):
                    chars.append([ch, cid, None])
        n = len(chars)
        if n < 15:
            return p
        pid = re.search(r'paraPrIDRef="(\d+)"', p)
        left, intent = pr_geom(pid.group(1)) if pid else (0, 0)
        cont = left + (-intent if intent < 0 else 0)
        cap1 = cap_for(m.start()) - left - (intent if intent > 0 else 0)
        cap2 = cap_for(m.start()) - cont

        # 장평·자간을 모두 변수로 두므로 누적폭은 배율을 뺀 '맨 폭'만 쌓는다.
        # 실제 폭 = 맨 폭 x 실효배율(e = 장평 + 자간) / 100
        BB = [0.0]
        for k in range(n):
            ch, cid, _ = chars[k]
            BB.append(BB[-1] + _units(ch) * cp_attrs(cid)[0])
        def W(a, z, e):  # chars[a:z] 폭 at 실효배율 e
            return (BB[z] - BB[a]) * e / 100.0
        boundaries = [k for k in range(n) if chars[k][0] == ' '] + [n]

        i, cap, touched = 0, cap1, False
        E_MIN, E_MAX = RATIO_MIN + SP_MIN, RATIO_MAX + SP_MAX
        while i < n:
            _h0, base_r, base_sp = cp_attrs(chars[i][1])
            base_e = base_r + base_sp
            # 손대지 않았을 때의 자연 줄 끝
            jj, pos = i, 0.0
            while jj < n and (pos + W(jj, jj + 1, base_e)) <= cap:
                pos += W(jj, jj + 1, base_e); jj += 1
            if jj >= n:
                break  # 마지막 줄은 줄바꿈이 없으므로 손대지 않는다
            seg = [chars[k][0] for k in range(i, jj)]
            lat = sum(1 for c in seg if ord(c) < 0x2E80 and c != ' ')
            if lat / max(1, len(seg)) > 0.45:
                # 영문 위주 줄 — HWP가 단어단위 처리, 건드리지 않고 자연 진행
                nb = jj
                while nb > i and chars[nb-1][0] != ' ' and nb < n:
                    nb -= 1
                i = jj if nb <= i else nb
                while i < n and chars[i][0] == ' ':
                    i += 1
                cap = cap2
                continue
            # 후보 어절 경계 — 자연 끝(jj) 앞뒤를 훑는다. jj 를 넘는 후보는
            # 다음 어절을 이 줄로 끌어올리는 경우이고, 그만큼 자간을 조여야 한다.
            best = None
            for e in [b for b in boundaries if i < b <= jj + 12]:
                eHi = cap * (1 - delta) * 100.0 / max(1e-6, BB[e] - BB[i])
                e2 = e
                while e2 < n and chars[e2][0] == ' ':
                    e2 += 1
                if e2 >= n:
                    eLo = E_MIN  # 마지막 줄이 되는 경우 하한 없음
                else:
                    eLo = cap * (1 + delta) * 100.0 / max(1e-6, BB[e2 + 1] - BB[i])
                lo, hi = max(E_MIN, eLo), min(E_MAX, eHi)
                if lo > hi:
                    continue
                e_sel = min(max(base_e, lo), hi)  # 회랑 안에서 기준에 가장 가까운 값
                dev = abs(e_sel - base_e)
                if e > jj and dev > PULL_BUDGET:
                    continue  # 끌어올리는 대가가 너무 크다 — 자연 줄바꿈에 맡긴다
                # 줄을 많이 채우는 후보가 우선, 같으면 덜 건드리는 쪽
                cand = (-e, dev)
                if best is None or cand < best[0]:
                    best = (cand, e_sel, e)
            if best is None:
                manual_lines[0] += 1
                i = jj
                while i < n and chars[i][0] == ' ':
                    i += 1
                cap = cap2
                continue
            _, e_sel, e = best
            r_new, sp_new = _decompose(e_sel, base_r, base_sp)
            if (r_new, sp_new) != (base_r, base_sp):
                for k in range(i, e):
                    chars[k][2] = (r_new, sp_new)
                changed_lines[0] += 1
                if e > jj:
                    pulled_lines[0] += 1
                touched = True
            i = e
            while i < n and chars[i][0] == ' ':
                i += 1
            cap = cap2
        if not touched:
            return p
        runs_out, cur_key, buf = [], None, []
        def flush():
            if buf:
                cid, rs = cur_key
                use = cid if rs is None else clone_cp(cid, rs[0], rs[1])
                txt = ''.join(buf).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
                runs_out.append('<hp:run charPrIDRef="%s"><hp:t>%s</hp:t></hp:run>' % (use, txt))
        for ch, cid, rs in chars:
            key = (cid, rs)
            if key != cur_key:
                flush()
                cur_key, buf = key, []
            buf.append(ch)
        flush()
        return head + ''.join(runs_out) + tail

    sec_xml = re.sub(r'<hp:p [^>]*>.*?</hp:p>', para_sub, sec_xml, flags=re.S)
    if new_charprs:
        hdr_xml = hdr_xml.replace('</hh:charProperties>',
                                  ''.join(new_charprs) + '</hh:charProperties>')
        mm = re.search(r'(<hh:charProperties itemCnt=")(\d+)(")', hdr_xml)
        if mm:
            hdr_xml = hdr_xml[:mm.start()] + mm.group(1) + str(int(mm.group(2)) + len(new_charprs)) + mm.group(3) + hdr_xml[mm.end():]
    return sec_xml, hdr_xml, changed_lines[0], manual_lines[0], pulled_lines[0]

def main(inp, outp, indent=True, label_indent=False):
    tmp = tempfile.mkdtemp()
    with zipfile.ZipFile(inp) as z:
        z.extractall(tmp)
    report = []
    hdr_path = os.path.join(tmp, 'Contents', 'header.xml')
    hdr = open(hdr_path, encoding='utf-8').read()
    hdr2 = polish_header_break(hdr)
    if hdr2 != hdr:
        report.append('어절 줄바꿈 설정(breakNonLatinWord=BREAK_WORD — 반전 매핑 주의)')
    hdr = hdr2
    for root, _, files in os.walk(os.path.join(tmp, 'Contents')):
        for f in sorted(files):
            if not f.startswith('section') or not f.endswith('.xml'):
                continue
            path = os.path.join(root, f)
            sec = open(path, encoding='utf-8').read()
            n_ls = sec.count('<hp:linesegarray>')
            sec = strip_lineseg(sec)
            if n_ls:
                report.append(f'{f}: 레이아웃 캐시(linesegarray) {n_ls}개 제거 — HWP 재계산 유도')
            sec2 = polish_section_symbols(sec)
            if sec2 != sec:
                report.append(f'{f}: ▲ 치환')
            sec = sec2
            if indent:
                sec, hdr, st, d = apply_hanging_indent(sec, hdr, label_indent=label_indent)
                if st['fixed'] or st['kept']:
                    report.append(f"{f}: 내어쓰기 — 교정 {st['fixed']}개 / 정렬돼있어 보존 {st['kept']}개 (신규 paraPr {d}개)")
            sec, hdr, nfit, nman, npull = auto_fit_ratio(sec, hdr)
            if nfit or nman:
                report.append(f"{f}: 어절 맞춤 — 자간·장평 조정 {nfit}개 줄"
                              f"(그중 다음 어절 끌어올림 {npull}개) / 조정 불가(육안 확인) {nman}개 줄")
            ET.fromstring(sec)
            open(path, 'w', encoding='utf-8').write(sec)
            leftover = [ch for ch in BANNED if ch in sec]
            if leftover:
                report.append(f'경고: {f} 금지문자 잔존 {leftover}')
    ET.fromstring(hdr)
    open(hdr_path, 'w', encoding='utf-8').write(hdr)
    if os.path.exists(outp):
        os.remove(outp)
    with zipfile.ZipFile(outp, 'w', zipfile.ZIP_DEFLATED) as z:
        mt = os.path.join(tmp, 'mimetype')
        if os.path.exists(mt):
            z.write(mt, 'mimetype', compress_type=zipfile.ZIP_STORED)
        for root, _, files in os.walk(tmp):
            for f in files:
                full = os.path.join(root, f)
                rel = os.path.relpath(full, tmp)
                if rel == 'mimetype':
                    continue
                z.write(full, rel)
    shutil.rmtree(tmp)
    print('\n'.join(report) if report else '변경 사항 없음')
    print(f'저장: {outp}')

if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    main(args[0], args[1], indent='--no-indent' not in sys.argv,
         label_indent='--label-indent' in sys.argv)
