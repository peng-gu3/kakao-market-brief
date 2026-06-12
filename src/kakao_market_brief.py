import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from html import escape
from urllib.parse import urlencode, urlparse
from zoneinfo import ZoneInfo

import feedparser
import requests
import yfinance as yf
from dotenv import load_dotenv

try:
    from pykrx import stock
except ImportError:
    stock = None

KST = ZoneInfo("Asia/Seoul")
UTC = ZoneInfo("UTC")
KAKAO_TOKEN_URL = "https://kauth.kakao.com/oauth/token"
KAKAO_SEND_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
DEFAULT_REPORT_PAGE_URL = "https://peng-gu3.github.io/kakao-market-brief/"
REPORT_OUTPUT_PATH = os.getenv("REPORT_OUTPUT_PATH", "docs/index.html")

KOREA_WATCHLIST = {
    "005930.KS": "삼성전자", "000660.KS": "SK하이닉스", "005380.KS": "현대차", "000270.KS": "기아",
    "012330.KS": "현대모비스", "035420.KS": "NAVER", "035720.KS": "카카오", "068270.KS": "셀트리온",
    "207940.KS": "삼성바이오로직스", "051910.KS": "LG화학", "373220.KS": "LG에너지솔루션", "006400.KS": "삼성SDI",
    "005490.KS": "POSCO홀딩스", "003670.KS": "포스코퓨처엠", "105560.KS": "KB금융", "055550.KS": "신한지주",
    "086790.KS": "하나금융지주", "032830.KS": "삼성생명", "028260.KS": "삼성물산", "009540.KS": "HD한국조선해양",
    "329180.KS": "HD현대중공업", "012450.KS": "한화에어로스페이스", "042660.KS": "한화오션", "034020.KS": "두산에너빌리티",
}

KOREA_BUCKETS = [
    {"005930.KS", "000660.KS", "035420.KS", "035720.KS", "068270.KS", "207940.KS"},
    {"005380.KS", "000270.KS", "012330.KS", "005490.KS", "003670.KS", "028260.KS"},
    {"051910.KS", "373220.KS", "006400.KS", "105560.KS", "055550.KS", "086790.KS", "032830.KS"},
    {"009540.KS", "329180.KS", "012450.KS", "042660.KS", "034020.KS"},
]

TICKER_SECTOR = {
    "005930.KS": "반도체/AI", "000660.KS": "반도체/AI",
    "035420.KS": "플랫폼/바이오", "035720.KS": "플랫폼/바이오", "068270.KS": "플랫폼/바이오", "207940.KS": "플랫폼/바이오",
    "005380.KS": "자동차", "000270.KS": "자동차", "012330.KS": "자동차",
    "051910.KS": "2차전지/소재", "373220.KS": "2차전지/소재", "006400.KS": "2차전지/소재", "005490.KS": "2차전지/소재", "003670.KS": "2차전지/소재",
    "105560.KS": "금융", "055550.KS": "금융", "086790.KS": "금융", "032830.KS": "금융",
    "009540.KS": "조선/방산/전력", "329180.KS": "조선/방산/전력", "012450.KS": "조선/방산/전력", "042660.KS": "조선/방산/전력", "034020.KS": "조선/방산/전력",
}

SECTOR_KEYWORDS = {
    "반도체/AI": ["반도체", "하이닉스", "삼성전자", "chip", "semiconductor", "nvidia", "ai"],
    "자동차": ["자동차", "현대차", "기아", "auto", "ev"],
    "2차전지/소재": ["배터리", "2차전지", "전기차", "battery", "리튬", "소재"],
    "금융": ["은행", "금융", "금리", "보험", "주주환원"],
    "조선/방산/전력": ["조선", "방산", "방위", "전력", "원전", "shipbuilding", "defense"],
    "플랫폼/바이오": ["네이버", "카카오", "플랫폼", "바이오", "제약", "셀트리온"],
}

MARKET_TICKERS = {
    "^GSPC": "S&P 500", "^IXIC": "NASDAQ", "^DJI": "Dow", "KRW=X": "USD/KRW",
    "^TNX": "미국 10년물 금리", "CL=F": "WTI 유가", "BTC-USD": "비트코인",
}

