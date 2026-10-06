"""사용자 PC에서 실제 브라우저를 띄워 로그인 상태로 페이지를 읽어오는 공통 로직.

VIBE·벅스 모두 공개 API가 없고 '내 보관함'은 로그인해야만 보이므로,
사용자가 직접 로그인/페이지 이동을 하고 도구는 그 사이 오가는 응답과 화면을 수집한다.
"""

from __future__ import annotations

import os
import queue
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from playwright.sync_api import BrowserContext, Error as PlaywrightError, Page, Response, sync_playwright

from .models import Playlist

CAPTURE_CONTENT_TYPES = ("json", "xml", "javascript")

# 스크롤 가능한 모든 영역(window + overflow 컨테이너)을 끝까지 내린다. 무한 스크롤 로딩용.
_SCROLL_JS = """
() => {
  const els = [document.scrollingElement || document.documentElement];
  for (const el of document.querySelectorAll('*')) {
    const s = getComputedStyle(el);
    if ((s.overflowY === 'auto' || s.overflowY === 'scroll') && el.scrollHeight > el.clientHeight + 10) {
      els.push(el);
    }
  }
  let total = 0;
  for (const el of els) { el.scrollTop = el.scrollHeight; total += el.scrollHeight; }
  return total;
}
"""


@dataclass
class CapturedResponse:
    url: str
    content_type: str
    body: str


class CaptureLog:
    """이번 실행 동안 받은 응답 전체. 수집기는 이전 Enter 이후(since_mark) 또는 전체(history)를 본다."""

    def __init__(self) -> None:
        self.history: list[CapturedResponse] = []
        self.mark = 0

    def since(self, index: int) -> list[CapturedResponse]:
        return self.history[index:]

    def since_mark(self) -> list[CapturedResponse]:
        return self.since(self.mark)


# 한 번의 Enter로 여러 플레이리스트를 돌려줄 수 있다 (예: VIBE 보관함 목록 전체 순회)
Collector = Callable[[Page, CaptureLog], list[Playlist]]


def auto_scroll(page: Page, max_rounds: int = 80, pause_ms: int = 700) -> None:
    """높이 변화가 없어질 때까지 스크롤해 지연 로딩되는 곡 목록을 모두 불러온다."""
    last, stable = -1, 0
    for _ in range(max_rounds):
        height = page.evaluate(_SCROLL_JS)
        page.wait_for_timeout(pause_ms)
        if height == last:
            stable += 1
            if stable >= 3:
                break
        else:
            stable = 0
        last = height


def merge_playlist(playlists: list[Playlist], new: Playlist) -> list[Playlist]:
    """같은 URL을 다시 수집하면 교체하고, 쿼리만 다른 같은 페이지(벅스 ?page=2 등)면 곡을 이어 붙인다."""
    out: list[Playlist] = []
    merged = False
    for p in playlists:
        if p.url == new.url:
            continue
        if not merged and p.source == new.source and _base_url(p.url) == _base_url(new.url):
            keys = {t.source_id for t in p.tracks if t.source_id}
            p.tracks += [t for t in new.tracks if not t.source_id or t.source_id not in keys]
            merged = True
        out.append(p)
    if not merged:
        out.append(new)
    return out


def _base_url(url: str) -> str:
    return url.split("?", 1)[0].split("#", 1)[0]


def _stdin_reader(commands: "queue.Queue[str]") -> None:
    while True:
        try:
            commands.put(input())
        except EOFError:
            commands.put("q")
            return


def _active_page(context: BrowserContext) -> Optional[Page]:
    pages = [p for p in context.pages if not p.is_closed()]
    return pages[-1] if pages else None


def interactive_capture(
    *,
    start_url: str,
    profile_dir: Path,
    collector: Collector,
    response_filter: Callable[[str], bool] = lambda url: True,
    dump_dir: Optional[Path] = None,
    channel: Optional[str] = None,
    guide: str = "",
    headless: bool = False,
) -> list[Playlist]:
    """브라우저를 띄우고, 사용자가 Enter를 누를 때마다 현재 페이지에서 플레이리스트를 수집한다."""
    profile_dir.mkdir(parents=True, exist_ok=True)
    if dump_dir:
        dump_dir.mkdir(parents=True, exist_ok=True)

    playlists: list[Playlist] = []
    log = CaptureLog()
    dump_seq = [0]

    def on_response(resp: Response) -> None:
        if not response_filter(resp.url):
            return
        ctype = resp.headers.get("content-type", "")
        if not any(t in ctype for t in CAPTURE_CONTENT_TYPES):
            return
        try:
            body = resp.text()
        except PlaywrightError:
            return
        log.history.append(CapturedResponse(resp.url, ctype, body))
        if dump_dir:
            dump_seq[0] += 1
            ext = "xml" if "xml" in ctype else "json"
            name = re.sub(r"[^A-Za-z0-9]+", "_", resp.url.split("?")[0])[-80:]
            (dump_dir / f"{dump_seq[0]:04d}_{name}.{ext}").write_text(
                f"// {resp.url}\n{body}", encoding="utf-8"
            )

    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            str(profile_dir),
            headless=headless,
            channel=channel,
            # 이미 설치된 Chromium을 쓰고 싶을 때 (예: playwright install 없이)
            executable_path=os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE") or None,
            viewport=None,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context.on("response", on_response)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(start_url)

        print(guide)
        print("\n[Enter] 현재 페이지 수집   [q + Enter] 종료 및 저장\n")

        commands: "queue.Queue[str]" = queue.Queue()
        threading.Thread(target=_stdin_reader, args=(commands,), daemon=True).start()

        while True:
            page = _active_page(context)
            if page is None:
                print("브라우저가 닫혀 종료합니다.")
                break
            try:
                cmd = commands.get_nowait().strip().lower()
            except queue.Empty:
                # Playwright 이벤트(응답 수집)가 계속 처리되도록 대기는 브라우저 쪽에서 한다.
                try:
                    page.wait_for_timeout(300)
                except PlaywrightError:
                    pass
                continue

            if cmd == "q":
                break
            try:
                print("스크롤하며 곡 목록을 불러오는 중...")
                auto_scroll(page)
                if dump_dir:
                    dump_seq[0] += 1
                    (dump_dir / f"{dump_seq[0]:04d}_page.html").write_text(
                        f"<!-- {page.url} -->\n{page.content()}", encoding="utf-8"
                    )
                collected = collector(page, log)
            except PlaywrightError as e:
                print(f"수집 실패: {e}")
                continue
            log.mark = len(log.history)
            collected = [p for p in collected if p.tracks]
            if not collected:
                print("이 페이지에서 곡을 찾지 못했습니다. 플레이리스트 상세 페이지에서 다시 시도하세요.")
                continue
            for playlist in collected:
                playlists = merge_playlist(playlists, playlist)
                print(f"✔ '{playlist.name}' {len(playlist.tracks)}곡 수집")
                for t in playlist.tracks[:3]:
                    print(f"    - {t.title} / {t.artist}")
                if len(playlist.tracks) > 3:
                    print("    ...")
            print(f"(누적 {len(playlists)}개 플레이리스트)  다른 페이지에서 Enter, 끝내려면 q + Enter")

        context.close()
    return playlists
