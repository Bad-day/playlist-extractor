"""최소한의 Spotify Web API 클라이언트 (Authorization Code + PKCE).

Client Secret 없이 Client ID만으로 동작한다. 2026년 2월 Web API 변경 사항을 반영해
곡 추가는 `/playlists/{id}/items`, 플레이리스트 생성은 `/me/playlists`를 먼저 쓰고
구 엔드포인트는 404일 때만 대체로 시도한다.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import secrets
import threading
import time
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Any, Optional

import requests

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API = "https://api.spotify.com/v1"
DEFAULT_REDIRECT = "http://127.0.0.1:8888/callback"
# user-read-private: 검색 시 사용자 국가(market)를 쓰려면 필요. 없으면 /search가 403 "Insufficient client scope".
SCOPES = "playlist-modify-private playlist-modify-public playlist-read-private user-read-private"
# 검색할 국가. 사용자 토큰이 있으면 계정 국가가 우선하지만, 명시해 두면 국가 조회 권한 문제를 피할 수 있다.
DEFAULT_MARKET = "KR"
# 곡·아티스트 이름을 한국어 표기로 받는다 (예: 'T.B.H' 대신 '고민중독'). VIBE·벅스 제목과 비교가 쉬워진다.
DEFAULT_LOCALE = "ko-KR,ko;q=0.9,en;q=0.8"


class SpotifyError(RuntimeError):
    pass


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:128]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def _wait_for_code(redirect_uri: str, state: str, timeout: int = 300) -> str:
    parsed = urllib.parse.urlparse(redirect_uri)
    result: dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            result.update({k: v[0] for k, v in qs.items()})
            ok = "code" in result and result.get("state") == state
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            msg = "Spotify 인증 완료. 이 창을 닫고 터미널로 돌아가세요." if ok else "인증 실패. 터미널을 확인하세요."
            self.wfile.write(f"<html><body><h3>{msg}</h3></body></html>".encode())

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer((parsed.hostname, parsed.port or 80), Handler)
    server.timeout = timeout
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    thread.join(timeout)
    server.server_close()
    if result.get("state") != state or "code" not in result:
        raise SpotifyError(f"Spotify 인증 실패: {result.get('error', '응답 없음')}")
    return result["code"]


class SpotifyClient:
    def __init__(
        self, client_id: str, token_path: Path, redirect_uri: str = DEFAULT_REDIRECT, market: str = DEFAULT_MARKET
    ):
        self.client_id = client_id
        self.market = market
        self.locale = os.environ.get("SPOTIFY_LOCALE", DEFAULT_LOCALE)
        self.token_path = token_path
        self.redirect_uri = redirect_uri
        self.session = requests.Session()
        self._token: Optional[dict[str, Any]] = None
        self._search_cache: dict[str, list[dict]] = {}
        self._me: Optional[dict] = None

    # --- 인증 -------------------------------------------------------------
    def _save_token(self, data: dict) -> None:
        if "refresh_token" not in data and self._token:
            data["refresh_token"] = self._token.get("refresh_token")
        data["expires_at"] = time.time() + int(data.get("expires_in", 3600)) - 60
        self._token = data
        self.token_path.write_text(json.dumps(data), encoding="utf-8")
        os.chmod(self.token_path, 0o600)

    def login(self) -> None:
        if self.token_path.exists():
            token = json.loads(self.token_path.read_text(encoding="utf-8"))
            missing = set(SCOPES.split()) - set(str(token.get("scope", "")).split())
            if not missing:
                self._token = token
                return
            # 권한(scope)이 추가된 새 버전이면 예전 토큰으로는 403이 나므로 다시 로그인한다
            print(f"Spotify 권한이 추가되어 다시 로그인합니다: {' '.join(sorted(missing))}")
            self.token_path.unlink()
        verifier, challenge = _pkce_pair()
        state = secrets.token_urlsafe(16)
        url = AUTH_URL + "?" + urllib.parse.urlencode(
            {
                "client_id": self.client_id,
                "response_type": "code",
                "redirect_uri": self.redirect_uri,
                "scope": SCOPES,
                "state": state,
                "code_challenge_method": "S256",
                "code_challenge": challenge,
            }
        )
        print(f"브라우저에서 Spotify 로그인/권한 허용을 진행하세요.\n(자동으로 안 열리면 직접 열기: {url})")
        webbrowser.open(url)
        code = _wait_for_code(self.redirect_uri, state)
        resp = requests.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
                "client_id": self.client_id,
                "code_verifier": verifier,
            },
            timeout=30,
        )
        if resp.status_code != 200:
            raise SpotifyError(f"토큰 발급 실패: {resp.status_code} {resp.text}")
        self._save_token(resp.json())

    def _refresh(self) -> None:
        assert self._token
        resp = requests.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": self._token["refresh_token"],
                "client_id": self.client_id,
            },
            timeout=30,
        )
        if resp.status_code != 200:
            self.token_path.unlink(missing_ok=True)
            raise SpotifyError("토큰 갱신 실패. 다시 실행하면 재로그인합니다.")
        self._save_token(resp.json())

    # --- 요청 -------------------------------------------------------------
    def request(self, method: str, path: str, **kwargs) -> requests.Response:
        if self._token is None:
            self.login()
        for attempt in range(6):
            if time.time() >= self._token.get("expires_at", 0):
                self._refresh()
            headers = {"Authorization": f"Bearer {self._token['access_token']}", "Accept-Language": self.locale}
            resp = self.session.request(method, API + path, headers=headers, timeout=30, **kwargs)
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", "2")) + 1
                print(f"  (요청 제한, {wait}초 대기)")
                time.sleep(wait)
                continue
            if resp.status_code == 401 and attempt == 0:
                self._refresh()
                continue
            if resp.status_code >= 500 and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            return resp
        return resp

    def _json(self, resp: requests.Response) -> Any:
        if resp.status_code >= 400:
            raise SpotifyError(f"{resp.request.method} {resp.url} → {resp.status_code} {resp.text[:300]}")
        return resp.json() if resp.content else {}

    def me(self) -> dict:
        if self._me is None:
            self._me = self._json(self.request("GET", "/me"))
        return self._me

    def search_tracks(self, query: str, limit: int = 10) -> list[dict]:
        if query not in self._search_cache:
            resp = self.request(
                "GET", "/search", params={"q": query, "type": "track", "limit": limit, "market": self.market}
            )
            self._search_cache[query] = self._json(resp).get("tracks", {}).get("items", []) or []
        return self._search_cache[query]

    def create_playlist(self, name: str, description: str = "", public: bool = False) -> dict:
        body = {"name": name, "description": description, "public": public}
        resp = self.request("POST", "/me/playlists", json=body)
        if resp.status_code in (404, 405):
            resp = self.request("POST", f"/users/{self.me()['id']}/playlists", json=body)
        return self._json(resp)

    def add_items(self, playlist_id: str, uris: list[str]) -> None:
        for i in range(0, len(uris), 100):
            chunk = uris[i : i + 100]
            resp = self.request("POST", f"/playlists/{playlist_id}/items", json={"uris": chunk})
            if resp.status_code == 404:
                resp = self.request("POST", f"/playlists/{playlist_id}/tracks", json={"uris": chunk})
            self._json(resp)
