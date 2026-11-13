"""구글 RSS로 트렌드·뉴스·공휴일을 모아 data/trends.json 으로 저장합니다.

- Google Trends 일간 인기 검색어 (한국): https://trends.google.com/trending/rss?geo=KR
- Google News RSS 검색 (뷰티 키워드별)
- Google Calendar '대한민국의 휴일' 공개 캘린더 (ICS)

표준 라이브러리만 사용합니다.  실행:  python scripts/fetch_trends.py
GitHub Actions(.github/workflows/trends.yml)가 매일 자동 실행해 JSON을 갱신합니다.
기사 본문은 저장하지 않고 제목·출처·링크·날짜만 저장합니다.
"""
import json
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

KST = timezone(timedelta(hours=9))
UA = {"User-Agent": "Mozilla/5.0 (portfolio dashboard; RSS reader)"}
OUT = Path(__file__).resolve().parent.parent / "data" / "trends.json"

TRENDS_URL = "https://trends.google.com/trending/rss?geo=KR"
HOLIDAY_ICS = ("https://calendar.google.com/calendar/ical/"
               "ko.south_korea%23holiday%40group.v.calendar.google.com/public/basic.ics")
NEWS_QUERIES = [
    "뷰티 트렌드",
    "메이크업 트렌드",
    "립 컬러 트렌드",
    "퍼스널컬러",
    "화장품 신제품 출시",
    "W컨셉 뷰티",
]
HT = "{https://trends.google.com/trending/rss}"


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def iso(datestr: str) -> str:
    try:
        return parsedate_to_datetime(datestr).astimezone(KST).isoformat(timespec="minutes")
    except Exception:
        return ""


def fetch_trends(limit: int = 20):
    root = ET.fromstring(get(TRENDS_URL))
    out = []
    for it in root.iter("item"):
        news = [{
            "title": (n.findtext(f"{HT}news_item_title") or "").strip(),
            "url": (n.findtext(f"{HT}news_item_url") or "").strip(),
            "source": (n.findtext(f"{HT}news_item_source") or "").strip(),
        } for n in it.findall(f"{HT}news_item")][:2]
        out.append({
            "title": (it.findtext("title") or "").strip(),
            "traffic": (it.findtext(f"{HT}approx_traffic") or "").strip(),
            "date": iso(it.findtext("pubDate") or ""),
            "news": news,
        })
        if len(out) >= limit:
            break
    return out


def fetch_news(query: str, limit: int = 10):
    q = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={q}+when:30d&hl=ko&gl=KR&ceid=KR:ko"
    root = ET.fromstring(get(url))
    out = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        source = (it.findtext("source") or "").strip()
        if source and title.endswith(" - " + source):
            title = title[: -len(" - " + source)]
        out.append({"title": title, "link": (it.findtext("link") or "").strip(),
                    "source": source, "date": iso(it.findtext("pubDate") or "")})
    out.sort(key=lambda x: x["date"], reverse=True)
    return out[:limit]


def fetch_holidays(months_ahead: int = 15):
    text = get(HOLIDAY_ICS).decode("utf-8", "replace")
    text = re.sub(r"\r?\n[ \t]", "", text)  # ICS 줄 접기 해제
    today = datetime.now(KST).date()
    until = today + timedelta(days=31 * months_ahead)
    seen, out = set(), []
    for block in text.split("BEGIN:VEVENT")[1:]:
        m = re.search(r"DTSTART;VALUE=DATE:(\d{8})", block)
        s = re.search(r"SUMMARY:(.+)", block)
        d = re.search(r"DESCRIPTION:(.+)", block)
        if not (m and s):
            continue
        day = datetime.strptime(m.group(1), "%Y%m%d").date()
        if not (today - timedelta(days=7) <= day <= until):
            continue
        name = s.group(1).strip()
        key = (day, name)
        if key in seen:
            continue
        seen.add(key)
        out.append({"date": day.isoformat(), "name": name,
                    "kind": (d.group(1).strip() if d else "")})
    out.sort(key=lambda x: x["date"])
    return out


def main():
    data = {"updated": datetime.now(KST).isoformat(timespec="minutes"),
            "sources": {"trends": TRENDS_URL, "news": "https://news.google.com/rss", "holidays": "Google Calendar 대한민국의 휴일"},
            "trends": [], "news": {}, "holidays": [], "errors": []}
    try:
        data["trends"] = fetch_trends()
    except Exception as e:  # 한 소스가 실패해도 나머지는 저장
        data["errors"].append(f"trends: {e}")
    for q in NEWS_QUERIES:
        try:
            data["news"][q] = fetch_news(q)
        except Exception as e:
            data["errors"].append(f"news[{q}]: {e}")
    try:
        data["holidays"] = fetch_holidays()
    except Exception as e:
        data["errors"].append(f"holidays: {e}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    n = sum(len(v) for v in data["news"].values())
    print(f"saved {OUT} · trends {len(data['trends'])} · news {n} · holidays {len(data['holidays'])} · errors {len(data['errors'])}")
    return 0 if not data["errors"] else 1


if __name__ == "__main__":
    sys.exit(main())
