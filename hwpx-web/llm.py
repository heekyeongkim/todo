# -*- coding: utf-8 -*-
"""원고 생성 LLM 호출부 (Google Gemini — 무료 등급 API 키 사용).

LLM은 최종 HWPX를 만들지 않는다 — hwp-writing-assistant 스킬의 입력 마크업
형식으로 된 md 원고만 생성하고, 파일은 pipeline.py(스킬 파이프라인)가 만든다.

API 키: https://aistudio.google.com/apikey 에서 무료 발급 →
        환경변수 GEMINI_API_KEY 로 설정 (google-genai SDK가 자동으로 읽는다).
"""
import os
import re

from google import genai
from google.genai import types

# 무료 등급에서 쓸 수 있는 기본 모델. HWPX_LLM_MODEL 환경변수로 변경 가능.
MODEL = os.environ.get("HWPX_LLM_MODEL", "gemini-2.5-flash")

# hwp-writing-assistant/SKILL.md 의 규칙을 원고 생성 프롬프트로 옮긴 것.
SYSTEM_PROMPT = """\
너는 한국 행정기관의 문서 작성 담당자다. 사용자가 준 제목·핵심 내용·참고 자료를
행안부 「AI 시대 행정문서 작성 가이드라인」 서식의 원고(마크다운)로 재구성한다.

# 출력 형식 (입력 마크업 — 이 형식만 출력한다)
- `# 제목` — 문서 제목, 반드시 한 줄. 계획서는 `…계획(안)`.
- `## 요약` — 첫 절은 반드시 요약. 본문은 `> `로 시작하는 줄 두 줄 이내, 기호 없이.
- 이후 내용에 맞는 번호절 `1.` `2.` `3.` — 4단 고정 구조가 아니다. 배경·추진 계획·
  향후 일정 등 절의 구성과 개수는 입력 내용에 따라 네가 정한다.
- 계층 기호: `1.`=`□`(동급) → `○` → `-` → `·`. 근거·출처는 `※`, 각주는 `*`,
  별지는 `[참고N]`. 줄 앞에 공백을 넣어 계층을 흉내내지 말 것(계층은 후처리가
  좌여백으로 넣는다). 한 줄이 곧 한 문단이다.
- 표는 연속된 `| a | b |` 줄로 쓴다. 셀 병합·표 안의 표·대각선 금지 — 병합처럼
  보여야 하면 같은 값을 반복해 채운다. 조직도·체계도·일정표는 표 대신 서술식으로.

# 문체
- 개조식 명사형 종결, 마침표 없음: `…방안을 마련함.` ✗ → `…방안을 마련` ○
- 라벨 프리픽스를 기본으로 쓴다: `○ (방법) …`, `○ (대상) …`, `○ (기간) …`
- 날짜는 `'26.6.26. ~ 7.12.` 형식.
- 강조는 볼드가 아니라 「」(정책·문서명)과 '따옴표'(개념·인용).
- 기사체는 행정문서 용어로 정리한다: 개미→개인투자자, 투톱→상위 2개 종목.
  직접 인용은 따옴표로 보존한다.
- 금지 기호: ▲ ◆ ■ ● ▶ ▷ ☞

# 내용 원칙
- 없는 내용을 만들지 않는다. 원문에 없으면 `- … 확인 필요`로 남긴다.
- 숫자·고유명사·날짜는 입력 원문 그대로 옮긴다. 표 안의 합계·비율은 반드시
  실제 계산과 일치해야 한다.
- 원문 날짜에 연·월이 없어 보완했으면, 원고 마지막 줄에
  `<!-- 가정: … -->` 형식의 HTML 주석 한 줄로 가정한 사실을 밝힌다.

# 출력 규칙
- 원고 마크다운만 출력한다. 코드펜스(```)나 설명 문장을 붙이지 않는다.
"""

FIX_PROMPT = """\
아래 원고가 숫자 자동 검증에서 오류(❌)를 냈다. 검증 리포트를 보고 원고의 숫자
정합성 오류만 고쳐서 전체 원고를 다시 출력하라. 입력 원문에 있던 숫자는 바꾸지
말고, 합계·비율 등 계산되는 값을 원문 기준으로 바로잡는 것을 우선한다.
원고 마크다운만 출력한다.

[검증 리포트]
{report}

[원고]
{manuscript}
"""

ADJUST_INSTRUCTIONS = {
    "concise": "아래 원고를 더 간결하게 다듬어 전체 원고를 다시 출력하라. "
               "핵심 항목만 남기고 세부항목(-, ·)을 줄이되, 숫자·날짜·고유명사와 "
               "절 구조 규칙은 그대로 유지한다. 원고 마크다운만 출력한다.",
    "detailed": "아래 원고를 더 상세하게 보강해 전체 원고를 다시 출력하라. "
                "입력 내용 범위 안에서 세부항목(-, ·)을 풀어 쓰되, 없는 사실을 "
                "만들지 않는다(부족하면 `- … 확인 필요`로 남긴다). "
                "원고 마크다운만 출력한다.",
}


def _client():
    # GEMINI_API_KEY(또는 GOOGLE_API_KEY) 환경변수를 자동으로 읽는다
    return genai.Client()


def _strip_fences(text):
    text = text.strip()
    m = re.match(r"^```[a-zA-Z]*\n(.*)\n```$", text, re.S)
    return m.group(1).strip() if m else text


def _call(user_text):
    response = _client().models.generate_content(
        model=MODEL,
        contents=user_text,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            max_output_tokens=8192,
        ),
    )
    text = response.text
    if not text or not text.strip():
        raise RuntimeError("LLM 응답이 비어 있습니다. 잠시 후 다시 시도해 주세요.")
    return _strip_fences(text)


def generate_manuscript(title, content, attachment_text=None):
    user = f"[문서 제목]\n{title}\n\n[핵심 내용]\n{content}"
    if attachment_text:
        user += f"\n\n[참고 파일 내용 — 원고 재료로 활용]\n{attachment_text[:30000]}"
    return _call(user)


def fix_manuscript(manuscript, check_report):
    return _call(FIX_PROMPT.format(report=check_report, manuscript=manuscript))


def adjust_manuscript(manuscript, mode):
    instruction = ADJUST_INSTRUCTIONS[mode]
    return _call(f"{instruction}\n\n[원고]\n{manuscript}")
