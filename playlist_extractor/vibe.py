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

from playwright.sync_api import Error as PlaywrightError

from .browser import CaptureLog, CapturedResponse, auto_scroll, interactive_capture
from .models import Playlist, Track

START_URL = "https://vibe.naver.com/library/playlists"

GUIDE = """
=== VIBE 추출 ===
1. 열린 브라우저에서 네이버 로그인 (최초 1회, 이후 로그인 유지)
2. 보관함 > 플레이리스트 목록 화면에서 터미널로 돌아와 Enter
   → 목록의 플레이리스트를 하나씩 자동으로 열어 각각 따로 수집
   (특정 플레이리스트만 원하면 그 상세 페이지를 연 상태에서 Enter)
3. 다 끝나면 q + Enter
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

    한 화면에는 보관함 목록·추천곡 등 다른 곡 목록 응답도 섞인다. 그래서 페이지 URL에
    플레이리스트 ID가 있으면 요청 URL에 그 ID가 들어간 응답만 쓰고, 없으면 아무것도 쓰지 않는다.
    ID가 없는 페이지(예: 좋아요한 노래)만 받은 곡을 모두 합친다.
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
    if ids:
        return _dedupe(matched), bool(matched)
    return _dedupe(others), False


# ---------------------------------------------------------------------------
# 플레이리스트 이름
# ---------------------------------------------------------------------------

_NAME_KEYS = ("mylistName", "playlistName", "playlistTitle", "mylistTitle", "title", "name")
_GENERIC_NAMES = re.compile(r"^(보관함|플레이리스트|VIBE|바이브|새 플레이리스트 추가|\d+\s*곡)$", re.I)


def _iter_dicts(obj: Any) -> Iterator[dict]:
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _iter_dicts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_dicts(v)


def name_from_responses(responses: list[CapturedResponse], playlist_id: str) -> str:
    """응답 JSON에서 이 플레이리스트 ID를 가진 객체의 이름 필드를 찾는다."""
    for r in responses:
        for d in _iter_dicts(parse_body(r.body)):
            if "trackTitle" in d:
                continue
            if not any(k.lower().endswith("id") and str(v) == playlist_id for k, v in d.items()):
                continue
            for key in _NAME_KEYS:
                v = d.get(key)
                if isinstance(v, str) and v.strip():
                    return v.strip()
    return ""


def clean_card_text(text: str) -> str:
    """목록 카드 텍스트('운동\n11곡')에서 이름 줄만 고른다."""
    for line in (text or "").splitlines():
        line = line.strip()
        if line and not _GENERIC_NAMES.match(line):
            return line
    return ""


_HEADINGS_JS = """
() => [...document.querySelectorAll('h1, h2, h3, h4, [class*="title"]')]
  .filter(el => el.offsetParent !== null)
  .map(el => (el.innerText || '').trim())
  .filter(Boolean)
