import json
import os
import textwrap
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import feedparser
import requests
import yfinance as yf
from dotenv import load_dotenv

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

try:
    from pykrx import stock
except ImportError:
    stock = None

KST = ZoneInfo("Asia/Seoul")
UTC = ZoneInfo("UTC")
KAKAO_TOKEN_URL = "https://kauth.kakao.com/oauth/token"
KAKAO_SEND_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
MARKET_LINK = "https://m.stock.naver.com/"
NEWS_CARD_IMAGE = "https://developers.kakao.com/assets/img/about/logos/kakaolink/kakaolink_btn_medium.png"

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

SECTOR_KEYWORDS = {
    "반도체/AI": ["반도체", "chip", "semiconductor", "nvidia", "ai", "삼성전자", "하이닉스"],
    "자동차": ["자동차", "현대차", "기아", "auto", "ev"],
    "2차전지/소재": ["배터리", "2차전지", "전기차", "battery", "리튬", "소재"],
    "금융": ["은행", "금융", "금리", "보험", "주주환원"],
    "조선/방산/전력": ["조선", "방산", "방위", "전력", "원전", "shipbuilding", "defense"],
    "바이오/플랫폼": ["바이오", "제약", "셀트리온", "네이버", "카카오", "플랫폼"],
}

TICKER_SECTOR = {
    "005930.KS": "반도체/AI", "000660.KS": "반도체/AI",
    "035420.KS": "바이오/플랫폼", "035720.KS": "바이오/플랫폼", "068270.KS": "바이오/플랫폼", "207940.KS": "바이오/플랫폼",
    "005380.KS": "자동차", "000270.KS": "자동차", "012330.KS": "자동차",
    "051910.KS": "2차전지/소재", "373220.KS": "2차전지/소재", "006400.KS": "2차전지/소재", "005490.KS": "2차전지/소재", "003670.KS": "2차전지/소재",
    "105560.KS": "금융", "055550.KS": "금융", "086790.KS": "금융", "032830.KS": "금융",
    "009540.KS": "조선/방산/전력", "329180.KS": "조선/방산/전력", "012450.KS": "조선/방산/전력", "042660.KS": "조선/방산/전력", "034020.KS": "조선/방산/전력",
}

US_MARKET_TICKERS = {
    "^GSPC": "S&P 500", "^IXIC": "NASDAQ", "^DJI": "Dow", "KRW=X": "USD/KRW",
    "^TNX": "미국 10년물 금리", "CL=F": "WTI 유가", "BTC-USD": "비트코인",
}

NEWS_QUERIES = {
    "국내 주요뉴스": "한국 경제 증시 산업 when:1d",
    "미국 주식뉴스": "US stock market earnings Fed sector when:1d",
    "세계 주요뉴스": "global economy geopolitics markets oil rates when:1d",
}

@dataclass
class Pick:
    ticker: str
    name: str
    score: float
    one_day: float
    five_day: float
    twenty_day: float
    close: float
    as_of: str
    sector: str
    selection_reason: str

@dataclass
class NewsItem:
    title: str
    link: str
    published_at: datetime | None

@dataclass
class Indicator:
    name: str
    value: float
    change: float
    display: str
    as_of: str

def now_kst() -> datetime:
    return datetime.now(KST)

def format_dt(dt: datetime | None) -> str:
    return "발행시각 미확인" if dt is None else dt.astimezone(KST).strftime("%m-%d %H:%M")

def compact_title(title: str, limit: int = 52) -> str:
    clean = " ".join(title.split())
    return clean if len(clean) <= limit else clean[: limit - 1] + "…"

def latest_index_label(index) -> str:
    if len(index) == 0:
        return "기준시각 미확인"
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

def format_change(change: float) -> str:
    if change > 0:
        return f"▲ {change:.2f}%"
    if change < 0:
        return f"▼ {abs(change):.2f}%"
    return "━ 0.00%"