NEWS_QUERIES = {
    "국내 주요뉴스": "한국 경제 증시 산업 when:1d",
    "미국 주식뉴스": "US stock market earnings Fed sector when:1d",
    "세계 주요뉴스": "global economy geopolitics markets oil rates when:1d",
}


@dataclass
class Indicator:
    name: str
    value: float
    change: float
    as_of: str
    unit: str = ""


@dataclass
class NewsItem:
    section: str
    title: str
    link: str
    published_at: datetime | None


@dataclass
class Pick:
    ticker: str
    name: str
    sector: str
    close: float
    as_of: str
    one_day: float
    five_day: float
    twenty_day: float
    score: float
    reason: str


def now_kst() -> datetime:
    return datetime.now(KST)


def report_page_url() -> str:
    value = os.getenv("REPORT_PAGE_URL", DEFAULT_REPORT_PAGE_URL).strip() or DEFAULT_REPORT_PAGE_URL
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host in {"localhost", "127.0.0.1", "0.0.0.0"}:
        return DEFAULT_REPORT_PAGE_URL
    if host.endswith(".local"):
        return DEFAULT_REPORT_PAGE_URL
    return value if value.endswith("/") else value + "/"


def fmt_dt(dt: datetime | None) -> str:
    if dt is None:
        return "시간 미확인"
    return dt.astimezone(KST).strftime("%m-%d %H:%M")


def fmt_change(value: float) -> str:
    if value > 0:
        return f"▲ {value:.2f}%"
    if value < 0:
        return f"▼ {abs(value):.2f}%"
    return "━ 0.00%"


def latest_label(index) -> str:
    if len(index) == 0:
        return "기준 미확인"
    latest = index[-1]
    try:
        if getattr(latest, "tzinfo", None) is None:
            latest = latest.tz_localize(UTC)
        return latest.tz_convert(KST).strftime("%m-%d %H:%M")
    except Exception:
        try:
            return latest.strftime("%Y-%m-%d")
        except Exception:
            return str(latest)


def pct_change(series, days: int) -> float:
    if len(series) <= days:
        return 0.0
    start = float(series.iloc[-days - 1])
    end = float(series.iloc[-1])
    return 0.0 if start == 0 else (end / start - 1) * 100


def fetch_weather() -> str:
    city = os.getenv("REPORT_CITY", "Busan")
    lat = os.getenv("REPORT_LAT", "35.1796")
    lon = os.getenv("REPORT_LON", "129.0756")
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,precipitation,wind_speed_10m",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "timezone": "Asia/Seoul",
        "forecast_days": 1,
    }
    url = "https://api.open-meteo.com/v1/forecast"
    for timeout in (8, 12):
        try:
            response = requests.get(url, params=params, timeout=timeout)
            response.raise_for_status()
            data = response.json()
            current = data["current"]
            daily = data["daily"]
            return (
                f"{city} 현재 {current['temperature_2m']}도, 강수 {current['precipitation']}mm, "
                f"풍속 {current['wind_speed_10m']}km/h. "
                f"오늘 {daily['temperature_2m_min'][0]}~{daily['temperature_2m_max'][0]}도, "
                f"강수확률 {daily['precipitation_probability_max'][0]}%."
            )
        except requests.RequestException:
            continue
        except (KeyError, IndexError, TypeError, ValueError):
            break
    return f"{city} 날씨는 외부 날씨 API 응답 지연으로 이번 브리핑에서는 생략했습니다."


