# 카카오톡 매일 시황 리포트

매일 오전 8시(KST)에 부산 날씨, 국내/미국 시장, 주요 뉴스, 국내/미국 중대형주 관심후보를 카카오톡 "나에게 보내기"로 전송합니다.

## 이번 버전 특징

- 부산 날씨 기본값 적용
- 국내 지수는 `pykrx`로 KRX 데이터를 우선 사용
- 뉴스 제목 아래에 링크 포함
- 리포트를 더 자세하게 작성
- 카카오톡 길이 제한에 걸리지 않도록 긴 리포트를 여러 메시지로 나눠 전송
- `시장 확인` 버튼은 네이버 금융으로 연결
- 국내 2개, 미국 2개 관심종목은 중대형주 후보군 안에서만 선정

## 설치

```powershell
cd C:\Users\grrrr\Documents\Codex\2026-06-11\8-2\outputs\kakao-market-brief
pip install -r requirements.txt
```

## .env 설정

```powershell
notepad .env
```

아래처럼 채웁니다.

```dotenv
KAKAO_REST_API_KEY=본인_REST_API_KEY
KAKAO_CLIENT_SECRET=
KAKAO_REFRESH_TOKEN=본인_REFRESH_TOKEN
OPENAI_API_KEY=
REPORT_CITY=Busan
REPORT_LAT=35.1796
REPORT_LON=129.0756
```

`OPENAI_API_KEY`는 선택입니다. 비워도 작동합니다. 넣으면 문장이 더 자연스럽게 다듬어집니다.

## 테스트 실행

```powershell
python src\kakao_market_brief.py
```

카카오톡 "나와의 채팅"에 여러 개의 메시지로 리포트가 오면 성공입니다.

## GitHub에 올리는 법

### 1. GitHub에서 저장소 만들기

1. [GitHub](https://github.com/) 접속
2. 오른쪽 위 `+` 클릭
3. `New repository` 클릭
4. Repository name 예시: `kakao-market-brief`
5. `Private` 선택 권장
6. `Create repository` 클릭

### 2. 내 PC 폴더를 GitHub에 연결

아래 명령에서 `YOUR_GITHUB_ID`만 본인 GitHub 아이디로 바꿉니다.

```powershell
cd C:\Users\grrrr\Documents\Codex\2026-06-11\8-2\outputs\kakao-market-brief
git init
git branch -M main
git add .
git commit -m "Add daily Kakao market brief"
git remote add origin https://github.com/YOUR_GITHUB_ID/kakao-market-brief.git
git push -u origin main
```

`git` 명령이 안 되면 Git for Windows를 설치해야 합니다.

[Git for Windows](https://git-scm.com/download/win)

### 3. GitHub Secrets 넣기

GitHub 저장소 화면에서:

1. `Settings`
2. `Secrets and variables`
3. `Actions`
4. `New repository secret`

아래 값을 각각 추가합니다.

- `KAKAO_REST_API_KEY`
- `KAKAO_REFRESH_TOKEN`
- `KAKAO_CLIENT_SECRET` 비어 있으면 생략 가능
- `OPENAI_API_KEY` 선택
- `REPORT_CITY` 값: `Busan`
- `REPORT_LAT` 값: `35.1796`
- `REPORT_LON` 값: `129.0756`

### 4. 자동 실행 확인

저장소의 `Actions` 탭으로 이동합니다.

`Daily Kakao Market Brief` 워크플로가 보이면 성공입니다. 매일 한국시간 오전 8시에 자동 실행됩니다.

바로 테스트하려면:

1. `Actions`
2. `Daily Kakao Market Brief`
3. `Run workflow`

## 주의

이 리포트는 자동화된 정보 요약과 관심종목 후보 제시입니다. 실제 매수/매도 판단은 본인의 투자 기준과 최신 공시, 실적, 리스크 확인 후에만 진행하세요.