def market_line(name: str, value: float, change: float, as_of: str, source: str | None = None, suffix: str = "") -> str:
    source_text = f" · {source}" if source else ""
    return f"{name}\n  {value:,.2f}{suffix} · {format_change(change)}\n  기준 {as_of}{source_text}"

def news_feed_url(query: str) -> str:
    params = {"q": query, "hl": "ko", "gl": "KR", "ceid": "KR:ko", "_": str(int(time.time()))}
    return "https://news.google.com/rss/search?" + urlencode(params)

def fetch_weather() -> str:
    city = os.getenv("REPORT_CITY", "Busan")
    lat = os.getenv("REPORT_LAT", "35.1796")
    lon = os.getenv("REPORT_LON", "129.0756")
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}&current=temperature_2m,precipitation,wind_speed_10m"
        "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max"
        "&timezone=Asia%2FSeoul&forecast_days=1"
    )
    try:
        data = requests.get(url, timeout=20).json()
        current = data["current"]
        daily = data["daily"]
        observed = current.get("time", "시각 미확인")
        return (
            f"{city} 현재 {current['temperature_2m']}도, 강수 {current['precipitation']}mm, "
            f"풍속 {current['wind_speed_10m']}km/h. "
            f"오늘 {daily['temperature_2m_min'][0]}~{daily['temperature_2m_max'][0]}도, "
            f"강수확률 {daily['precipitation_probability_max'][0]}%. 기준 {observed}"
        )
    except Exception as exc:
        return f"날씨 정보를 가져오지 못했습니다: {exc}"

def fetch_krx_index_snapshot() -> list[str]:
    if stock is None:
        return []
    today = now_kst().date()
    start = (today - timedelta(days=14)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")
    lines = []
    for code, name in {"1001": "KOSPI", "2001": "KOSDAQ"}.items():
        try:
            frame = stock.get_index_ohlcv_by_date(start, end, code)
            if frame.empty or len(frame) < 2:
                continue
            close = frame["종가"].dropna()
            lines.append(market_line(name, float(close.iloc[-1]), pct_change(close, 1), close.index[-1].strftime("%Y-%m-%d"), "KRX"))
        except Exception:
            continue
    return lines

def fetch_macro_indicators() -> list[Indicator]:
    indicators = []
    for ticker, name in US_MARKET_TICKERS.items():
        try:
            interval = "1h" if ticker in {"KRW=X", "BTC-USD", "CL=F"} else "1d"
            period = "5d" if interval == "1h" else "7d"
            history = yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=False)
            close = history["Close"].dropna()
            if len(close) < 2:
                continue
            change = pct_change(close, 1)
            value = float(close.iloc[-1])
            as_of = latest_index_label(close.index)
            if ticker == "BTC-USD":
                display = f"{name}\n  ${value:,.0f} · {format_change(change)}\n  기준 {as_of}"
            elif ticker == "CL=F":
                display = f"{name}\n  ${value:,.2f} · {format_change(change)}\n  기준 {as_of}"
            elif ticker == "KRW=X":
                display = market_line(name, value, change, as_of, suffix="원")
            elif ticker == "^TNX":
                display = market_line(name, value, change, as_of, suffix="%p")
            else:
                display = market_line(name, value, change, as_of)
            indicators.append(Indicator(name, value, change, display, as_of))
        except Exception:
            continue
    return indicators

def fetch_market_snapshot(indicators: list[Indicator] | None = None) -> list[str]:
    krx_lines = fetch_krx_index_snapshot()
    if not krx_lines:
        for ticker, name in {"^KS11": "KOSPI", "^KQ11": "KOSDAQ"}.items():
            try:
                history = yf.Ticker(ticker).history(period="7d", interval="1d", auto_adjust=False)
                close = history["Close"].dropna()
                if len(close) >= 2:
                    krx_lines.append(market_line(name, float(close.iloc[-1]), pct_change(close, 1), latest_index_label(close.index), "Yahoo"))
            except Exception:
                continue
    indicators = indicators or fetch_macro_indicators()
    return krx_lines + [indicator.display for indicator in indicators]

