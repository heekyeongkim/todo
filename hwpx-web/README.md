# 한글 보고서 초안 생성기 (HWPX)

핵심 내용을 입력하면 Claude가 행정문서 원고(마크다운)를 작성하고,
레포 루트의 `hwp-writing-assistant/` 스킬 파이프라인이 한글(HWP)에서
바로 열리는 HWPX 파일로 조판한다.

## 구조

```
사용자 입력 (제목·핵심 내용·첨부 TXT/PDF/DOCX)
   ↓ llm.py          — Claude가 스킬 입력 마크업 원고(md)만 생성 (HWPX는 만들지 않음)
   ↓ core.py         — check_numbers 검증 → 오류 시 LLM 되먹임 재수정(최대 2회)
   ↓ pipeline.py     — build_hwpx → hwpx_polish (스킬 스크립트를 수정 없이 호출)
   ↓                    ※ hwpx_polish 생략 금지(글자 겹침), hwpx_shifttab은 서버에서 미호출
결과: HWPX + 검증/조판 리포트 + 원고 미리보기
```

- 숫자 검증이 2회 재시도 후에도 실패하면 생성을 막지 않고 **경고와 함께 강행**하며,
  결과 화면에 검증 리포트를 그대로 표시한다.
- 스킬 폴더(`hwp-writing-assistant/`)의 스크립트는 수정하지 않는다.
  `template-field.hwpx` 는 build 단계가 스킬 폴더에서 자동으로 찾는다.

## 실행

```bash
pip install -r hwpx-web/requirements.txt
export ANTHROPIC_API_KEY=...      # 또는 `ant auth login` 프로필
python hwpx-web/server.py         # http://localhost:8765
```

모델은 기본 `claude-opus-5` 이며 `HWPX_LLM_MODEL` 환경변수로 바꿀 수 있다.

## 검증 (API 키 불필요)

```bash
python hwpx-web/test_flow.py
```

스텁 LLM으로 ① 스킬 sample.md 엔드투엔드(좌여백 750/1500/2250·음수 내어쓰기),
② 숫자 오류 → 자동 수정 → 재검증, ③ 2회 실패 시 경고 강행,
④ 가정 주석 추출·파일명 치환, 그리고 hwpx zip의 `mimetype` 무압축·최상단을 검사한다.
