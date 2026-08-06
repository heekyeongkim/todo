# 유튜브 채널 데이터 수집 (블링 스타일)

YouTube Data API v3로 채널의 **구독자 수 / 총 조회수**를 매일 받아와서,
전날 스냅샷과 비교해 블링(vling)처럼 **구독자 증가**와 **일일 조회수**를 계산합니다.

## 1. API 키 발급 (무료)

1. [Google Cloud Console](https://console.cloud.google.com)에서 새 프로젝트 생성
2. `API 및 서비스 → 라이브러리`에서 **YouTube Data API v3** 검색 후 "사용 설정"
3. `API 및 서비스 → 사용자 인증 정보 → 사용자 인증 정보 만들기 → API 키`
4. 발급된 키를 환경변수로 등록:

```bash
export YOUTUBE_API_KEY="발급받은 키"
```

무료 쿼터는 하루 10,000 유닛이고, 이 스크립트는 채널 50개당 1유닛 정도만 쓰므로
매일 돌려도 쿼터 걱정은 없습니다.

## 2. 채널 목록 등록

`channels.txt`에 한 줄에 하나씩 적습니다. `@핸들` 또는 `UC...` 채널 ID 모두 가능합니다.

## 3. 실행

```bash
python3 fetch_channels.py
```

- 첫 실행: 오늘 수치만 저장됩니다 (증가량은 `-`로 표시)
- 다음 날부터: 직전 스냅샷과 비교해 구독자 증가 / 일일 조회수가 계산됩니다

결과물:

| 경로 | 내용 |
|---|---|
| `data/snapshots/YYYY-MM-DD.json` | 그날의 원본 수치 (구독자·총조회수) |
| `data/reports/YYYY-MM-DD.csv` | 증가량 포함 리포트 (엑셀에서 바로 열림) |

## 4. 매일 자동 실행 (선택)

macOS/리눅스라면 crontab으로 매일 오전 9시에 자동 수집할 수 있습니다:

```bash
crontab -e
# 아래 한 줄 추가 (경로와 키는 본인 것으로)
0 9 * * * YOUTUBE_API_KEY="발급받은 키" python3 /경로/todo/youtube-data/fetch_channels.py >> /경로/todo/youtube-data/data/cron.log 2>&1
```

## 참고: 블링 지표와의 대응

| 블링 화면 | 이 스크립트 |
|---|---|
| 구독자 수 | `subscriberCount` (API에서 바로 조회) |
| 구독자 급상승 | `subscriberChange` (전일 대비 차이) |
| 일일 조회수 | `dailyViews` (채널 총조회수의 전일 대비 차이) |

주의: 유튜브 API의 구독자 수는 3자리 유효숫자로 반올림되어 내려옵니다
(예: 12,345,678 → 12,300,000). 대형 채널의 소폭 증가는 0으로 보일 수 있는데,
이는 블링을 포함한 모든 외부 서비스가 동일하게 갖는 제약입니다.