def parse_published(entry) -> datetime | None:
    parsed = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    return None if not parsed else datetime(*parsed[:6], tzinfo=UTC).astimezone(KST)

def fetch_news() -> dict[str, list[NewsItem]]:
    result = {}
    cutoff = now_kst() - timedelta(hours=48)
    for section, query in NEWS_QUERIES.items():
        feed = feedparser.parse(news_feed_url(query))
        items = []
        for entry in feed.entries:
            published_at = parse_published(entry)
            if published_at is not None and published_at < cutoff:
                continue
            items.append(NewsItem(entry.title, entry.link, published_at))
        items.sort(key=lambda item: item.published_at or datetime.min.replace(tzinfo=KST), reverse=True)
        result[section] = items[:6]
    return result

def news_sector_scores(news: dict[str, list[NewsItem]]) -> dict[str, int]:
    titles = " ".join(item.title for items in news.values() for item in items).lower()
    return {sector: sum(1 for keyword in keywords if keyword.lower() in titles) for sector, keywords in SECTOR_KEYWORDS.items()}

def score_watchlist(watchlist: dict[str, str], news: dict[str, list[NewsItem]]) -> list[Pick]:
    bucket = KOREA_BUCKETS[now_kst().date().toordinal() % len(KOREA_BUCKETS)]
    sector_scores = news_sector_scores(news)
    picks = []
    for ticker, name in watchlist.items():
        try:
            history = yf.Ticker(ticker).history(period="3mo", interval="1d", auto_adjust=True)
            close = history["Close"].dropna()
            volume = history["Volume"].dropna() if "Volume" in history else []
            if len(close) < 25:
                continue
            one, five, twenty = pct_change(close, 1), pct_change(close, 5), pct_change(close, 20)
            vol_score = 0.0
            if len(volume) >= 21 and float(volume.iloc[-21:-1].mean()) > 0:
                vol_score = min((float(volume.iloc[-1]) / float(volume.iloc[-21:-1].mean()) - 1) * 3, 12)
            sector = TICKER_SECTOR.get(ticker, "기타")
            news_score = min(sector_scores.get(sector, 0) * 3, 12)
            rotation_bonus = 6 if ticker in bucket else 0
            overheat_penalty = 8 if one > 5 or twenty > 25 else 0
            falling_penalty = 6 if five < -8 else 0
            score = (five * 0.35) + (twenty * 0.25) + (one * 0.15) + vol_score + news_score + rotation_bonus - overheat_penalty - falling_penalty
            reason = f"{sector} 섹터, {'오늘 순환 후보군 포함' if ticker in bucket else '보조 후보군'}, 뉴스점수 {news_score:.0f}, 거래량점수 {vol_score:.1f}"
            picks.append(Pick(ticker, name, score, one, five, twenty, float(close.iloc[-1]), latest_index_label(close.index), sector, reason))
        except Exception:
            continue
    picks = sorted(picks, key=lambda pick: pick.score, reverse=True)
    selected, used_sectors = [], set()
    for pick in picks:
        if pick.sector in used_sectors and len(selected) < 2:
            continue
        selected.append(pick)
        used_sectors.add(pick.sector)
        if len(selected) == 2:
            return selected
    return picks[:2]

def pick_commentary(pick: Pick) -> str:
    if pick.twenty_day > 8 and pick.five_day > 0:
        return "중기 추세와 단기 흐름이 같이 살아있는 모멘텀 후보"
    if pick.twenty_day > 8 and pick.five_day <= 0:
        return "중기 추세는 양호하지만 최근 눌림이 있어 반등 확인 필요"
    if pick.five_day > 3:
        return "단기 수급이 강한 편이라 시장 반등 시 탄력이 기대되는 후보"
    return "상대적으로 방어적인 흐름을 보이는 중대형주 후보"