def fetch_krx_indices() -> list[Indicator]:
    if stock is None:
        return []
    today = now_kst().date()
    start = (today - timedelta(days=14)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")
    result = []
    for code, name in {"1001": "KOSPI", "2001": "KOSDAQ"}.items():
        try:
            frame = stock.get_index_ohlcv_by_date(start, end, code)
            close = frame["종가"].dropna()
            if len(close) >= 2:
                result.append(Indicator(name, float(close.iloc[-1]), pct_change(close, 1), close.index[-1].strftime("%Y-%m-%d")))
        except Exception:
            continue
    return result


def fetch_market_indicators() -> list[Indicator]:
    result = fetch_krx_indices()
    if not result:
        for ticker, name in {"^KS11": "KOSPI", "^KQ11": "KOSDAQ"}.items():
            try:
                history = yf.Ticker(ticker).history(period="7d", interval="1d", auto_adjust=False)
                close = history["Close"].dropna()
                if len(close) >= 2:
                    result.append(Indicator(name, float(close.iloc[-1]), pct_change(close, 1), latest_label(close.index)))
            except Exception:
                continue
    for ticker, name in MARKET_TICKERS.items():
        try:
            interval = "1h" if ticker in {"KRW=X", "CL=F", "BTC-USD"} else "1d"
            period = "5d" if interval == "1h" else "7d"
            history = yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=False)
            close = history["Close"].dropna()
            if len(close) < 2:
                continue
            unit = "원" if ticker == "KRW=X" else "%p" if ticker == "^TNX" else "$" if ticker in {"CL=F", "BTC-USD"} else ""
            result.append(Indicator(name, float(close.iloc[-1]), pct_change(close, 1), latest_label(close.index), unit))
        except Exception:
            continue
    return result


def news_url(query: str) -> str:
    params = {"q": query, "hl": "ko", "gl": "KR", "ceid": "KR:ko", "_": str(int(time.time()))}
    return "https://news.google.com/rss/search?" + urlencode(params)


def parse_published(entry) -> datetime | None:
    parsed = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    return None if not parsed else datetime(*parsed[:6], tzinfo=UTC).astimezone(KST)


def fetch_news() -> list[NewsItem]:
    items = []
    cutoff = now_kst() - timedelta(hours=48)
    for section, query in NEWS_QUERIES.items():
        try:
            feed = feedparser.parse(news_url(query))
        except Exception:
            continue
        for entry in feed.entries[:8]:
            published = parse_published(entry)
            if published and published < cutoff:
                continue
            items.append(NewsItem(section, entry.title, entry.link, published))
    items.sort(key=lambda item: item.published_at or datetime.min.replace(tzinfo=KST), reverse=True)
    return items


def sector_scores(news: list[NewsItem]) -> dict[str, int]:
    titles = " ".join(item.title for item in news).lower()
    return {sector: sum(1 for keyword in keywords if keyword.lower() in titles) for sector, keywords in SECTOR_KEYWORDS.items()}


def score_watchlist(news: list[NewsItem]) -> list[Pick]:
    scores = sector_scores(news)
    bucket = KOREA_BUCKETS[now_kst().date().toordinal() % len(KOREA_BUCKETS)]
    picks = []
    for ticker, name in KOREA_WATCHLIST.items():
        try:
            history = yf.Ticker(ticker).history(period="3mo", interval="1d", auto_adjust=True)
            close = history["Close"].dropna()
            volume = history["Volume"].dropna() if "Volume" in history else []
            if len(close) < 25:
                continue
            one = pct_change(close, 1)
            five = pct_change(close, 5)
            twenty = pct_change(close, 20)
            vol_score = 0.0
            if len(volume) >= 21 and float(volume.iloc[-21:-1].mean()) > 0:
                vol_score = min((float(volume.iloc[-1]) / float(volume.iloc[-21:-1].mean()) - 1) * 3, 12)
            sector = TICKER_SECTOR.get(ticker, "기타")
            news_score = min(scores.get(sector, 0) * 3, 12)
            rotation = 6 if ticker in bucket else 0
            penalty = (8 if one > 5 or twenty > 25 else 0) + (6 if five < -8 else 0)
            score = five * 0.35 + twenty * 0.25 + one * 0.15 + vol_score + news_score + rotation - penalty
            reason = f"{sector} · {'오늘 순환 후보군' if ticker in bucket else '보조 후보군'} · 뉴스 {news_score:.0f} · 거래량 {vol_score:.1f}"
            picks.append(Pick(ticker, name, sector, float(close.iloc[-1]), latest_label(close.index), one, five, twenty, score, reason))
        except Exception:
            continue
    picks.sort(key=lambda item: item.score, reverse=True)
    selected, used = [], set()
    for pick in picks:
        if pick.sector in used and len(selected) < 2:
            continue
        selected.append(pick)
        used.add(pick.sector)
        if len(selected) == 2:
            return selected
    return picks[:2]


