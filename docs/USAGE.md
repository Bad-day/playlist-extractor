# 명령어 설명서

Windows PowerShell 기준으로 설명합니다. Mac은 경로 구분자를 `\` 대신 `/`로 쓰면 됩니다.
설치와 Spotify 앱 등록 방법은 [README](../README.md)를 참고하세요.

---

## 0. 실행할 때마다 먼저 할 일

PowerShell을 새로 열었다면 아래 세 줄을 먼저 입력합니다.

```powershell
cd "C:\Users\<이름>\Downloads\playlist-extractor-main"   # 프로그램 폴더로 이동
.venv\Scripts\Activate.ps1                                # 가상환경 켜기 → 줄 앞에 (.venv) 표시
$env:SPOTIFY_CLIENT_ID="발급받은_Client_ID"                # match / push 할 때만 필요
```

- 명령은 **반드시 프로그램 폴더에서** 실행해야 합니다. 로그인 정보와 결과 파일이 이 폴더 안에 저장되기 때문입니다.
- 이미 열어 둔 창에서 이어서 쓴다면 다시 입력할 필요가 없습니다. 줄 앞에 `(.venv)`가 붙어 있으면 그대로 쓰면 됩니다.

---

## 1. 전체 흐름

```
① vibe   VIBE 보관함 추출            → output\vibe.json
② bugs   벅스 곡 목록 추출           → output\bugs.json
③ match  Spotify에서 같은 곡 찾기     → output\match.csv   (엑셀로 확인·수정)
④ push   Spotify 플레이리스트 만들기
```

모든 명령의 형식은 같습니다.

```powershell
python -m playlist_extractor <명령> [옵션]
```

명령마다 옵션 목록을 보려면 `--help`를 붙이세요. 예: `python -m playlist_extractor bugs --help`

---

## 2. `vibe` — 네이버 VIBE 보관함 추출

```powershell
python -m playlist_extractor vibe --dump --overwrite
```

**진행 방법**
1. 브라우저가 열리면 네이버에 로그인합니다. 처음 한 번만 하면 다음부터는 로그인 상태가 유지됩니다.
2. **보관함 → 플레이리스트** 목록 화면에서 PowerShell로 돌아와 **Enter**를 누릅니다.
   - 플레이리스트를 하나씩 자동으로 열어 **각각 따로** 저장합니다. 0곡인 플레이리스트는 건너뜁니다.
   - 특정 플레이리스트 하나만 원하면, 그 플레이리스트 화면을 연 상태에서 Enter를 누르세요.
3. 끝나면 `q`를 입력하고 Enter를 누릅니다. 플레이리스트별 곡 수가 출력됩니다.

**옵션**

| 옵션 | 설명 |
|---|---|
| `--dump` | 화면이 받은 원본 데이터를 `output\raw_vibe\`에 저장합니다. 문제가 생겼을 때 원인 확인용입니다. |
| `--overwrite` | 기존 `vibe.json`을 지우고 새로 저장합니다. 빼면 기존 내용 뒤에 이어서 저장합니다. |
| `--chrome` | 프로그램이 띄우는 브라우저 대신 PC에 설치된 크롬으로 실행합니다. 로그인이 막힐 때 쓰세요. |
| `-o 파일경로` | 저장할 파일을 직접 지정합니다. 기본값은 `output\vibe.json`입니다. |

**출력 예**
```
  - 운동: 11곡
  - 국힙&외힙: 128곡