def pick_risk(pick: Pick) -> str:
    if pick.one_day > 4:
        return "하루 상승폭이 커서 추격 매수 리스크"
    if pick.five_day < -5:
        return "최근 1주 조정이 커서 추가 하락 확인 필요"
    if pick.twenty_day > 15:
        return "20일 상승률이 높아 단기 과열 가능성"
    return "시장 전체 변동성, 환율, 금리 뉴스에 따른 흔들림"

def check_price_text(pick: Pick) -> str:
    return f"체크 가격대: {pick.close * 1.02:,.2f} 상향 돌파 시 관심, {pick.close * 0.97:,.2f} 이탈 시 보수적 대응"

def market_temperature(markets: list[str], indicators: list[Indicator]) -> tuple[str, str]:
    score, reasons = 50, []
    joined = "\n".join(markets)
    if "KOSPI" in joined and "▲" in joined:
        score += 8; reasons.append("국내 대표지수 양호")
    if "NASDAQ" in joined and "▼" in joined:
        score -= 8; reasons.append("미국 성장주 약세")
    for item in indicators:
        if item.name == "USD/KRW" and item.change > 0.4:
            score -= 8; reasons.append("환율 상승 부담")
        elif item.name == "USD/KRW" and item.change < -0.3:
            score += 5; reasons.append("환율 안정")
        elif item.name == "미국 10년물 금리" and item.change > 1:
            score -= 7; reasons.append("미 금리 상승")
        elif item.name == "미국 10년물 금리" and item.change < -1:
            score += 5; reasons.append("미 금리 하락")
    score = max(0, min(100, score))
    label = f"{score}/100, 위험선호" if score >= 65 else f"{score}/100, 중립" if score >= 45 else f"{score}/100, 방어적"
    return label, ", ".join(reasons[:4]) or "뚜렷한 방향성은 제한적"

def one_line_conclusion(temperature: str, indicators: list[Indicator]) -> str:
    text = "오늘은 확인 후 대응이 유리한 중립 장세입니다."
    if "위험선호" in temperature:
        text = "오늘은 강한 종목 위주로 선별 접근할 수 있는 장세입니다."
    elif "방어적" in temperature:
        text = "오늘은 추격보다 현금 비중과 리스크 관리가 우선인 장세입니다."
    for item in indicators:
        if item.name == "USD/KRW" and item.change > 0.4:
            return text + " 특히 환율 상승 부담을 같이 봐야 합니다."
        if item.name == "NASDAQ" and item.change < -1:
            return text + " 미국 기술주 약세가 국내 성장주에 부담이 될 수 있습니다."
    return text

def sector_check(news: dict[str, list[NewsItem]], indicators: list[Indicator]) -> list[str]:
    scores = news_sector_scores(news)
    checks = [f"- {sector}: {'최근 뉴스가 있어 장중 수급 확인' if scores.get(sector, 0) else '뉴스 모멘텀은 제한적, 지수 대비 상대강도 확인'}" for sector in SECTOR_KEYWORDS]
    for item in indicators:
        if item.name == "미국 10년물 금리" and item.change > 1:
            checks.append("- 성장주: 금리 상승 부담으로 추격 매수 자제")
        if item.name == "WTI 유가" and item.change > 2:
            checks.append("- 정유/화학/항공: 유가 영향 확인")
    return checks[:8]

def freshness_note(news: dict[str, list[NewsItem]]) -> str:
    news_times = [item.published_at for items in news.values() for item in items if item.published_at is not None]
    if not news_times:
        return "시장 데이터 기준은 각 항목에 표시. 뉴스 발행시각 확인 불가."
    latest_news = max(news_times)
    hours = (now_kst() - latest_news).total_seconds() / 3600
    return f"시장 데이터 기준은 각 항목에 표시. 최신 뉴스 {format_dt(latest_news)} 기준, 약 {hours:.1f}시간 전."