def market_temperature(indicators: list[Indicator]) -> tuple[str, str]:
    score = 50
    reasons = []
    by_name = {item.name: item for item in indicators}
    if by_name.get("KOSPI") and by_name["KOSPI"].change > 0:
        score += 8
        reasons.append("KOSPI 상승")
    if by_name.get("NASDAQ") and by_name["NASDAQ"].change < 0:
        score -= 8
        reasons.append("NASDAQ 약세")
    if by_name.get("USD/KRW") and by_name["USD/KRW"].change > 0.4:
        score -= 8
        reasons.append("환율 상승")
    if by_name.get("미국 10년물 금리") and by_name["미국 10년물 금리"].change > 1:
        score -= 7
        reasons.append("미 금리 상승")
    score = max(0, min(100, score))
    label = "위험선호" if score >= 65 else "중립" if score >= 45 else "방어적"
    return f"{score}/100 · {label}", ", ".join(reasons) or "뚜렷한 방향성은 제한적"


def pick_commentary(pick: Pick) -> str:
    if pick.twenty_day > 8 and pick.five_day > 0:
        return "중기 추세와 단기 흐름이 같이 살아있는 후보"
    if pick.twenty_day > 8:
        return "중기 추세는 양호하지만 최근 눌림 확인 필요"
    if pick.five_day > 3:
        return "단기 수급이 강한 후보"
    return "상대적으로 방어적인 흐름의 후보"


def render_kakao_summary(weather: str, indicators: list[Indicator], picks: list[Pick], news: list[NewsItem]) -> str:
    generated = now_kst().strftime("%Y-%m-%d %H:%M")
    temp, reason = market_temperature(indicators)
    main_indicators = [item for item in indicators if item.name in {"KOSPI", "KOSDAQ", "NASDAQ", "USD/KRW"}][:4]
    lines = [
        f"[{generated} KST] 아침 브리핑",
        "",
        f"시장 온도: {temp}",
        f"근거: {reason}",
        "",
        "주요 지표",
    ]
    for item in main_indicators:
        value = f"${item.value:,.0f}" if item.name == "비트코인" else f"{item.value:,.2f}{item.unit}"
        lines.append(f"- {item.name}: {value} · {fmt_change(item.change)}")
    lines.extend(["", "국내 관심후보"])
    for pick in picks:
        lines.append(f"- {pick.name}: 1일 {fmt_change(pick.one_day)}, 5일 {fmt_change(pick.five_day)}")
    lines.extend([
        "",
        f"날씨: {weather}",
        "",
        "상세 뉴스 링크, 지표표, 선정 근거는 아래 버튼의 전체 페이지에서 확인하실 수 있습니다.",
        "주의: 자동화된 관심후보이며 매수/매도 지시가 아닙니다.",
    ])
    return "\n".join(lines)


