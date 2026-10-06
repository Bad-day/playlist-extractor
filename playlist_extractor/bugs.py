"""벅스 '내 앨범' / '최근 들은 곡' 등 곡 목록 페이지 추출.

벅스는 곡 목록을 서버에서 HTML 표로 그려서 내려준다(곡마다 `<tr rowtype="track" trackid=...>`).
로그인된 브라우저에서 페이지를 열고 HTML을 파싱한다. 목록이 1, 2, 3 … 페이지로 나뉘어 있으면
페이지 번호(와 '다음' 버튼)를 차례로 눌러 끝까지 모은다.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup, Tag
from playwright.sync_api import Error as PlaywrightError, Page

from .browser import CaptureLog, interactive_capture
from .models import Playlist, Track

# 보관함 주소는 확인되지 않아(존재하지 않는 페이지가 열림) 벅스 홈에서 시작한다
START_URL = "https://music.bugs.co.kr/"

GUIDE = """
=== 벅스 추출 ===
1. 열린 브라우저에서 벅스 로그인 (최초 1회, 이후 로그인 유지)
2. 옮길 곡 목록 페이지를 연다
   - 상단 '내 음악' → '내 앨범' → 앨범 클릭
   - 또는 '최근 들은 곡' 등 곡 목록이 보이는 페이지
3. 터미널로 돌아와 Enter → 곡 목록 수집
   (1, 2, 3 … 페이지로 나뉘어 있으면 마지막 페이지까지 자동으로 넘기며 하나로 모음)