def simple_report(weather: str, markets: list[str], indicators: list[Indicator], news: dict[str, list[NewsItem]], korea: list[Pick]) -> str:
    generated_at = now_kst().strftime("%Y-%m-%d %H:%M")
    temperature, temperature_reason = market_temperature(markets, indicators)
    lines = [
        f"[{generated_at} KST] 데일리 시황 브리프", f"최신성 체크: {freshness_note(news)}", "", "━━━━━━━━━━━━", "",
        f"한 줄 결론: {one_line_conclusion(temperature, indicators)}", "", f"시장 온도계: {temperature}", f"온도계 근거: {temperature_reason}", "", "━━━━━━━━━━━━", "",
        f"날씨: {weather}", "", "1. 시장 체크", "",
    ]
    for line in markets:
        lines.extend([line, ""])
    lines.extend(["2. 환율/금리/유가/비트코인", ""])
    for item in indicators:
        if item.name in {"USD/KRW", "미국 10년물 금리", "WTI 유가", "비트코인"}:
            lines.extend([item.display, ""])
    lines.extend([
        "3. 오늘의 해석", "",
        "- 국내 후보는 확정 순위가 아니라 당일 순환 후보군, 뉴스 섹터, 가격 흐름, 거래량을 섞어 고릅니다.", "",
        "- 같은 섹터 2개가 동시에 뽑히지 않도록 분산합니다.", "",
        "- 해외 개별종목 후보는 제외하고 국내 중대형주 후보만 표시합니다.", "",
        "4. 섹터별 체크", "",
    ])
    for line in sector_check(news, indicators):
        lines.extend([line, ""])
    lines.extend(["5. 주요뉴스", ""])
    for section, items in news.items():
        lines.append(f"[{section}]")
        if not items:
            lines.extend(["- 최근 48시간 내 확인된 뉴스가 부족합니다.", ""])
            continue
        for item in items[:4]:
            lines.append(f"- [{format_dt(item.published_at)}] {compact_title(item.title)}")
        lines.append("")
    lines.extend(["뉴스 링크는 이어서 보내는 카드에서 제목을 눌러 확인하실 수 있습니다.", "", "6. 국내 중대형주 관심후보", ""])
    for pick in korea:
        lines.extend([
            f"- {pick.name}({pick.ticker})", "", f"  현재가: {pick.close:,.2f}", f"  기준: {pick.as_of}",
            f"  흐름: 1일 {format_change(pick.one_day)}, 5일 {format_change(pick.five_day)}, 20일 {format_change(pick.twenty_day)}", "",
            f"  선정방식: {pick.selection_reason}", "", f"  근거: {pick_commentary(pick)}", "", f"  {check_price_text(pick)}", "", f"  리스크: {pick_risk(pick)}", "",
        ])
    lines.extend([
        "7. 오늘 확인할 것", "", "- 국내: 반도체, 자동차, 금융, 2차전지, 조선/방산, 바이오/플랫폼 수급", "",
        "- 미국: 대형 기술주, 금리 민감 업종 흐름", "", "- 매크로: 환율, 미 국채금리, 원유, 지정학 뉴스", "",
        f"- 시장 바로가기: {MARKET_LINK}", "", "주의: 자동화된 관심종목 후보이며 매수/매도 지시가 아닙니다.",
    ])
    return "\n".join(lines)

def ai_refine_report(draft: str) -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or OpenAI is None:
        return draft
    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        messages=[
            {"role": "system", "content": "너는 한국 개인투자자를 위한 아침 시황 비서다. 과장하지 말고 근거와 리스크 중심으로 요약한다. 해외 개별종목 추천은 절대 넣지 않는다. 뉴스 링크는 본문에 넣지 않는다. 원문의 생성시각, 최신성 체크, 데이터 기준시각, 뉴스 발행시각, 선정방식은 삭제하거나 바꾸지 않는다."},
            {"role": "user", "content": "아래 원자료를 카카오톡으로 읽기 좋게 다듬어줘. 문단 사이 빈 줄을 유지하고, 긴 URL은 절대 본문에 넣지 마.\n\n" + draft},
        ],
        temperature=0.25,
        max_tokens=1800,
    )
    return response.choices[0].message.content.strip()

