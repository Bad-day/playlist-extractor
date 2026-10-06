import time

from playlist_extractor.spotify import SpotifyClient


class FakeResp:
    def __init__(self, status, data=None, headers=None):
        self.status_code = status
        self._data = data or {}
        self.headers = headers or {}
        self.content = b"x" if data is not None else b""
        self.text = str(data)
        self.url = ""
        self.request = type("R", (), {"method": "POST"})()

    def json(self):
        return self._data


def make_client(tmp_path, responder):
    c = SpotifyClient("cid", tmp_path / "token.json")
    c._token = {"access_token": "t", "refresh_token": "r", "expires_at": time.time() + 3600}
    calls = []

    def request(method, url, **kw):
        calls.append((method, url.replace("https://api.spotify.com/v1", ""), kw.get("json")))
        return responder(method, calls[-1][1])

    c.session.request = request
    return c, calls


def test_add_items_uses_items_endpoint_in_chunks(tmp_path):
    c, calls = make_client(tmp_path, lambda m, p: FakeResp(201, {"snapshot_id": "s"}))
    c.add_items("pl", [f"spotify:track:{i}" for i in range(205)])
    assert [(p, len(j["uris"])) for _, p, j in calls] == [
        ("/playlists/pl/items", 100), ("/playlists/pl/items", 100), ("/playlists/pl/items", 5),
    ]


def test_create_playlist_falls_back_to_user_endpoint(tmp_path):
    def responder(method, path):
        if path == "/me/playlists":
            return FakeResp(404, {"error": "nf"})
        if path == "/me":
            return FakeResp(200, {"id": "me123"})
        return FakeResp(201, {"id": "new"})

    c, calls = make_client(tmp_path, responder)
    assert c.create_playlist("x")["id"] == "new"
    assert [p for _, p, _ in calls] == ["/me/playlists", "/me", "/users/me123/playlists"]


def test_retries_after_rate_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)
    seq = iter([FakeResp(429, {}, {"Retry-After": "1"}), FakeResp(200, {"tracks": {"items": [{"name": "a"}]}})])
    c, calls = make_client(tmp_path, lambda m, p: next(seq))
    assert c.search_tracks("q") == [{"name": "a"}]
    assert c.search_tracks("q") == [{"name": "a"}]  # 캐시
    assert len(calls) == 2


def test_search_uses_explicit_market(tmp_path):
    params = []

    def responder(method, path):
        return FakeResp(200, {"tracks": {"items": []}})

    c, calls = make_client(tmp_path, responder)
    orig = c.session.request

    def request(method, url, **kw):
        params.append(kw.get("params"))
        return orig(method, url, **kw)

    c.session.request = request
    c.search_tracks("q")
    assert params[0]["market"] == "KR"


def test_login_reuses_token_with_all_scopes(tmp_path):
    import json

    from playlist_extractor import spotify

    token_path = tmp_path / "token.json"
    token_path.write_text(json.dumps({"access_token": "t", "refresh_token": "r", "scope": spotify.SCOPES}))
    c = SpotifyClient("cid", token_path)
    c.login()
    assert c._token["access_token"] == "t"


def test_login_again_when_saved_token_lacks_new_scope(tmp_path, monkeypatch):
    import json

    import pytest

    from playlist_extractor import spotify

    token_path = tmp_path / "token.json"
    old_scopes = "playlist-modify-private playlist-modify-public playlist-read-private"
    token_path.write_text(json.dumps({"access_token": "old", "refresh_token": "r", "scope": old_scopes}))
    opened = []
    monkeypatch.setattr(spotify.webbrowser, "open", lambda url: opened.append(url))

    def stop(*_):
        raise spotify.SpotifyError("stop")

    monkeypatch.setattr(spotify, "_wait_for_code", stop)
    with pytest.raises(spotify.SpotifyError):
        SpotifyClient("cid", token_path).login()
    assert not token_path.exists()
    assert "user-read-private" in opened[0]


def test_requests_korean_names(tmp_path):
    seen = []
    c, calls = make_client(tmp_path, lambda m, p: FakeResp(200, {"tracks": {"items": []}}))
    orig = c.session.request

    def request(method, url, **kw):
        seen.append(kw["headers"])
        return orig(method, url, **kw)

    c.session.request = request
    c.search_tracks("q")
    assert seen[0]["Accept-Language"].startswith("ko")