저장: output\vibe.json  (8개 플레이리스트, 301곡)
```
`N곡 중 M곡만 가져왔습니다` 경고가 뜨면 `docs\ISSUES.md` 2번을 참고하세요.

---

## 3. `bugs` — 벅스 곡 목록 추출

```powershell
python -m playlist_extractor bugs --dump
```

**진행 방법**
1. 브라우저가 열리면 벅스에 로그인합니다.
2. 옮길 곡 목록 페이지를 엽니다.
   - **내 음악 → 내 앨범 → 앨범 클릭**
   - 또는 **최근 들은 곡**
3. PowerShell에서 **Enter**를 누릅니다.
   - 목록이 1, 2, 3 … 페이지로 나뉘어 있으면 **마지막 페이지까지 자동으로 넘기며** 하나로 모읍니다.
   - 중간 페이지에서 눌러도 1페이지부터 모읍니다.
4. 다른 앨범도 2~3번을 반복하고, 끝나면 `q`를 입력하고 Enter를 누릅니다.

옵션은 `vibe`와 같습니다(`--dump`, `--overwrite`, `--chrome`, `-o`). 원본 데이터는 `output\raw_bugs\`에 저장됩니다.

> **기존 결과가 지워지나요?**
> 아니요. `--overwrite`를 붙이지 않으면 기존 `bugs.json`은 그대로 두고 **뒤에 이어서** 저장합니다.
> 같은 페이지를 다시 수집하면 그 항목만 새 결과로 바뀝니다. 최근 들은 곡을 다시 수집할 때는 **1페이지를 연 상태**에서 Enter를 누르세요. 다른 페이지에서 시작하면 `최근 들은 곡 (2)`처럼 하나가 더 생길 수 있습니다.

---

## 4. `match` — Spotify에서 같은 곡 찾기

```powershell
python -m playlist_extractor match output\vibe.json output\bugs.json
```

- 처음 실행할 때만 브라우저에서 Spotify 로그인과 **동의** 화면이 뜹니다.
- 곡마다 `✔`(찾음) 또는 `✘`(못 찾음)가 표시되고, 결과는 `output\match.csv`에 저장됩니다.
- 파일은 하나만 넣어도 됩니다. 예: `match output\vibe.json`

**옵션**

| 옵션 | 설명 |
|---|---|
| `--only "이름1" "이름2"` | 지정한 이름의 플레이리스트만 매칭합니다. 예: `--only "운동" "Jpop"` |
| `-o 파일경로` | 결과 CSV를 저장할 위치입니다. 기본값은 `output\match.csv`입니다. |
| `--client-id ID` | 환경변수 대신 Client ID를 직접 넣을 때 씁니다. |

**match.csv 확인과 수정 (엑셀)**

| 열 | 뜻 |
|---|---|
| `playlist` | 원래 플레이리스트 이름입니다. Spotify에서도 이 이름으로 만들어집니다. |
| `title` / `artist` / `album` | VIBE·벅스에 있던 곡 정보입니다. |
| `spotify_uri` | 찾은 Spotify 곡입니다. **이 칸에 값이 있는 곡만** Spotify에 추가됩니다. |
| `spotify_title` / `spotify_artist` | 찾은 곡의 제목과 아티스트입니다. 원래 곡과 같은지 비교하세요. |
| `score` | 일치 정도(0~1)입니다. 낮은 곡부터 확인하세요. |

- **못 찾은 곡**(`spotify_uri`가 빈 곡): Spotify 앱에서 그 곡을 찾아 **공유 → 곡 링크 복사**를 누르고, 복사한 링크(`https://open.spotify.com/track/...`)를 그 칸에 붙여 넣습니다.
- **잘못 찾은 곡**: `spotify_uri` 칸을 올바른 링크로 바꾸거나 비웁니다.
- 저장은 엑셀 기본 형식(`CSV (쉼표로 분리)`)으로 해도 됩니다. **`.xlsx`로 바꿔 저장하지는 마세요.**

> ⚠️ `match`를 다시 실행하면 `match.csv`를 **새로 덮어씁니다**. 엑셀에서 고친 내용이 사라질 수 있으니, 고친 뒤에 다시 매칭할 일이 있으면 `-o output\match2.csv`처럼 다른 이름으로 저장하세요.

---

## 5. `push` — Spotify에 플레이리스트 만들기

먼저 미리보기를 합니다. 실제로는 아무것도 만들지 않습니다.
```powershell
python -m playlist_extractor push output\match.csv --dry-run
```
문제가 없으면 실제로 생성합니다.
```powershell
python -m playlist_extractor push output\match.csv --prefix "[VIBE] "
```

**옵션**

| 옵션 | 설명 |
|---|---|
| `--dry-run` | 실제로 만들지 않고 "어떤 플레이리스트에 몇 곡 추가 예정"만 출력합니다. |
| `--prefix "글자"` | Spotify 플레이리스트 이름 앞에 붙입니다. 예: `[VIBE] 운동` |
| `--only "이름1" "이름2"` | 지정한 플레이리스트만 만듭니다. |
| `--public` | 공개 플레이리스트로 만듭니다. 기본은 비공개입니다. |
| `--client-id ID` | 환경변수 대신 Client ID를 직접 넣을 때 씁니다. |

