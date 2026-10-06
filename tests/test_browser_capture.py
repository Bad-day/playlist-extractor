"""로컬 가짜 VIBE 사이트로 브라우저 수집 흐름(응답 가로채기, 무한 스크롤, 보관함 순회, Enter/q 입력)을 검증한다."""

import builtins
import http.server
import json
import threading
import time

import pytest

from playlist_extractor import browser, vibe

GENERIC_TITLE = "보관함 > 플레이리스트 VIBE(바이브)"

PLAYLISTS = {
    "74895567": ("운동", [("Warriors", "Imagine Dragons"), ("Legend", "The Score")]),
    "74895566": ("☠️", [("RAVE", "Dxrk"), ("MONTAGEM COMA", "Mustafa Atarer"), ("DIA DELÍCIA", "Nakama"),
                    ("PASSO BEM SOLTO", "EmCee.A"), ("Brasuk", "Brasuk Beat")]),
    "74895565": ("기본 리스트", []),
    # 화면이 첫 페이지(2곡)만 불러오고 멈추는 플레이리스트 → API 페이지를 직접 이어서 요청해야 한다
    "74895550": ("국힙&외힙", [(f"힙합{i}", "가수") for i in range(1, 6)]),
}


def track_obj(pid, i, title, artist):
    return {"trackId": int(pid) * 100 + i, "trackTitle": title, "artists": [{"artistName": artist}],
            "album": {"albumTitle": title}}


def tracks_of(pid):
    return [track_obj(pid, i, t, a) for i, (t, a) in enumerate(PLAYLISTS[pid][1])]


# 보관함 화면: 실제 VIBE처럼 모든 플레이리스트의 곡이 담긴 응답을 받고, 카드마다 표지 링크 + 이름을 그린다.
# 74895566번 카드는 링크에 글자가 없고 이름이 바깥 요소에 있다.
LIBRARY = f"""<!doctype html><html><head><title>{GENERIC_TITLE}</title></head><body>
<h2>보관함</h2>
<div class="card"><a href="/mylist/74895567"><img alt=""></a><a href="/mylist/74895567">운동</a><span>2곡</span></div>
<div class="card"><a href="/mylist/74895566"><img alt=""></a><div><p>☠️</p><p>5곡</p></div></div>
<div class="card"><a href="/mylist/74895565"><img alt=""></a><div><p>기본 리스트</p><p>0곡</p></div></div>
<div class="card"><a href="/mylist/74895550"><img alt=""></a><a href="/mylist/74895550">국힙&amp;외힙</a><span>5곡</span></div>
<script>fetch('/api/vibe/library/mylists');</script>
</body></html>"""

# 플레이리스트 상세 화면: 제목은 일반 문구, 곡은 스크롤할 때마다 2곡씩 불러온다. 추천곡 응답도 섞인다.
DETAIL = """<!doctype html><html><head><title>%s</title></head>
<body><div id="list" style="height:300px;overflow-y:auto"><div id="rows"></div></div>
<script>
const pid = location.pathname.split('/').pop();
let start = 1, done = false;
async function load() {
  if (done) return;
  const r = await fetch(`/api/vibe/mylist/${pid}/tracks?start=${start}&display=2`);
  const data = await r.json();
  const tracks = data.response.result.tracks;
  if (tracks.length < 2) done = true;
  for (const t of tracks) {
    const d = document.createElement('div'); d.style.height = '200px'; d.textContent = t.trackTitle;
    document.getElementById('rows').appendChild(d);
  }
  start += 2;
}
fetch('/api/vibe/recommend/tracks');
load();
document.getElementById('list').addEventListener('scroll', e => {
  const el = e.target;
  if (pid !== '74895550' && el.scrollTop + el.clientHeight >= el.scrollHeight - 5) load();
});
</script></body></html>""" % GENERIC_TITLE


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        path, _, query = self.path.partition("?")
        params = dict(p.split("=") for p in query.split("&") if "=" in p)
        if path == "/library/playlists":
            self._send(LIBRARY, "text/html; charset=utf-8")
        elif path.startswith("/mylist/"):
            self._send(DETAIL, "text/html; charset=utf-8")
        elif path == "/api/vibe/library/mylists":
            mylists = [{"mylistId": int(pid), "mylistName": name, "tracks": tracks_of(pid)}
                       for pid, (name, _) in PLAYLISTS.items()]
            self._send(json.dumps({"response": {"result": {"mylists": mylists}}}), "application/json")
        elif path.startswith("/api/vibe/mylist/"):
            pid = path.split("/")[4]
            start = int(params.get("start", 1))
            page = tracks_of(pid)[start - 1 : start + 1]
            body = {"response": {"result": {"mylist": {"mylistId": int(pid), "mylistName": PLAYLISTS[pid][0]},
                                            "trackTotalCount": len(PLAYLISTS[pid][1]), "tracks": page}}}
            self._send(json.dumps(body), "application/json")
        elif path == "/api/vibe/recommend/tracks":
            self._send(json.dumps({"tracks": [track_obj("9999", 0, "추천곡", "누군가")]}), "application/json")
        else:
            self.send_response(404)
            self.end_headers()

    def _send(self, body, ctype):
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def run_capture(start_url, tmp_path, monkeypatch, keys=("", "q")):
    inputs = iter(keys)

    def fake_input(*_):
        time.sleep(2)
        try:
            return next(inputs)
        except StopIteration:
            raise EOFError

    monkeypatch.setattr(builtins, "input", fake_input)
    return browser.interactive_capture(
        start_url=start_url,
        profile_dir=tmp_path / "profile",
        collector=vibe._collect,
        response_filter=lambda url: "/api/vibe/" in url,
        dump_dir=tmp_path / "dump",
        headless=True,
    )


def titles(playlist):
    return [t.title for t in playlist.tracks]


def test_library_page_collects_each_playlist_separately(server, tmp_path, monkeypatch):
    playlists = run_capture(f"{server}/library/playlists", tmp_path, monkeypatch)
    assert [(p.name, titles(p)) for p in playlists] == [
        ("운동", ["Warriors", "Legend"]),
        ("☠️", ["RAVE", "MONTAGEM COMA", "DIA DELÍCIA", "PASSO BEM SOLTO", "Brasuk"]),
        ("국힙&외힙", [f"힙합{i}" for i in range(1, 6)]),
    ]
    assert playlists[0].url.endswith("/mylist/74895567")
    assert any(p.suffix == ".html" for p in (tmp_path / "dump").iterdir())


def test_detail_page_uses_only_that_playlist(server, tmp_path, monkeypatch):
    playlists = run_capture(f"{server}/mylist/74895566", tmp_path, monkeypatch)
    assert len(playlists) == 1
    # 이름은 페이지 제목(일반 문구)이 아니라 응답의 플레이리스트 정보에서 가져온다
    assert playlists[0].name == "☠️"
    assert titles(playlists[0]) == ["RAVE", "MONTAGEM COMA", "DIA DELÍCIA", "PASSO BEM SOLTO", "Brasuk"]