"""


def _page_name(page: Page) -> str:
    for text in page.evaluate(_HEADINGS_JS):
        name = clean_card_text(text)
        if name:
            return name
    return ""


def _name_for(page: Page, responses: list[CapturedResponse], url: str, hint: str = "") -> str:
    ids = page_ids(url)
    name = hint or (name_from_responses(responses, ids[0]) if ids else "") or _page_name(page)
    return name or (f"VIBE 플레이리스트 {ids[0]}" if ids else "VIBE")


# ---------------------------------------------------------------------------
# 수집
# ---------------------------------------------------------------------------

# 보관함 목록의 플레이리스트 카드: 같은 ID로 가는 링크(표지/제목)를 묶고 이름 텍스트를 찾는다.
_CARDS_JS = """
() => {
  const idOf = a => (a.getAttribute('href') || '').match(/\\/mylist\\/(\\d+)/)?.[1];
  const groups = new Map();
  for (const a of document.querySelectorAll('a[href*="/mylist/"]')) {
    const id = idOf(a);
    if (!id) continue;
    if (!groups.has(id)) groups.set(id, {id, url: a.href, texts: []});
    groups.get(id).texts.push((a.innerText || '').trim());
  }
  for (const g of groups.values()) {
    if (g.texts.some(Boolean)) continue;
    // 링크에 글자가 없으면(표지 이미지) 다른 카드를 포함하지 않는 범위까지 부모로 올라가며 찾는다
    let el = [...document.querySelectorAll('a[href*="/mylist/"]')].find(a => idOf(a) === g.id);
    while (el.parentElement) {
      const ids = new Set([...el.parentElement.querySelectorAll('a[href*="/mylist/"]')].map(idOf));
      if (ids.size > 1) break;
      el = el.parentElement;
    }
    g.texts.push((el.innerText || '').trim());
  }
  return [...groups.values()];
}
"""


def _wait_loaded(page: Page) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except PlaywrightError:
        pass
    page.wait_for_timeout(800)


def _collect_one(page: Page, log: CaptureLog, start: int, hint: str = "") -> Optional[Playlist]:
    tracks, exact = tracks_from_responses(log.since(start), page.url)
    if not exact:
        return None
    return Playlist(name=_name_for(page, log.since(start), page.url, hint), source="vibe", url=page.url, tracks=tracks)


def _collect_detail(page: Page, log: CaptureLog) -> list[Playlist]:
    playlist = _collect_one(page, log, 0)
    if playlist is None:
        # 앱이 캐시를 써서 곡 목록을 다시 요청하지 않은 경우 → 새로고침으로 다시 받는다
        start = len(log.history)
        page.reload()
        _wait_loaded(page)
        auto_scroll(page)
        playlist = _collect_one(page, log, start)
    if playlist is None:
        print("※ 이 플레이리스트의 곡 목록 응답을 찾지 못했습니다. --dump 로 실행해 output/raw_vibe 를 공유해 주세요.")
        return []
    return [playlist]


def _collect_library(page: Page, log: CaptureLog, cards: list[dict]) -> list[Playlist]:
    library_url = page.url
    print(f"보관함에서 플레이리스트 {len(cards)}개를 찾았습니다. 하나씩 열어 수집합니다.")
    out: list[Playlist] = []
    for i, card in enumerate(cards, 1):
        hint = next((n for n in map(clean_card_text, card["texts"]) if n), "")
        print(f"  [{i}/{len(cards)}] {hint or card['url']}")
        start = len(log.history)
        try:
            page.goto(card["url"])
            _wait_loaded(page)
            auto_scroll(page)
        except PlaywrightError as e:
            print(f"    열기 실패: {e}")
            continue
        playlist = _collect_one(page, log, start, hint)
        if playlist is None:
            print("    곡 목록을 찾지 못했습니다 (빈 플레이리스트일 수 있음)")
            continue
        out.append(playlist)
    page.goto(library_url)
    return out


def cards_from_responses(responses: list[CapturedResponse], base_url: str) -> list[dict]:
    """화면에 링크가 없을 때 대비: 보관함 응답의 플레이리스트 객체(mylistId + 이름)로 목록을 만든다."""
    origin = "{0.scheme}://{0.netloc}".format(urlparse(base_url))
    cards: dict[str, dict] = {}
    for r in responses:
        for d in _iter_dicts(parse_body(r.body)):
            if "trackTitle" in d:
                continue
            pid = next(
                (str(v) for k, v in d.items() if re.fullmatch(r"(my)?list[_]?id|mylistNo|playlistId", k, re.I)),
                "",
            )
            if not re.fullmatch(r"\d{4,}", pid) or pid in cards:
                continue
            name = next((d[k] for k in _NAME_KEYS if isinstance(d.get(k), str) and d[k].strip()), "")
            cards[pid] = {"id": pid, "url": f"{origin}/mylist/{pid}", "texts": [name]}
    return list(cards.values())


def _collect(page: Page, log: CaptureLog) -> list[Playlist]:
    if page_ids(page.url):
        return _collect_detail(page, log)
    cards = page.evaluate(_CARDS_JS) or cards_from_responses(log.history, page.url)
    if cards:
        return _collect_library(page, log, cards)
    if "library/playlist" in page.url:
        print("※ 보관함 목록에서 플레이리스트를 찾지 못했습니다. 플레이리스트를 하나 열고 Enter 하거나, --dump 결과를 공유해 주세요.")
        return []
    # 좋아요한 노래처럼 ID 없는 페이지: 이번에 받은 곡을 모두 모은다
    tracks, _ = tracks_from_responses(log.since_mark(), page.url)
    if tracks:
        print("※ ID가 없는 페이지라 이번에 받은 곡 목록을 모두 합쳤습니다. 다른 곡이 섞였는지 확인하세요.")
    return [Playlist(name=_page_name(page) or "VIBE", source="vibe", url=page.url, tracks=tracks)]


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
