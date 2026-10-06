"""벅스 '내 앨범' 추출.

벅스는 곡 목록을 서버에서 HTML 표로 그려서 내려준다(곡마다 `<tr rowtype="track" trackid=...>`).
로그인된 브라우저에서 페이지를 열고 HTML을 파싱한다.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup, Tag
from playwright.sync_api import Page

from .browser import CapturedResponse, interactive_capture
from .models import Playlist, Track

START_URL = "https://music.bugs.co.kr/user/library"

GUIDE = """
=== 벅스 추출 ===
1. 열린 브라우저에서 벅스 로그인 (최초 1회, 이후 로그인 유지)
2. 내 앨범 목록에서 옮길 앨범을 클릭해 곡 목록 페이지를 연다
3. 터미널로 돌아와 Enter → 곡 목록 수집
   (곡이 여러 페이지로 나뉘어 있으면 페이지를 넘길 때마다 Enter → 같은 앨범으로 합쳐짐)
4. 다른 앨범도 2~3 반복, 다 끝나면 q + Enter
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


def _collect(page: Page, _responses: list[CapturedResponse]) -> Optional[Playlist]:
    html = page.content()
    return Playlist(name=_playlist_name(page, html), source="bugs", url=page.url, tracks=parse_tracks(html))


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
