# playlist-extractor

네이버 VIBE 보관함과 벅스 '내 앨범'에 담긴 곡을 추출해 Spotify 플레이리스트로 옮기는 **개인용** 도구입니다.

- VIBE와 벅스 모두 공개 API가 없고, 보관함은 로그인해야 볼 수 있습니다. 그래서 **내 PC에서 브라우저를 띄우고**, 직접 로그인한 화면에서 곡 목록을 읽어옵니다. 아이디나 비밀번호는 도구에 입력하지 않습니다.
- Spotify는 공식 Web API를 씁니다. 개발 모드(Premium 필요, 사용자 최대 5명)로 동작합니다.

> 📖 명령어별 옵션, 자주 쓰는 조합, 문제 해결은 **[명령어 설명서(docs/USAGE.md)](docs/USAGE.md)**에 정리되어 있습니다.

## 동작 순서

```
vibe / bugs  ─▶ output/vibe.json, output/bugs.json   (곡 제목·아티스트·앨범)
match        ─▶ output/match.csv                     (Spotify 곡 자동 매칭 결과, 직접 수정 가능)
push         ─▶ Spotify 플레이리스트 생성
```

## 준비

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e .
playwright install chromium
```

### Spotify 앱 등록 (최초 1회)

1. [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)에서 **Create app**
2. Redirect URI에 `http://127.0.0.1:8888/callback`를 그대로 입력합니다. `localhost`가 아니라 `127.0.0.1`이어야 합니다.
3. API는 **Web API**를 선택합니다.
4. 발급된 **Client ID**를 환경변수에 넣습니다.

```bash
export SPOTIFY_CLIENT_ID=발급받은_클라이언트_ID      # Windows PowerShell: $env:SPOTIFY_CLIENT_ID="..."
```

## 사용법

### 1. VIBE 추출 (서비스 종료 2026-12-31 전에!)

```bash
python -m playlist_extractor vibe --dump
```

1. 열린 브라우저에서 네이버에 로그인합니다. 로그인 상태는 `.browser-profile/`에 저장돼 다음부터는 생략됩니다.
2. **보관함 → 플레이리스트** 목록 화면에서 터미널로 돌아와 **Enter**를 누릅니다.
   - 목록에 있는 플레이리스트를 하나씩 자동으로 열어서 **플레이리스트별로 따로** 수집합니다. 예: 운동 / 국내 / 국힙&외힙 / Jpop
   - 특정 플레이리스트 하나만 원하면, 그 상세 페이지를 연 상태에서 Enter를 누르세요.
   - 곡이 없는 플레이리스트(예: 기본 리스트 0곡)는 건너뜁니다.
3. 끝나면 `q` + Enter를 누릅니다. 결과는 `output/vibe.json`에 저장되고, 플레이리스트별 곡 수가 표시됩니다.

### 2. 벅스 추출

```bash
python -m playlist_extractor bugs --dump
```

1. 열린 브라우저에서 벅스에 로그인합니다.
2. 옮길 **곡 목록 페이지**를 엽니다.
   - 내 음악 → 내 앨범 → 앨범 클릭
   - 또는 **최근 들은 곡**처럼 곡 목록이 보이는 페이지
3. 터미널에서 **Enter**를 누릅니다.
   - 목록이 1, 2, 3 … 페이지로 나뉘어 있으면 마지막 페이지까지 **자동으로 넘기며** 하나로 모읍니다. 번호 묶음이 넘어가는 '다음' 버튼도 자동으로 누릅니다.
   - 중간 페이지에서 Enter를 눌러도 1페이지로 돌아가서 처음부터 모읍니다.
4. 다른 앨범이나 페이지도 같은 방법으로 수집하고, 끝나면 `q` + Enter를 누릅니다. 결과는 `output/bugs.json`에 저장됩니다.

> 네이버나 벅스에서 로그인이 막히면 `--chrome` 옵션을 붙여 설치된 Chrome으로 실행해 보세요.
> 여러 번 나눠 실행해도 결과 파일에 이어서 저장됩니다. 새로 시작하려면 `--overwrite`를 붙이세요.

### 3. Spotify 곡 매칭

```bash
python -m playlist_extractor match output/vibe.json output/bugs.json
```

- 처음 실행하면 브라우저에서 Spotify 로그인과 권한 허용 창이 열립니다. 토큰은 `.spotify_token.json`에 저장됩니다.
- 결과는 `output/match.csv`에 저장됩니다. 엑셀로 열립니다.
  - `spotify_uri`가 비어 있는 곡은 못 찾은 곡입니다. Spotify 앱에서 해당 곡의 **공유 → 링크 복사**로 얻은 주소(`https://open.spotify.com/track/...`)를 이 칸에 붙여 넣으면 됩니다.
  - 잘못 매칭된 곡은 `spotify_uri`를 고치거나 비우면 됩니다.
  - `score`가 낮은 곡부터 확인하는 것을 권장합니다.

### 4. Spotify에 플레이리스트 생성

```bash
python -m playlist_extractor push output/match.csv --dry-run      # 미리보기
python -m playlist_extractor push output/match.csv --prefix "[VIBE] "
```

기본은 비공개 플레이리스트입니다. 공개로 만들려면 `--public`을 붙이세요. 특정 플레이리스트만 만들려면 `--only "이름1" "이름2"`를 쓰세요.

## 곡을 제대로 못 가져올 때

VIBE·벅스의 내부 구조는 공개된 것이 아니고 바뀔 수 있습니다. 그래서 이 도구는 특정 URL에 의존하지 않도록 만들었습니다.

- **VIBE**: 브라우저가 받은 JSON/XML 응답 중 `trackTitle` 필드가 있는 객체를 곡으로 인식합니다. 페이지 URL의 플레이리스트 ID가 들어간 응답을 우선하고, 추천곡 등 다른 목록은 제외합니다.
- **벅스**: 페이지 HTML의 곡 행(`tr[rowtype="track"]`)에서 제목(`p.title`), 아티스트(`p.artist`), 앨범(`a.album`)을 읽습니다.

곡이 0개로 나오거나 이상하게 나오면 `--dump`로 실행해 보세요. `output/raw_vibe/` 또는 `output/raw_bugs/`에 원본 응답과 HTML이 저장됩니다. 그중 곡 목록이 담긴 파일 하나를 공유해 주시면 파서를 맞출 수 있습니다. 덤프에는 개인정보가 담길 수 있으니 필요한 부분만 공유하세요.

## 개발

```bash
pip install -e '.[dev]'
pytest
```

`tests/fixtures/`의 VIBE·벅스 샘플은 실제 응답이 아니라 **예상 구조**입니다. 실제 덤프를 받으면 그것으로 교체하세요.