4. 다른 페이지도 2~3 반복, 다 끝나면 q + Enter
"""


def _text(el: Optional[Tag]) -> str:
    if el is None:
        return ""
    return (el.get("title") or el.get_text(" ", strip=True) or "").strip()


def _track_rows(soup: BeautifulSoup) -> list[Tag]:
    rows = soup.select('tr[rowtype="track"]')
    if not rows:
        rows = soup.select("tr[trackid]")
    return rows


def parse_tracks(html: str) -> list[Track]:
    soup = BeautifulSoup(html, "html.parser")
    tracks: list[Track] = []
    seen: set[str] = set()
    for row in _track_rows(soup):
        title = _text(row.select_one("p.title a")) or _text(row.select_one("p.title"))
        if not title:
            continue
        artist_links = row.select("p.artist a:not(.more)")
        artists = [a.get_text(strip=True) for a in artist_links if a.get_text(strip=True)]
        if not artists:
            artist_text = _text(row.select_one("p.artist"))
            artists = [artist_text] if artist_text else []
        track_id = row.get("trackid", "")
        if track_id and track_id in seen:
            continue
        seen.add(track_id)
        tracks.append(
            Track(
                title=title,
                artists=list(dict.fromkeys(artists)),
                album=_text(row.select_one("a.album")),
                source_id=str(track_id),
            )
        )
    return tracks


def _playlist_name(page: Page, html: str) -> str:
    title = re.sub(r"\s*[-|:]\s*(벅스|Bugs).*$", "", page.title() or "", flags=re.I).strip()
    if title:
        return title
    soup = BeautifulSoup(html, "html.parser")
    h = soup.select_one("header h1, .pgTitle h1, h1")
    return _text(h) or page.url


# 페이지 번호 영역 안의 클릭 가능한 요소
_PAGER_ITEMS = (
    ":is(.paging, .pagination, [class*='paging'], [class*='pagination'], [class*='Paging']) :is(a, button)"
)
_NEXT_GROUP = re.compile(r"^\s*(다음|next|>|›|»)\s*$", re.I)
_PREV_GROUP = re.compile(r"^\s*(처음|맨\s*앞|이전|first|prev(ious)?|<|‹|«)\s*$", re.I)
MAX_PAGES = 200

_FIRST_ID_JS = """
() => {
  const row = document.querySelector('tr[rowtype="track"], tr[trackid]');
  return row ? (row.getAttribute('trackid') || row.innerText.slice(0, 80)) : '';
}
"""


def _first_row(page: Page) -> str:
    try:
        return page.evaluate(_FIRST_ID_JS)
    except PlaywrightError:  # 페이지 이동 중
        return ""


def _click_and_wait(page: Page, target) -> bool:
    """페이지 번호를 누르고 곡 목록이 바뀔 때까지 기다린다. 바뀌면 True."""
    before_url, before_row = page.url, _first_row(page)
    try:
        target.click()
    except PlaywrightError:
        return False
    for _ in range(60):
        page.wait_for_timeout(250)
        row = _first_row(page)
        if row and (row != before_row or page.url != before_url):
            break
    else:
        return False
    try:
        page.wait_for_load_state("domcontentloaded", timeout=10000)
    except PlaywrightError:
        pass
    page.wait_for_timeout(300)
    return True


def _go_to_page(page: Page, number: int) -> bool:
    """number 페이지로 이동. 번호가 안 보이면 '다음' 버튼으로 다음 번호 묶음을 연다."""
    items = page.locator(_PAGER_ITEMS)
    target = items.filter(has_text=re.compile(rf"^\s*{number}\s*$"))
    if target.count():
        return _click_and_wait(page, target.first)
    nxt = items.filter(has_text=_NEXT_GROUP)
    if not nxt.count():
        nxt = page.locator(":is(.paging, .pagination, [class*='paging'], [class*='pagination']) :is(a, button)[class*='next']")
    if not nxt.count():
        return False
    return _click_and_wait(page, nxt.first)


_CURRENT_PAGE_JS = """
() => {
  const pagers = document.querySelectorAll(".paging, .pagination, [class*='paging'], [class*='pagination']");
  for (const pager of pagers) {
    for (const el of pager.querySelectorAll('*')) {
      const text = (el.innerText || '').trim();
      if (!/^\\d+$/.test(text) || el.children.length) continue;
      const cls = (el.className || '').toString() + ' ' + ((el.parentElement && el.parentElement.className) || '').toString();
      if (el.tagName === 'STRONG' || el.getAttribute('aria-current') || /(^|\\s)(on|selected|active|current)(\\s|$)/i.test(cls)) {
        return parseInt(text, 10);
      }
    }
  }
  return 1;
}
"""


def _go_to_first(page: Page) -> bool:
    """1페이지로 돌아간다. 번호 1이 안 보이면 '처음'/'이전' 버튼으로 앞 묶음을 연다."""
    for _ in range(MAX_PAGES):
        items = page.locator(_PAGER_ITEMS)
        first = items.filter(has_text=re.compile(r"^\s*1\s*$"))
        if first.count():
            return _click_and_wait(page, first.first)
        prev = items.filter(has_text=_PREV_GROUP)
        if not prev.count():
            prev = page.locator(
                ":is(.paging, .pagination, [class*='paging'], [class*='pagination']) "
                ":is(a, button):is([class*='first'], [class*='prev'])"
            )
        if not prev.count() or not _click_and_wait(page, prev.first):
            return False
    return False


def collect_all_pages(page: Page) -> list[Track]:
    """1페이지부터 마지막 페이지까지 넘기며 곡을 모은다."""
    if page.locator(_PAGER_ITEMS).count() and page.evaluate(_CURRENT_PAGE_JS) > 1:
        if not _go_to_first(page):
            print("  ※ 1페이지로 돌아가지 못해 지금 페이지부터 모읍니다.")
    tracks = parse_tracks(page.content())
    seen = {t.source_id for t in tracks if t.source_id}
    number = 2
    while number <= MAX_PAGES and page.locator(_PAGER_ITEMS).count():
        if not _go_to_page(page, number):
            break
        new = [t for t in parse_tracks(page.content()) if not t.source_id or t.source_id not in seen]
        if not new:
            break
        seen.update(t.source_id for t in new if t.source_id)
        tracks += new
        print(f"  {number}페이지: {len(new)}곡 (누적 {len(tracks)}곡)")
        number += 1
    return tracks


def _collect(page: Page, _log: CaptureLog) -> list[Playlist]:
    url = page.url
    name = _playlist_name(page, page.content())
    return [Playlist(name=name, source="bugs", url=url, tracks=collect_all_pages(page))]


def extract(profile_dir: Path, dump_dir: Optional[Path] = None, channel: Optional[str] = None) -> list[Playlist]:
    return interactive_capture(
        start_url=START_URL,
        profile_dir=profile_dir,
        collector=_collect,
        response_filter=lambda url: "bugs.co.kr" in url,
        dump_dir=dump_dir,
        channel=channel,
        guide=GUIDE,
    )