> ⚠️ `push`는 실행할 때마다 플레이리스트를 **새로 만듭니다**. 두 번 실행하면 같은 이름의 플레이리스트가 두 개 생깁니다. 일부만 다시 만들 때는 `--only`를 쓰고, 이미 만든 것은 Spotify 앱에서 지우세요.

---

## 6. 자주 쓰는 조합

**VIBE 전체를 Spotify로**
```powershell
python -m playlist_extractor vibe --overwrite
python -m playlist_extractor match output\vibe.json
python -m playlist_extractor push output\match.csv --prefix "[VIBE] "
```

**벅스 최근 들은 곡만 따로 옮기기**
```powershell
python -m playlist_extractor bugs
python -m playlist_extractor match output\bugs.json --only "최근 들은 곡" -o output\match_bugs.csv
python -m playlist_extractor push output\match_bugs.csv --prefix "[Bugs] "
```

**플레이리스트 하나만 다시 옮기기**
```powershell
python -m playlist_extractor match output\vibe.json --only "국힙&외힙" -o output\match_hiphop.csv
python -m playlist_extractor push output\match_hiphop.csv --prefix "[VIBE] "
```

---

## 7. 파일 위치

| 위치 | 내용 | 지워도 되나요? |
|---|---|---|
| `output\vibe.json`, `output\bugs.json` | 추출한 곡 목록입니다. | 다시 추출할 수 있으면 지워도 됩니다. VIBE는 12/31에 종료되니 **백업을 권장**합니다. |
| `output\match.csv` | 매칭 결과입니다. 엑셀로 수정합니다. | 다시 만들 수 있지만, 직접 고친 내용은 사라집니다. |
| `output\raw_vibe\`, `output\raw_bugs\` | `--dump`로 저장한 원본 데이터입니다. | 지워도 됩니다. |
| `.browser-profile\` | VIBE·벅스 로그인 상태입니다. | 지우면 다음 실행 때 다시 로그인하면 됩니다. |
| `.spotify_token.json` | Spotify 로그인 상태입니다. | 지우면 다음 실행 때 다시 로그인하면 됩니다. |

`.browser-profile`과 `.spotify_token.json`에는 로그인 정보가 들어 있습니다. 다른 사람에게 공유하지 마세요.

---

## 8. 문제 해결

| 증상 | 해결 |
|---|---|
| `Activate.ps1 … 스크립트를 실행할 수 없으므로` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`를 실행하고 `Y`를 입력합니다. |
| `neither 'setup.py' nor 'pyproject.toml' found` | 프로그램 폴더가 아닌 곳에서 실행한 것입니다. 0번의 `cd`부터 다시 하세요. |
| `No module named ...` (예: `'playwright'`) | 가상환경이 꺼져 있습니다. `.venv\Scripts\Activate.ps1`을 실행하세요. |
| `Spotify Client ID가 필요합니다` | `$env:SPOTIFY_CLIENT_ID="..."`를 입력합니다. PowerShell을 새로 열 때마다 다시 넣어야 합니다. |
| Spotify 인증 실패 / `INVALID_CLIENT: Invalid redirect URI` | Spotify 앱 설정의 리디렉션 URI가 정확히 `http://127.0.0.1:8888/callback`인지 확인하세요. |
| Spotify 로그인을 다른 계정으로 바꾸고 싶음 | `.spotify_token.json`을 지우고 다시 실행합니다. |
| 네이버·벅스 로그인이 막힘 | `--chrome` 옵션을 붙여 실행합니다. |
| "이 페이지에서 곡을 찾지 못했습니다" | `--dump`로 실행한 뒤 `output\raw_vibe` 또는 `output\raw_bugs`에서 가장 최근 `..._page.html` 파일을 공유해 주세요. |
| 새 버전을 받았는데 반영이 안 됨 | 실행 중인 추출 창을 `q`로 끝내고 다시 실행합니다. 재설치나 PowerShell 재시작은 필요 없습니다. |

지금까지 나온 이슈와 해결 과정은 [docs/ISSUES.md](ISSUES.md)에 기록되어 있습니다.
