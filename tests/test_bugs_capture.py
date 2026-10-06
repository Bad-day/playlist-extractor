"""로컬 가짜 벅스 '최근 들은 곡' 페이지로 여러 페이지 자동 수집을 검증한다."""

import builtins
import http.server
import threading
import time

import pytest

from playlist_extractor import browser, bugs

PER_PAGE = 2
TOTAL = 9  # 5페이지 (마지막 페이지 1곡)
GROUP = 2  # 페이지 번호를 2개씩 보여 주고 나머지는 '다음' 버튼으로


def row(i):
    return (
        f'<tr rowtype="track" trackid="{1000 + i}">'
        f'<th><p class="title"><a href="/track/{1000 + i}" title="곡{i}">곡{i}</a></p></th>'
        f'<td><p class="artist"><a href="/artist/1">가수{i}</a></p></td>'
        f'<td><a class="album" title="앨범{i}">앨범{i}</a></td></tr>'
    )


def render(page_no):
    last = (TOTAL + PER_PAGE - 1) // PER_PAGE
    start = (page_no - 1) * PER_PAGE + 1
    rows = "".join(row(i) for i in range(start, min(start + PER_PAGE, TOTAL + 1)))
    group_start = (page_no - 1) // GROUP * GROUP + 1
    links = []
    if group_start > 1:
        links.append(f'<a class="prev" href="/recent?page={group_start - 1}">이전</a>')
    for n in range(group_start, min(group_start + GROUP, last + 1)):
        links.append(f"<strong>{n}</strong>" if n == page_no else f'<a href="/recent?page={n}">{n}</a>')
    if group_start + GROUP <= last:
        links.append(f'<a class="next" href="/recent?page={group_start + GROUP}">다음</a>')
    return (
        "<!doctype html><html><head><title>최근 들은 곡 - 벅스</title></head><body>"
        f'<table class="list trackList"><tbody>{rows}</tbody></table>'
        f'<div class="paging">{"".join(links)}</div></body></html>'
    )


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        path, _, query = self.path.partition("?")
        if path != "/recent":
            self.send_response(404)
            self.end_headers()
            return
        page_no = int(query.split("page=")[1]) if "page=" in query else 1
        data = render(page_no).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
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


def run_capture(start_url, tmp_path, monkeypatch):
    inputs = iter(["", "q"])

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
        collector=bugs._collect,
        headless=True,
    )


@pytest.mark.parametrize("start_page", [1, 3])
def test_recent_tracks_collects_every_page(server, tmp_path, monkeypatch, start_page):
    playlists = run_capture(f"{server}/recent?page={start_page}", tmp_path, monkeypatch)
    assert len(playlists) == 1
    assert playlists[0].name == "최근 들은 곡"
    assert [t.title for t in playlists[0].tracks] == [f"곡{i}" for i in range(1, TOTAL + 1)]
    assert playlists[0].tracks[0].artists == ["가수1"]