def refresh_kakao_access_token() -> str:
    rest_api_key = os.getenv("KAKAO_REST_API_KEY")
    refresh_token = os.getenv("KAKAO_REFRESH_TOKEN")
    missing = [name for name, value in {"KAKAO_REST_API_KEY": rest_api_key, "KAKAO_REFRESH_TOKEN": refresh_token}.items() if not value]
    if missing:
        raise RuntimeError(".env 파일에 다음 값이 비어 있습니다: " + ", ".join(missing))
    data = {"grant_type": "refresh_token", "client_id": rest_api_key, "refresh_token": refresh_token}
    client_secret = os.getenv("KAKAO_CLIENT_SECRET")
    if client_secret:
        data["client_secret"] = client_secret
    response = requests.post(KAKAO_TOKEN_URL, data=data, timeout=20)
    response.raise_for_status()
    return response.json()["access_token"]

def split_message(text: str, limit: int = 900) -> list[str]:
    chunks, current = [], ""
    for paragraph in text.split("\n\n"):
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
        if len(paragraph) <= limit:
            current = paragraph
        else:
            chunks.extend(textwrap.wrap(paragraph, width=limit, replace_whitespace=False))
            current = ""
    if current:
        chunks.append(current)
    return chunks

def send_kakao_message(text: str) -> None:
    access_token = refresh_kakao_access_token()
    chunks = split_message(text)
    for index, chunk in enumerate(chunks, start=1):
        prefix = f"({index}/{len(chunks)})\n" if len(chunks) > 1 else ""
        template = {"object_type": "text", "text": prefix + chunk, "link": {"web_url": MARKET_LINK, "mobile_web_url": MARKET_LINK}, "button_title": "시장 확인"}
        response = requests.post(KAKAO_SEND_URL, headers={"Authorization": f"Bearer {access_token}"}, data={"template_object": json.dumps(template, ensure_ascii=False)}, timeout=20)
        response.raise_for_status()

def flatten_news(news: dict[str, list[NewsItem]], limit: int = 3) -> list[NewsItem]:
    items = [item for section_items in news.values() for item in section_items if item.link]
    items.sort(key=lambda item: item.published_at or datetime.min.replace(tzinfo=KST), reverse=True)
    return items[:limit]

def send_news_link_card(news: dict[str, list[NewsItem]]) -> None:
    items = flatten_news(news)
    if not items:
        return
    access_token = refresh_kakao_access_token()
    contents = [{"title": compact_title(item.title, 38), "description": format_dt(item.published_at), "image_url": NEWS_CARD_IMAGE, "link": {"web_url": item.link, "mobile_web_url": item.link}} for item in items]
    template = {
        "object_type": "list",
        "header_title": "오늘 주요뉴스 링크",
        "header_link": {"web_url": "https://news.google.com/", "mobile_web_url": "https://news.google.com/"},
        "contents": contents,
        "buttons": [{"title": "뉴스 더 보기", "link": {"web_url": "https://news.google.com/topstories?hl=ko&gl=KR&ceid=KR:ko", "mobile_web_url": "https://news.google.com/topstories?hl=ko&gl=KR&ceid=KR:ko"}}],
    }
    response = requests.post(KAKAO_SEND_URL, headers={"Authorization": f"Bearer {access_token}"}, data={"template_object": json.dumps(template, ensure_ascii=False)}, timeout=20)
    response.raise_for_status()

def build_report_and_news() -> tuple[str, dict[str, list[NewsItem]]]:
    weather = fetch_weather()
    indicators = fetch_macro_indicators()
    markets = fetch_market_snapshot(indicators)
    news = fetch_news()
    korea = score_watchlist(KOREA_WATCHLIST, news)
    draft = simple_report(weather, markets, indicators, news, korea)
    return ai_refine_report(draft), news

def main() -> None:
    load_dotenv()
    report, news = build_report_and_news()
    print(report)
    if os.getenv("DRY_RUN") == "1":
        return
    send_kakao_message(report)
    send_news_link_card(news)

if __name__ == "__main__":
    main()
