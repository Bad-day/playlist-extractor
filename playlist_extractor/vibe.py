"""네이버 VIBE 보관함 추출.

VIBE 웹(vibe.naver.com)은 apis.naver.com/vibeWeb/... 내부 API로 곡 목록을 받아온다.
엔드포인트 경로는 공개 문서가 없고 바뀔 수 있으므로 특정 URL에 의존하지 않고,
브라우저가 받은 JSON/XML 응답을 훑어 `trackTitle` 필드를 가진 객체를 곡으로 인식한다.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterator, Optional
from urllib.parse import urlparse

from playwright.sync_api import Page

from .browser import CapturedResponse, interactive_capture
from .models import Playlist, Track

START_URL = "https://vibe.naver.com/library/playlists"

GUIDE = """
=== VIBE 추출 ===
1. 열린 브라우저에서 네이버 로그인 (최초 1회, 이후 로그인 유지)
2. 보관함 > 플레이리스트 에서 옮길 플레이리스트를 클릭해 상세 페이지를 연다
3. 터미널로 돌아와 Enter → 자동 스크롤 후 곡 목록 수집
4. 다른 플레이리스트도 2~3 반복 ('좋아요한 노래' 페이지도 같은 방법으로 가능)
5. 다 끝나면 q + Enter
"""


def is_vibe_api(url: str) -> bool:
    host = urlparse(url).netloc
    return "naver.com" in host and "vibe" in url.lower()


# ---------------------------------------------------------------------------
# 응답 파싱
# ---------------------------------------------------------------------------

def _xml_to_obj(el: ET.Element) -> Any:
    children = list(el)
    if not children:
        return (el.text or "").strip()
    out: dict[str, Any] = {}
    for child in children:
        value = _xml_to_obj(child)
        if child.tag in out:
            if not isinstance(out[child.tag], list):
                out[child.tag] = [out[child.tag]]
            out[child.tag].append(value)
        else:
            out[child.tag] = value
    return out


def parse_body(body: str) -> Any:
    text = body.lstrip()
    if text.startswith("//"):  # dump 파일 첫 줄 주석
        text = text.split("\n", 1)[1] if "\n" in text else ""
    text = text.lstrip()
    if text.startswith("<"):
        try:
            return _xml_to_obj(ET.fromstring(text))
        except ET.ParseError:
            return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def _as_list(v: Any) -> list:
    if v is None or v == "":
        return []
    return v if isinstance(v, list) else [v]


def _artist_names(raw: Any) -> list[str]:
    # JSON: [{"artistName": ...}], XML 변환: {"artist": [{...}] 또는 {...}}
    if isinstance(raw, dict) and "artist" in raw:
        raw = raw["artist"]
    names = []
    for a in _as_list(raw):
        if isinstance(a, dict):
            name = a.get("artistName") or a.get("name")
        else:
            name = a
        if name and str(name).strip():
            names.append(str(name).strip())
    return names


def _track_from_obj(obj: dict) -> Optional[Track]:
    title = obj.get("trackTitle")
    if not isinstance(title, str) or not title.strip():
        return None
    album = obj.get("album")
    album_title = ""
    if isinstance(album, dict):
        album_title = album.get("albumTitle") or album.get("title") or ""
    elif isinstance(obj.get("albumTitle"), str):
        album_title = obj["albumTitle"]
    artists = _artist_names(obj.get("artists")) or _artist_names(obj.get("artist"))
    if not artists and isinstance(obj.get("artistName"), str):
        artists = [obj["artistName"]]
    return Track(
        title=title.strip(),
        artists=artists,
        album=str(album_title).strip(),
        source_id=str(obj.get("trackId", "")),
    )


def iter_tracks(obj: Any) -> Iterator[Track]:
    """임의의 JSON 구조에서 곡 객체를 등장 순서대로 찾는다."""
    if isinstance(obj, dict):
        track = _track_from_obj(obj)
        if track:
            yield track
            return
        for v in obj.values():
            yield from iter_tracks(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from iter_tracks(v)


def _dedupe(tracks: list[Track]) -> list[Track]:
    seen, out = set(), []
    for t in tracks:
        key = t.source_id or (t.title, tuple(t.artists))
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out


def page_ids(page_url: str) -> list[str]:
    """플레이리스트 페이지 URL에서 식별자로 보이는 경로 조각(숫자 포함 4자 이상)을 뽑는다."""
    segments = urlparse(page_url).path.strip("/").split("/")
    return [s for s in segments if len(s) >= 4 and re.search(r"\d", s)]


def tracks_from_responses(responses: list[CapturedResponse], page_url: str) -> tuple[list[Track], bool]:
    """곡 목록과, 페이지 ID로 응답을 특정했는지 여부를 돌려준다.

    한 페이지에는 추천곡 등 다른 곡 목록 응답도 섞이므로,
    URL에 플레이리스트 ID가 들어간 응답이 있으면 그것만 쓴다.
    """
    ids = page_ids(page_url)
    matched: list[Track] = []
    others: list[Track] = []
    for r in responses:
        tracks = list(iter_tracks(parse_body(r.body)))
        if not tracks:
            continue
        if ids and any(i in r.url for i in ids):
            matched.extend(tracks)
        else:
            others.extend(tracks)
    if matched:
        return _dedupe(matched), True
    return _dedupe(others), False


def _playlist_name(page: Page) -> str:
    title = re.sub(r"\s*[-|:]\s*VIBE.*$", "", page.title() or "", flags=re.I).strip()
    if title and title.upper() != "VIBE":
        return title
    for sel in ("h2", "h3", "h1"):
        el = page.query_selector(sel)
        if el and el.inner_text().strip():
            return el.inner_text().strip().splitlines()[0]
    return page.url


def _collect(page: Page, responses: list[CapturedResponse]) -> Optional[Playlist]:
    tracks, exact = tracks_from_responses(responses, page.url)
    if tracks and not exact:
        print("※ 이 페이지 전용 응답을 특정하지 못해 받은 곡 목록을 모두 합쳤습니다. 추천곡이 섞였는지 확인하세요.")
    return Playlist(name=_playlist_name(page), source="vibe", url=page.url, tracks=tracks)


def extract(profile_dir: Path, dump_dir: Optional[Path] = None, channel: Optional[str] = None) -> list[Playlist]:
    return interactive_capture(
        start_url=START_URL,
        profile_dir=profile_dir,
        collector=_collect,
        response_filter=is_vibe_api,
        dump_dir=dump_dir,
        channel=channel,
        guide=GUIDE,
    )
