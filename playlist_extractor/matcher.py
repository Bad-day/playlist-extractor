"""원본 곡(제목/아티스트)을 Spotify 검색 결과와 매칭한다.

국내 곡은 아티스트 표기가 서비스마다 달라서(예: 아이유 / IU, 혁오(HYUKOH) / HYUKOH) 아티스트
문자열 비교만으로는 틀리기 쉽다. 그래서 순서대로 시도한다.

1. `track:"제목" artist:"아티스트"` 필터 검색 (아티스트 별칭 처리는 Spotify에 맡김).
   아티스트가 '한글(영문)' 꼴이면 전체 / 바깥 / 괄호 안 표기로 각각 시도한다.
2. 필터 없는 `제목 아티스트` 검색 → 제목·아티스트 유사도로 고른다.
3. `track:"제목"` 만으로 검색 → 아티스트가 비슷한 곡을 고른다.

확실한 곡이 없으면 가장 그럴듯한 후보를 '추정(guess)'으로 돌려준다. 필터 검색에서 Spotify가
가장 위에 올린 곡(제목은 한글/영문 표기가 달라 비교가 안 되는 경우가 많음)이 그 후보다.
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
    # 한쪽이 다른 쪽을 포함하면(부제 차이 등) 높게 본다.
    # 단 짧은 쪽이 너무 짧으면 우연히 포함될 수 있다(예: 'eat' ⊂ '뻔한멜로디featcrush').
    short, long_ = sorted((na, nb), key=len)
    if short in long_ and len(short) * 2 >= len(long_):
        return 0.9
    return SequenceMatcher(None, na, nb).ratio()


# --- 한글 → 로마자 (국어의 로마자 표기법, 음운 변화는 무시한 단순판) ---------------
_INITIALS = ["g", "kk", "n", "d", "tt", "r", "m", "b", "pp", "s", "ss", "", "j", "jj", "ch", "k", "t", "p", "h"]
_MEDIALS = ["a", "ae", "ya", "yae", "eo", "e", "yeo", "ye", "o", "wa", "wae", "oe", "yo", "u", "wo", "we", "wi",
            "yu", "eu", "ui", "i"]
_FINALS = ["", "k", "k", "k", "n", "n", "n", "t", "l", "k", "m", "l", "l", "l", "p", "l", "m", "p", "p", "t", "t",
           "ng", "t", "t", "k", "t", "p", "t"]


def romanize(text: str) -> str:
    """'위잉위잉' → 'wiingwiing'. Spotify에 로마자 제목으로 올라간 곡과 비교하는 용도."""
    out = []
    for ch in text:
        code = ord(ch) - 0xAC00
        if 0 <= code < 11172:
            out.append(_INITIALS[code // 588] + _MEDIALS[(code % 588) // 28] + _FINALS[code % 28])
        else:
            out.append(ch)
    return "".join(out)


def _has_hangul(text: str) -> bool:
    return any(0xAC00 <= ord(c) <= 0xD7A3 for c in text)


def title_parts(title: str) -> list[str]:
    """비교용 제목 후보: 정리한 제목, 괄호 밖, 괄호 안.
    '노래 (The Song)' → ['노래 (The Song)', '노래', 'The Song'] — 한쪽만 영문 병기한 경우를 맞추기 위해."""
    cleaned = clean_title(title)
    outside = re.sub(r"\s*[\(\[][^\)\]]*[\)\]]", "", cleaned).strip()
    inside = re.findall(r"[\(\[]([^\)\]]+)[\)\]]", cleaned)
    parts = [cleaned, outside] + [i.strip() for i in inside]
    return [p for i, p in enumerate(parts) if normalize(p) and p not in parts[:i]] or [cleaned]


def _title_score(track: Track, cand: dict) -> float:
    mine, theirs = title_parts(track.title), title_parts(cand["name"])
    score = similarity(track.title, cand["name"])
    for a in mine:
        for b in theirs:
            score = max(score, similarity(a, b))
            if _has_hangul(a) and not _has_hangul(b):
                score = max(score, similarity(romanize(a), b))
    # 괄호 안/밖 한쪽만 맞은 경우는 완전 일치보다 조금 낮게
    full = similarity(clean_title(track.title), clean_title(cand["name"]))
    return score if score <= full else min(score, 0.95)


def artist_variants(name: str) -> list[str]:
    """'혁오(HYUKOH)' → ['혁오(HYUKOH)', '혁오', 'HYUKOH']. 괄호가 없으면 그대로 하나."""
    variants = [name.strip()]
    m = re.fullmatch(r"\s*(.+?)\s*[\(\[]\s*(.+?)\s*[\)\]]\s*", name)
    if m:
        variants += [m.group(1), m.group(2)]
    return [v for i, v in enumerate(variants) if v and v not in variants[:i]]


def _artist_score(track: Track, cand: dict) -> float:
    cand_artists = [a["name"] for a in cand.get("artists", [])]
    mine = [v for a in track.artists for v in artist_variants(a)]
    if not mine or not cand_artists:
        return 0.0
    theirs = [v for a in cand_artists for v in artist_variants(a)]
    return max(similarity(a, b) for a in mine for b in theirs)


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
    method: str = ""  # "filtered" | "loose" | "title" | "guess" | ""

    @property
    def is_guess(self) -> bool:
        return self.method == GUESS


Search = Callable[[str], list[dict]]

GUESS = "guess"
GUESS_MIN_LOOSE = 0.5  # 필터 없는 검색 후보를 추정으로 쓸 때 제목·아티스트 최소 유사도


def _to_match(track: Track, score: float, cand: dict, method: str) -> Match:
    return Match(
        track=track,
        uri=cand["uri"],
        name=cand["name"],
        artist=", ".join(a["name"] for a in cand.get("artists", [])),
        album=(cand.get("album") or {}).get("name", ""),
        score=round(min(score, 1.0), 3),
        method=method,
    )


def match_track(track: Track, search: Search) -> Match:
    title = _query_escape(clean_title(track.title) or track.title, 150)
    artists = artist_variants(track.artists[0]) if track.artists else []
    artists = [_query_escape(a, 60) for a in artists]

    def run(q: str) -> list[dict]:
        return search(q[:MAX_QUERY])

    guess: Optional[tuple[float, dict]] = None

    # 1. 제목 + 아티스트 필터
    for artist in artists:
        results = run(f'track:"{title}" artist:"{artist}"')
        best = None
        for cand in results:
            s = _title_score(track, cand) + _album_bonus(track, cand)
            if s >= ACCEPT_FILTERED and (best is None or s > best[0]):
                best = (s, cand)
        if best:
            return _to_match(track, best[0], best[1], "filtered")
        if results and guess is None:
            # 제목 표기가 달라(한글/영문) 비교가 안 될 뿐 Spotify가 고른 1위가 맞는 곡인 경우가 많다
            top = results[0]
            guess = (max(_title_score(track, top), 0.5), top)

    # 2. 필터 없는 검색
    base_artist = artists[1] if len(artists) > 1 else (artists[0] if artists else "")
    best = None
    for cand in run(f"{title} {base_artist}".strip()):
        t = _title_score(track, cand)
        a = _artist_score(track, cand)
        s = 0.65 * t + 0.35 * a + _album_bonus(track, cand)
        if t >= 0.75 and s >= ACCEPT_LOOSE and (best is None or s > best[0]):
            best = (s, cand)
        elif guess is None and t >= GUESS_MIN_LOOSE and a >= GUESS_MIN_LOOSE:
            guess = (s, cand)
    if best:
        return _to_match(track, best[0], best[1], "loose")

    # 3. 제목만 필터 → 아티스트 표기가 크게 다른 경우
    if artists:
        best = None
        for cand in run(f'track:"{title}"'):
            t = _title_score(track, cand)
            a = _artist_score(track, cand)
            if t >= ACCEPT_FILTERED and a >= 0.6 and (best is None or t + a > best[0]):
                best = (t + a, cand)
        if best:
            return _to_match(track, best[0] / 2, best[1], "title")

    if guess:
        return _to_match(track, guess[0], guess[1], GUESS)
    return Match(track=track)
