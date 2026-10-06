"""추출한 플레이리스트를 서비스와 무관한 공통 형태로 표현하고 JSON으로 저장/로드한다."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Track:
    title: str
    artists: list[str]
    album: str = ""
    source_id: str = ""

    @property
    def artist(self) -> str:
        return ", ".join(self.artists)


@dataclass
class Playlist:
    name: str
    source: str  # "vibe" | "bugs"
    url: str = ""
    tracks: list[Track] = field(default_factory=list)


def save_playlists(playlists: list[Playlist], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = [asdict(p) for p in playlists]
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_playlists(path: Path) -> list[Playlist]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [
        Playlist(
            name=p["name"],
            source=p["source"],
            url=p.get("url", ""),
            tracks=[Track(**t) for t in p["tracks"]],
        )
        for p in data
    ]