def render_html(weather: str, indicators: list[Indicator], news: list[NewsItem], picks: list[Pick], summary: str) -> str:
    generated = now_kst().strftime("%Y-%m-%d %H:%M KST")
    temp, reason = market_temperature(indicators)
    indicator_cards = "".join(
        f"<article><h3>{escape(item.name)}</h3><p class='value'>{escape(str(round(item.value, 2)))}{escape(item.unit)}</p><p>{escape(fmt_change(item.change))}</p><small>기준 {escape(item.as_of)}</small></article>"
        for item in indicators
    )
    pick_cards = "".join(
        f"<article><h3>{escape(pick.name)} <small>{escape(pick.ticker)}</small></h3><p class='value'>{pick.close:,.2f}</p><small>기준 {escape(pick.as_of)}</small><dl><dt>흐름</dt><dd>1일 {escape(fmt_change(pick.one_day))} · 5일 {escape(fmt_change(pick.five_day))} · 20일 {escape(fmt_change(pick.twenty_day))}</dd><dt>선정</dt><dd>{escape(pick.reason)}</dd><dt>근거</dt><dd>{escape(pick_commentary(pick))}</dd></dl></article>"
        for pick in picks
    )
    news_items = "".join(
        f"<li><a href='{escape(item.link)}' target='_blank' rel='noopener'>{escape(item.title)}</a><span>{escape(item.section)} · {escape(fmt_dt(item.published_at))}</span></li>"
        for item in news[:18]
    )
    return f"""<!doctype html>
<html lang='ko'>
<head>
<meta charset='utf-8'>
<meta name='viewport' content='width=device-width, initial-scale=1'>
<title>아침 브리핑</title>
<style>
:root {{ --bg:#f5f6f8; --card:#fff; --ink:#111827; --muted:#667085; --line:#d8dee8; --blue:#1f6feb; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink); font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; line-height:1.6; }}
header {{ background:#111827; color:white; padding:28px 18px; }}
main {{ max-width:920px; margin:0 auto; padding:18px; }}
h1 {{ margin:0 0 6px; font-size:28px; }}
h2 {{ margin:30px 0 12px; font-size:20px; }}
h3 {{ margin:0 0 8px; font-size:17px; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:12px; }}
article,.summary {{ background:var(--card); border:1px solid var(--line); border-radius:8px; padding:15px; }}
.value {{ font-size:21px; font-weight:800; margin:4px 0; }}
small,.muted,span {{ color:var(--muted); }}
dl {{ margin:10px 0 0; }} dt {{ font-weight:700; margin-top:8px; }} dd {{ margin:2px 0 0; }}
ul.news {{ list-style:none; padding:0; margin:0; display:grid; gap:10px; }}
ul.news li {{ background:white; border:1px solid var(--line); border-radius:8px; padding:13px; }}
ul.news a {{ display:block; color:var(--blue); text-decoration:none; font-weight:700; }}
ul.news span {{ display:block; margin-top:5px; font-size:13px; }}
pre {{ white-space:pre-wrap; font:15px/1.55 ui-monospace,Menlo,Consolas,monospace; margin:0; }}
</style>
</head>
<body>
<header><main><h1>아침 브리핑</h1><p class='muted'>{escape(generated)} · 시장 온도 {escape(temp)} · {escape(reason)}</p></main></header>
<main>
<section class='summary'><h2>카톡 요약</h2><pre>{escape(summary)}</pre></section>
<section><h2>날씨</h2><article>{escape(weather)}</article></section>
<section><h2>지수 · 환율 · 금리</h2><div class='grid'>{indicator_cards}</div></section>
<section><h2>국내 관심후보</h2><div class='grid'>{pick_cards}</div></section>
<section><h2>뉴스</h2><ul class='news'>{news_items}</ul></section>
</main>
</body>
</html>"""


def write_html(html: str) -> None:
    directory = os.path.dirname(REPORT_OUTPUT_PATH)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(REPORT_OUTPUT_PATH, "w", encoding="utf-8") as handle:
        handle.write(html)


def refresh_kakao_access_token() -> str:
    rest_api_key = os.getenv("KAKAO_REST_API_KEY")
    refresh_token = os.getenv("KAKAO_REFRESH_TOKEN")
    missing = [name for name, value in {"KAKAO_REST_API_KEY": rest_api_key, "KAKAO_REFRESH_TOKEN": refresh_token}.items() if not value]
    if missing:
        raise RuntimeError("환경변수가 비어 있습니다: " + ", ".join(missing))
    data = {"grant_type": "refresh_token", "client_id": rest_api_key, "refresh_token": refresh_token}
    client_secret = os.getenv("KAKAO_CLIENT_SECRET")
    if client_secret:
        data["client_secret"] = client_secret
    response = requests.post(KAKAO_TOKEN_URL, data=data, timeout=20)
    response.raise_for_status()
    return response.json()["access_token"]


def send_kakao_message(text: str) -> None:
    access_token = refresh_kakao_access_token()
    url = report_page_url()
    template = {
        "object_type": "text",
        "text": text,
        "link": {"web_url": url, "mobile_web_url": url},
        "button_title": "전체 브리핑 보기",
    }
    response = requests.post(
        KAKAO_SEND_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        data={"template_object": json.dumps(template, ensure_ascii=False)},
        timeout=20,
    )
    response.raise_for_status()


def build() -> str:
    weather = fetch_weather()
    indicators = fetch_market_indicators()
    news = fetch_news()
    picks = score_watchlist(news)
    summary = render_kakao_summary(weather, indicators, picks, news)
    write_html(render_html(weather, indicators, news, picks, summary))
    return summary


def main() -> None:
    load_dotenv()
    summary = build()
    print(summary)
    if os.getenv("DRY_RUN") == "1" or os.getenv("SEND_KAKAO") == "0":
        return
    send_kakao_message(summary)


if __name__ == "__main__":
    main()
