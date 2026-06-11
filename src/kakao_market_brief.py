import json
import os
import textwrap
from dataclasses import dataclass
from datetime import datetime, timedelta
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
KAKAO_TOKEN_URL = "https://kauth.kakao.com/oauth/token"
KAKAO_SEND_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
MARKET_LINK = "https://m.stock.naver.com/"

KOREA_WATCHLIST = {
    "005930.KS": "삼성전자",
    "000660.KS": "SK하이닉스",
    "005380.KS": "현대차",
    "000270.KS": "기아",
    "035420.KS": "NAVER",
    "035720.KS": "카카오",
    "051910.KS": "LG화학",
    "207940.KS": "삼성바이오로직스",
    "005490.KS": "POSCO홀딩스",
    "105560.KS": "KB금융",
    "055550.KS": "신한지주",
    "012330.KS": "현대모비스",
}

US_WATCHLIST = {
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "NVDA": "NVIDIA",
    "AMZN": "Amazon",
    "GOOGL": "Alphabet",
    "META": "Meta",
    "AVGO": "Broadcom",
    "JPM": "JPMorgan Chase",
    "XOM": "Exxon Mobil",
    "LLY": "Eli Lilly",
    "UNH": "UnitedHealth",
    "COST": "Costco",
}

US_MARKET_TICKERS = {
    "^GSPC": "S&P 500",
    "^IXIC": "NASDAQ",
    "^DJI": "Dow",
    "KRW=X": "USD/KRW",
    "^TNX": "미국 10년물 금리",
    "CL=F": "WTI 유가",
    "BTC-USD": "비트코인",
}

