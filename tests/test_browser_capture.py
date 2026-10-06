"""로컬 가짜 사이트로 브라우저 수집 흐름(응답 가로채기 + 무한 스크롤 + Enter/q 입력)을 검증한다."""

import builtins
import http.server
import json
import threading
import time
from pathlib import Path

import pytest

from playlist_extractor import browser, vibe

FIXTURES = Path(__file__).parent / "fixtures"

PAGE = """<!doctype html><html><head><title>출근길 플리 - VIBE</title></head>
<body><div id="list" style="height:300px;overflow-y:auto"><div id="rows"></div></div>
<script>
let page = 0;
async function load() {
  const r = await fetch('/api/vibe/mylist/12345/tracks?start=' + (page * 2 + 1));
  const data = await r.json();
  for (const t of data.tracks) {
    const d = document.createElement('div'); d.style.height = '200px'; d.textContent = t.trackTitle;
    document.getElementById('rows').appendChild(d);
  }
  page++;
}
fetch('/api/vibe/recommend');
load();
document.getElementById('list').addEventListener('scroll', e => {
  const el = e.target;
  if (page < 3 && el.scrollTop + el.clientHeight >= el.scrollHeight - 5) load();
});
</script></body></html>"""

ALL_TRACKS = [
    {"trackId": i, "trackTitle": f"곡{i}", "artists": [{"artistName": f"가수{i}"}], "album": {"albumTitle": "앨범"}}
    for i in range(1, 7)
]


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path.startswith("/mylist/12345"):
            body, ctype = PAGE.encode(), "text/html; charset=utf-8"
        elif self.path.startswith("/api/vibe/mylist/12345/tracks"):
            start = int(self.path.split("start=")[1])
            body = json.dumps({"tracks": ALL_TRACKS[start - 1 : start + 1]}).encode()
            ctype = "application/json"
        elif self.path.startswith("/api/vibe/recommend"):
            body = (FIXTURES / "vibe_playlist.json").read_bytes()
            ctype = "application/json"
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_interactive_capture_collects_all_pages(server, tmp_path, monkeypatch):
    inputs = iter(["", "q"])

    def fake_input(*_):
        time.sleep(2)
        try:
            return next(inputs)
        except StopIteration:
            raise EOFError

    monkeypatch.setattr(builtins, "input", fake_input)
    playlists = browser.interactive_capture(
        start_url=f"{server}/mylist/12345",
        profile_dir=tmp_path / "profile",
        collector=vibe._collect,
        response_filter=lambda url: "/api/vibe/" in url,
        dump_dir=tmp_path / "dump",
        headless=True,
    )
    assert len(playlists) == 1
    pl = playlists[0]
    assert pl.name == "출근길 플리"
    # 추천곡(밤편지 등)은 제외되고 스크롤로 불러온 6곡이 순서대로 모여야 한다
    assert [t.title for t in pl.tracks] == [f"곡{i}" for i in range(1, 7)]
    assert any(p.suffix == ".html" for p in (tmp_path / "dump").iterdir())
