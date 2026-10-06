"""원본 곡(제목/아티스트)을 Spotify 검색 결과와 매칭한다.

국내 곡은 아티스트 표기가 서비스마다 달라서(예: 아이유 / IU) 아티스트 문자열 비교만으로는
틀리기 쉽다. 그래서 1차로 `track:… artist:…` 필터 검색을 하고(아티스트 별칭 처리는 Spotify에 맡김)
제목 유사도로 고르며, 실패하면 필터 없는 검색 결과를 제목+아티스트 유사도로 고른다.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Callable, Optional

from .models import Track

# (feat. X), [Prod. Y], (Remastered) 등 버전/참여 표기로 보는 괄호 안 단어
_DECORATION_WORDS = re.compile(
    r"\bfeat|\bft\.|\bwith\b|prod|inst|remaster|\bver\.|version|mix|edit|\blive\b", re.I
)
_DASH_SUFFIX = re.compile(r"\s+-\s+.*(remaster|version|mix|edit|live).*$", re.I)
_NON_WORD = re.compile(r"[^\w]+", re.UNICODE)

ACCEPT_FILTERED = 0.80  # 아티스트 필터 검색: 제목 유사도 기준
ACCEPT_LOOSE = 0.78  # 필터 없는 검색: 제목·아티스트 가중 점수 기준


# Spotify 검색어(q) 최대 길이는 250자. 넘으면 400 "Query exceeds maximum length".
MAX_QUERY = 250


def _strip_decorations(t: str) -> str:
    """버전/참여 표기 괄호를 지운다. 괄호 안에 괄호가 또 있어도(예: (Feat. 미란이(Mirani), ...)) 통째로."""
    out: list[str] = []
    i = 0
    while i < len(t):
        if t[i] in "([":
            depth, j = 0, i
            while j < len(t):
                if t[j] in "([":
                    depth += 1
                elif t[j] in ")]":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            group = t[i : j + 1]  # 닫는 괄호가 없으면 끝까지
            if _DECORATION_WORDS.search(group):
                i = j + 1
                continue
        out.append(t[i])
        i += 1
    return re.sub(r"\s{2,}", " ", "".join(out))


def clean_title(title: str) -> str:
    t = unicodedata.normalize("NFKC", title)
    t = _strip_decorations(t)
    t = _DASH_SUFFIX.sub("", t)
    return t.strip()


def normalize(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).lower()
    return _NON_WORD.sub("", s)


def similarity(a: str, b: str) -> float:
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    # 한쪽이 다른 쪽을 포함하면(부제 차이 등) 높게 본다
    if na in nb or nb in na:
        return 0.9
    return SequenceMatcher(None, na, nb).ratio()


def _title_score(track: Track, cand: dict) -> float:
    return max(
        similarity(clean_title(track.title), clean_title(cand["name"])),
        similarity(track.title, cand["name"]),
    )


def _artist_score(track: Track, cand: dict) -> float:
    cand_artists = [a["name"] for a in cand.get("artists", [])]
    if not track.artists or not cand_artists:
        return 0.0
    return max(similarity(a, b) for a in track.artists for b in cand_artists)


def _album_bonus(track: Track, cand: dict) -> float:
    album = (cand.get("album") or {}).get("name", "")
    return 0.05 if track.album and album and similarity(track.album, album) >= 0.85 else 0.0


def _query_escape(s: str, limit: int = 100) -> str:
    return s.replace('"', " ").strip()[:limit].strip()


@dataclass
class Match:
    track: Track
    uri: str = ""
    name: str = ""
    artist: str = ""
    album: str = ""
    score: float = 0.0
    method: str = ""  # "filtered" | "loose" | ""


Search = Callable[[str], list[dict]]


def match_track(track: Track, search: Search) -> Match:
    title = _query_escape(clean_title(track.title) or track.title, 150)
    main_artist = _query_escape(track.artists[0], 60) if track.artists else ""

    best: Optional[tuple[float, dict, str]] = None

    if main_artist:
        q = f'track:"{title}" artist:"{main_artist}"'
        for cand in search(q[:MAX_QUERY]):
            s = _title_score(track, cand) + _album_bonus(track, cand)
            if s >= ACCEPT_FILTERED and (best is None or s > best[0]):
                best = (s, cand, "filtered")

    if best is None:
        q = f"{title} {main_artist}".strip()
        for cand in search(q[:MAX_QUERY]):
            t = _title_score(track, cand)
            a = _artist_score(track, cand)
            s = 0.65 * t + 0.35 * a + _album_bonus(track, cand)
            if t >= 0.75 and s >= ACCEPT_LOOSE and (best is None or s > best[0]):
                best = (s, cand, "loose")

    if best is None:
        return Match(track=track)
    score, cand, method = best
    return Match(
        track=track,
        uri=cand["uri"],
        name=cand["name"],
        artist=", ".join(a["name"] for a in cand.get("artists", [])),
        album=(cand.get("album") or {}).get("name", ""),
        score=round(min(score, 1.0), 3),
        method=method,
    )
