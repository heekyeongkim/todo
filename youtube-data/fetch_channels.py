#!/usr/bin/env python3
"""유튜브 채널 데이터 수집 스크립트 (블링 스타일 지표 만들기)

YouTube Data API v3로 채널의 구독자 수 / 총 조회수를 받아와서
날짜별 스냅샷(data/snapshots/YYYY-MM-DD.json)으로 저장하고,
직전 스냅샷과 비교해 "구독자 증가" / "일일 조회수" 지표를 계산한다.

사용법:
    export YOUTUBE_API_KEY="발급받은 API 키"
    python3 fetch_channels.py

수집 대상 채널은 channels.txt에 한 줄에 하나씩 적는다.
(@핸들 또는 UC로 시작하는 채널 ID 모두 가능)
"""

import csv
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

API_BASE = "https://www.googleapis.com/youtube/v3/channels"
BASE_DIR = Path(__file__).resolve().parent
CHANNELS_FILE = BASE_DIR / "channels.txt"
SNAPSHOT_DIR = BASE_DIR / "data" / "snapshots"
REPORT_DIR = BASE_DIR / "data" / "reports"


def api_get(params):
    """channels.list API 호출 후 JSON 반환. 오류 시 메시지를 보여주고 종료."""
    url = API_BASE + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=30) as res:
            return json.load(res)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            reason = json.loads(body)["error"]["message"]
        except (ValueError, KeyError):
            reason = body[:300]
        sys.exit(f"[오류] API 호출 실패 (HTTP {e.code}): {reason}")


def read_channel_list():
    if not CHANNELS_FILE.exists():
        sys.exit(f"[오류] {CHANNELS_FILE} 파일이 없습니다. 채널 목록을 먼저 만들어 주세요.")
    entries = []
    for line in CHANNELS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            entries.append(line)
    if not entries:
        sys.exit(f"[오류] {CHANNELS_FILE}에 채널이 하나도 없습니다.")
    return entries


def resolve_handle(handle, key):
    """@핸들 → 채널 ID(UC...) 변환"""
    data = api_get({"part": "id", "forHandle": handle, "key": key})
    items = data.get("items", [])
    if not items:
        print(f"[경고] 핸들을 찾을 수 없어 건너뜀: {handle}")
        return None
    return items[0]["id"]


def fetch_stats(channel_ids, key):
    """채널 ID 목록의 이름/구독자/조회수 조회 (한 번에 최대 50개)"""
    result = {}
    for i in range(0, len(channel_ids), 50):
        batch = channel_ids[i : i + 50]
        data = api_get({
            "part": "snippet,statistics",
            "id": ",".join(batch),
            "maxResults": 50,
            "key": key,
        })
        for item in data.get("items", []):
            stats = item["statistics"]
            result[item["id"]] = {
                "title": item["snippet"]["title"],
                "subscriberCount": int(stats.get("subscriberCount", 0)),
                "viewCount": int(stats.get("viewCount", 0)),
                "videoCount": int(stats.get("videoCount", 0)),
            }
    return result


def load_previous_snapshot(today_name):
    """오늘 것을 제외한 가장 최근 스냅샷을 불러온다."""
    if not SNAPSHOT_DIR.exists():
        return None, None
    files = sorted(p for p in SNAPSHOT_DIR.glob("*.json") if p.stem != today_name)
    if not files:
        return None, None
    latest = files[-1]
    return latest.stem, json.loads(latest.read_text(encoding="utf-8"))


def fmt(n):
    return f"{n:,}"


def main():
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        sys.exit(
            "[오류] 환경변수 YOUTUBE_API_KEY가 없습니다.\n"
            "  1) https://console.cloud.google.com 에서 프로젝트 생성\n"
            "  2) 'YouTube Data API v3' 사용 설정 후 API 키 발급\n"
            "  3) export YOUTUBE_API_KEY=\"발급받은 키\" 실행 후 다시 시도"
        )

    entries = read_channel_list()

    # @핸들은 채널 ID로 변환
    channel_ids = []
    for entry in entries:
        if entry.startswith("@"):
            cid = resolve_handle(entry, key)
            if cid:
                channel_ids.append(cid)
        else:
            channel_ids.append(entry)

    print(f"채널 {len(channel_ids)}개 조회 중...")
    stats = fetch_stats(channel_ids, key)
    if not stats:
        sys.exit("[오류] 조회된 채널이 없습니다. channels.txt의 ID/핸들을 확인해 주세요.")

    # 오늘 스냅샷 저장
    today = date.today().isoformat()
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    snapshot_path = SNAPSHOT_DIR / f"{today}.json"
    snapshot_path.write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"스냅샷 저장: {snapshot_path.relative_to(BASE_DIR)}")

    # 직전 스냅샷과 비교해 증가량 계산
    prev_date, prev = load_previous_snapshot(today)
    rows = []
    for cid, cur in stats.items():
        old = (prev or {}).get(cid)
        rows.append({
            "channelId": cid,
            "title": cur["title"],
            "subscriberCount": cur["subscriberCount"],
            "subscriberChange": cur["subscriberCount"] - old["subscriberCount"] if old else None,
            "viewCount": cur["viewCount"],
            "dailyViews": cur["viewCount"] - old["viewCount"] if old else None,
        })

    # 블링 기본 정렬처럼 일일 조회수 내림차순 (첫 실행이면 구독자 수 기준)
    have_diff = prev is not None
    rows.sort(
        key=lambda r: (r["dailyViews"] if have_diff and r["dailyViews"] is not None else r["subscriberCount"]),
        reverse=True,
    )

    # 콘솔 출력
    print()
    if have_diff:
        print(f"=== {prev_date} → {today} 변화량 ===")
    else:
        print("=== 첫 수집 (내일부터 증가량이 계산됩니다) ===")
    header = f"{'채널':<30} {'구독자':>15} {'구독자 증가':>12} {'일일 조회수':>15}"
    print(header)
    print("-" * len(header))
    for r in rows:
        sub_chg = fmt(r["subscriberChange"]) if r["subscriberChange"] is not None else "-"
        daily = fmt(r["dailyViews"]) if r["dailyViews"] is not None else "-"
        print(f"{r['title']:<30} {fmt(r['subscriberCount']):>15} {sub_chg:>12} {daily:>15}")

    # CSV 리포트 저장
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / f"{today}.csv"
    with report_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nCSV 리포트 저장: {report_path.relative_to(BASE_DIR)}")


if __name__ == "__main__":
    main()