NEWS_FEEDS = {
    "국내 주요뉴스": "https://news.google.com/rss/search?q=%ED%95%9C%EA%B5%AD+%EA%B2%BD%EC%A0%9C+%EC%A6%9D%EC%8B%9C+%EC%82%B0%EC%97%85&hl=ko&gl=KR&ceid=KR:ko",
    "미국 주식뉴스": "https://news.google.com/rss/search?q=US+stock+market+earnings+Fed+sector&hl=ko&gl=KR&ceid=KR:ko",
    "세계 주요뉴스": "https://news.google.com/rss/search?q=global+economy+geopolitics+markets+oil+rates&hl=ko&gl=KR&ceid=KR:ko",
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


@dataclass
class NewsItem:
    title: str
    link: str


@dataclass
class Indicator:
    name: str
    value: float
    change: float
    display: str


def pct_change(series, days: int) -> float:
    if len(series) <= days:
        return 0.0
    start = float(series.iloc[-days - 1])
    end = float(series.iloc[-1])
    if start == 0:
        return 0.0
    return (end / start - 1) * 100


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
        return (
            f"{city} 현재 {current['temperature_2m']}도, 강수 {current['precipitation']}mm, "
            f"풍속 {current['wind_speed_10m']}km/h. "
            f"오늘 {daily['temperature_2m_min'][0]}~{daily['temperature_2m_max'][0]}도, "
            f"강수확률 {daily['precipitation_probability_max'][0]}%."
        )
    except Exception as exc:
        return f"날씨 정보를 가져오지 못했습니다: {exc}"


def fetch_krx_index_snapshot() -> list[str]:
    if stock is None:
        return []

    today = datetime.now(KST).date()
    start = (today - timedelta(days=14)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")
    indices = {"1001": "KOSPI", "2001": "KOSDAQ"}
    lines = []

    for code, name in indices.items():
        try:
            frame = stock.get_index_ohlcv_by_date(start, end, code)
            if frame.empty or len(frame) < 2:
                continue
            close = frame["종가"].dropna()
            change = pct_change(close, 1)
            lines.append(f"{name}: {close.iloc[-1]:,.2f} ({change:+.2f}%, KRX)")
        except Exception:
            continue
    return lines


def fetch_yahoo_market_snapshot(indicators: list[Indicator] | None = None) -> list[str]:
    indicators = indicators or fetch_macro_indicators()
    return [indicator.display for indicator in indicators]


def fetch_macro_indicators() -> list[Indicator]:
    indicators = []
    for ticker, name in US_MARKET_TICKERS.items():
        try:
            history = yf.Ticker(ticker).history(period="7d", interval="1d", auto_adjust=False)
            close = history["Close"].dropna()
            if len(close) < 2:
                continue
            change = pct_change(close, 1)
            value = float(close.iloc[-1])
            suffix = "%"
            if ticker == "^TNX":
                display = f"{name}: {value:.2f}%p ({change:+.2f}%)"
            elif ticker == "KRW=X":
                display = f"{name}: {value:,.2f}원 ({change:+.2f}%)"
            elif ticker == "BTC-USD":
                display = f"{name}: ${value:,.0f} ({change:+.2f}%)"
            elif ticker == "CL=F":
                display = f"{name}: ${value:,.2f} ({change:+.2f}%)"
            else:
                display = f"{name}: {value:,.2f} ({change:+.2f}%)"
            indicators.append(Indicator(name, value, change, display))
        except Exception:
            continue
    return indicators


def fetch_market_snapshot(indicators: list[Indicator] | None = None) -> list[str]:
    krx_lines = fetch_krx_index_snapshot()
    if not krx_lines:
        # pykrx 설치 전에도 돌아가게 하기 위한 임시 대체값입니다.
        for ticker, name in {"^KS11": "KOSPI", "^KQ11": "KOSDAQ"}.items():
            try:
                history = yf.Ticker(ticker).history(period="7d", interval="1d", auto_adjust=False)
                close = history["Close"].dropna()
                if len(close) < 2:
                    continue
                krx_lines.append(f"{name}: {close.iloc[-1]:,.2f} ({pct_change(close, 1):+.2f}%, Yahoo)")
            except Exception:
                continue
    return krx_lines + fetch_yahoo_market_snapshot(indicators)


def fetch_news() -> dict[str, list[NewsItem]]:
    result = {}
    for section, url in NEWS_FEEDS.items():
        feed = feedparser.parse(url)
        result[section] = [
            NewsItem(title=entry.title, link=entry.link)
            for entry in feed.entries[:5]
        ]
    return result


def score_watchlist(watchlist: dict[str, str]) -> list[Pick]:
    picks = []
    for ticker, name in watchlist.items():
        try:
            history = yf.Ticker(ticker).history(period="2mo", interval="1d", auto_adjust=True)
            close = history["Close"].dropna()
            if len(close) < 25:
                continue
            one = pct_change(close, 1)
            five = pct_change(close, 5)
            twenty = pct_change(close, 20)
            score = (five * 0.45) + (twenty * 0.35) + (one * 0.20)
            picks.append(Pick(ticker, name, score, one, five, twenty, float(close.iloc[-1])))
        except Exception:
            continue
    return sorted(picks, key=lambda pick: pick.score, reverse=True)[:2]


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
    breakout = pick.close * 1.02
    support = pick.close * 0.97
    return f"체크 가격대: {breakout:,.2f} 상향 돌파 시 관심, {support:,.2f} 이탈 시 보수적 대응"


def market_temperature(markets: list[str], indicators: list[Indicator]) -> tuple[str, str]:
    score = 50
    reasons = []

    joined = "\n".join(markets)
    if "KOSPI" in joined and "+" in joined:
        score += 8
        reasons.append("국내 대표지수 양호")
    if "NASDAQ" in joined and "-" in joined:
        score -= 8
        reasons.append("미국 성장주 약세")

    for item in indicators:
        if item.name == "USD/KRW":
            if item.change > 0.4:
                score -= 8
                reasons.append("환율 상승 부담")
            elif item.change < -0.3:
                score += 5
                reasons.append("환율 안정")
        elif item.name == "미국 10년물 금리":
            if item.change > 1:
                score -= 7
                reasons.append("미 금리 상승")
            elif item.change < -1:
                score += 5
                reasons.append("미 금리 하락")
        elif item.name == "WTI 유가" and item.change > 2:
            score -= 4
            reasons.append("유가 상승")
        elif item.name == "비트코인":
            if item.change > 2:
                score += 4
                reasons.append("위험자산 선호")
            elif item.change < -2:
                score -= 4
                reasons.append("위험자산 약세")

    score = max(0, min(100, score))
    if score >= 65:
        label = f"{score}/100, 위험선호"
    elif score >= 45:
        label = f"{score}/100, 중립"
    else:
        label = f"{score}/100, 방어적"
    return label, ", ".join(reasons[:4]) or "뚜렷한 방향성은 제한적"


def one_line_conclusion(temperature: str, markets: list[str], indicators: list[Indicator]) -> str:
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
    titles = " ".join(item.title for items in news.values() for item in items).lower()
    checks = []

    sector_keywords = [
        ("반도체", ["semiconductor", "chip", "nvidia", "삼성전자", "sk하이닉스", "반도체"]),
        ("2차전지", ["battery", "배터리", "2차전지", "전기차", "ev"]),
        ("자동차", ["auto", "자동차", "현대차", "기아"]),
        ("금융", ["bank", "금리", "은행", "금융"]),
        ("조선/방산", ["shipbuilding", "defense", "조선", "방산"]),
        ("바이오", ["bio", "healthcare", "제약", "바이오"]),
        ("AI/전력", ["ai", "power", "electricity", "data center", "전력", "데이터센터"]),
    ]

    for sector, keywords in sector_keywords:
        hit = any(keyword in titles for keyword in keywords)
        if hit:
            checks.append(f"- {sector}: 관련 뉴스가 있어 장중 수급 확인")
        else:
            checks.append(f"- {sector}: 뉴스 모멘텀은 제한적, 지수 대비 상대강도 확인")

    for item in indicators:
        if item.name == "미국 10년물 금리" and item.change > 1:
            checks.append("- 성장주: 금리 상승 부담으로 추격 매수 자제")
        if item.name == "WTI 유가" and item.change > 2:
            checks.append("- 정유/화학/항공: 유가 영향 확인")
    return checks[:8]


def simple_report(
    weather: str,
    markets: list[str],
    indicators: list[Indicator],
    news: dict[str, list[NewsItem]],
    korea: list[Pick],
    us: list[Pick],
) -> str:
    today = datetime.now(KST).strftime("%Y-%m-%d")
    temperature, temperature_reason = market_temperature(markets, indicators)
    conclusion = one_line_conclusion(temperature, markets, indicators)
    lines = [
        f"[{today} 08:00] 데일리 시황 브리프",
        "",
        f"한 줄 결론: {conclusion}",
        f"시장 온도계: {temperature}",
        f"온도계 근거: {temperature_reason}",
        "",
        f"날씨: {weather}",
        "",
        "1. 시장 체크",
        *[f"- {line}" for line in markets],
        "",
        "2. 환율/금리/유가/비트코인",
        *[f"- {item.display}" for item in indicators if item.name in {"USD/KRW", "미국 10년물 금리", "WTI 유가", "비트코인"}],
        "",
        "3. 오늘의 해석",
        "- 국내 지수는 KRX 데이터를 우선 사용합니다. 값 옆에 Yahoo가 붙으면 임시 대체 데이터입니다.",
        "- 미국 지수와 환율은 Yahoo Finance 데이터를 사용합니다.",
        "- 관심종목은 중대형주 안에서 1일, 5일, 20일 흐름을 섞어 고릅니다.",
        "",
        "4. 섹터별 체크",
        *sector_check(news, indicators),
        "",
        "5. 주요뉴스",
    ]

    for section, items in news.items():
        lines.append(f"[{section}]")
        for item in items[:4]:
            lines.append(f"- {item.title}")
            lines.append(f"  {item.link}")

    lines.extend(["", "6. 국내 중대형주 관심후보"])
    for pick in korea:
        lines.extend(
            [
                f"- {pick.name}({pick.ticker})",
                f"  현재가: {pick.close:,.2f}",
                f"  흐름: 1일 {pick.one_day:+.2f}%, 5일 {pick.five_day:+.2f}%, 20일 {pick.twenty_day:+.2f}%",
                f"  근거: {pick_commentary(pick)}",
                f"  {check_price_text(pick)}",
                f"  리스크: {pick_risk(pick)}",
            ]
        )

    lines.extend(["", "7. 미국 중대형주 관심후보"])
    for pick in us:
        lines.extend(
            [
                f"- {pick.name}({pick.ticker})",
                f"  현재가: {pick.close:,.2f}",
                f"  흐름: 1일 {pick.one_day:+.2f}%, 5일 {pick.five_day:+.2f}%, 20일 {pick.twenty_day:+.2f}%",
                f"  근거: {pick_commentary(pick)}",
                f"  {check_price_text(pick)}",
                f"  리스크: {pick_risk(pick)}",
            ]
        )

    lines.extend(
        [
            "",
            "8. 오늘 확인할 것",
            "- 국내: 반도체, 자동차, 금융, 2차전지 업종 수급",
            "- 미국: 대형 기술주, 헬스케어, 금리 민감 업종 흐름",
            "- 매크로: 환율, 미 국채금리, 원유, 지정학 뉴스",
            f"- 시장 바로가기: {MARKET_LINK}",
            "",
            "주의: 자동화된 관심종목 후보이며 매수/매도 지시가 아닙니다.",
        ]
    )
    return "\n".join(lines)


def ai_refine_report(draft: str) -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or OpenAI is None:
        return draft

    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        messages=[
            {
                "role": "system",
                "content": (
                    "너는 한국 개인투자자를 위한 아침 시황 비서다. "
                    "과장하지 말고, 중대형주 관심후보를 근거와 리스크 중심으로 요약한다. "
                    "매수/매도 지시처럼 쓰지 않는다. 뉴스 링크는 반드시 유지한다."
                ),
            },
            {
                "role": "user",
                "content": (
                    "아래 원자료를 카카오톡으로 읽기 좋은 한국어 리포트로 다듬어줘. "
                    "시황, 업종, 주요뉴스, 국내 후보 2개, 미국 후보 2개, 리스크를 포함하고 "
                    "너무 짧지 않게 작성해줘.\n\n"
                    f"{draft}"
                ),
            },
        ],
        temperature=0.3,
        max_tokens=1800,
    )
    return response.choices[0].message.content.strip()


def refresh_kakao_access_token() -> str:
    rest_api_key = os.getenv("KAKAO_REST_API_KEY")
    refresh_token = os.getenv("KAKAO_REFRESH_TOKEN")
    missing = [
        name
        for name, value in {
            "KAKAO_REST_API_KEY": rest_api_key,
            "KAKAO_REFRESH_TOKEN": refresh_token,
        }.items()
        if not value
    ]
    if missing:
        raise RuntimeError(
            ".env 파일에 다음 값이 비어 있습니다: "
            + ", ".join(missing)
            + "\nnotepad .env 로 열어서 값을 채운 뒤 저장하세요."
        )

    data = {
        "grant_type": "refresh_token",
        "client_id": rest_api_key,
        "refresh_token": refresh_token,
    }
    client_secret = os.getenv("KAKAO_CLIENT_SECRET")
    if client_secret:
        data["client_secret"] = client_secret

    response = requests.post(KAKAO_TOKEN_URL, data=data, timeout=20)
    response.raise_for_status()
    return response.json()["access_token"]


def split_message(text: str, limit: int = 900) -> list[str]:
    chunks = []
    current = ""
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
        template = {
            "object_type": "text",
            "text": prefix + chunk,
            "link": {
                "web_url": MARKET_LINK,
                "mobile_web_url": MARKET_LINK,
            },
            "button_title": "시장 확인",
        }
        response = requests.post(
            KAKAO_SEND_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            data={"template_object": json.dumps(template, ensure_ascii=False)},
            timeout=20,
        )
        response.raise_for_status()


def build_report() -> str:
    weather = fetch_weather()
    indicators = fetch_macro_indicators()
    markets = fetch_market_snapshot(indicators)
    news = fetch_news()
    korea = score_watchlist(KOREA_WATCHLIST)
    us = score_watchlist(US_WATCHLIST)
    draft = simple_report(weather, markets, indicators, news, korea, us)
    return ai_refine_report(draft)


def main() -> None:
    load_dotenv()
    report = build_report()
    print(report)
    if os.getenv("DRY_RUN") == "1":
        return
    send_kakao_message(report)


if __name__ == "__main__":
    main()
