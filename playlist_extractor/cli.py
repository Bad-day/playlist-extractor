"""명령줄 진입점.

  python -m playlist_extractor vibe            # VIBE 보관함 → output/vibe.json
  python -m playlist_extractor bugs            # 벅스 내 앨범 → output/bugs.json
  python -m playlist_extractor match output/vibe.json output/bugs.json   # → output/match.csv
  python -m playlist_extractor push output/match.csv                     # Spotify에 생성
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import re
import sys
from collections import OrderedDict
from pathlib import Path

from .models import load_playlists, save_playlists, uniquify_names

ROOT = Path.cwd()
OUTPUT = ROOT / "output"
PROFILE = ROOT / ".browser-profile"
TOKEN = ROOT / ".spotify_token.json"

CSV_FIELDS = [
    "playlist", "source", "title", "artist", "album",
    "spotify_uri", "spotify_title", "spotify_artist", "spotify_album", "score", "method",
]


def cmd_extract(args: argparse.Namespace) -> None:
    if args.service == "vibe":
        from .vibe import extract
    else:
        from .bugs import extract
    dump_dir = OUTPUT / f"raw_{args.service}" if args.dump else None
    playlists = extract(PROFILE / args.service, dump_dir=dump_dir, channel="chrome" if args.chrome else None)
    if not playlists:
        print("수집된 플레이리스트가 없습니다.")
        return
    out = Path(args.output or OUTPUT / f"{args.service}.json")
    if out.exists() and not args.overwrite:
        # 여러 번 나눠 실행해도 이전 결과가 지워지지 않게 이어 붙인다 (같은 URL은 새 결과로 교체)
        new_urls = {p.url for p in playlists}
        playlists = [p for p in load_playlists(out) if p.url not in new_urls] + playlists
    uniquify_names(playlists)
    save_playlists(playlists, out)
    for p in playlists:
        print(f"  - {p.name}: {len(p.tracks)}곡")
    total = sum(len(p.tracks) for p in playlists)
    print(f"\n저장: {out}  ({len(playlists)}개 플레이리스트, {total}곡)")
    if dump_dir:
        print(f"원본 응답 덤프: {dump_dir}")


def _client(args: argparse.Namespace):
    from .spotify import DEFAULT_REDIRECT, SpotifyClient

    client_id = args.client_id or os.environ.get("SPOTIFY_CLIENT_ID")
    if not client_id:
        sys.exit("Spotify Client ID가 필요합니다: --client-id 또는 환경변수 SPOTIFY_CLIENT_ID")
    client = SpotifyClient(client_id, TOKEN, os.environ.get("SPOTIFY_REDIRECT_URI", DEFAULT_REDIRECT))
    client.login()
    return client


def cmd_match(args: argparse.Namespace) -> None:
    from .matcher import match_track

    playlists = [p for path in args.inputs for p in load_playlists(Path(path))]
    if args.only:
        playlists = [p for p in playlists if p.name in args.only]
    if not playlists:
        sys.exit("매칭할 플레이리스트가 없습니다.")

    client = _client(args)
    out = Path(args.output or OUTPUT / "match.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    matched = total = 0
    with out.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for p in playlists:
            print(f"\n[{p.source}] {p.name} ({len(p.tracks)}곡)")
            for t in p.tracks:
                m = match_track(t, client.search_tracks)
                total += 1
                matched += bool(m.uri)
                mark = "✔" if m.uri else "✘"
                print(f"  {mark} {t.title} / {t.artist}" + (f"  →  {m.name} / {m.artist} ({m.score})" if m.uri else ""))
                writer.writerow({
                    "playlist": p.name, "source": p.source,
                    "title": t.title, "artist": t.artist, "album": t.album,
                    "spotify_uri": m.uri, "spotify_title": m.name, "spotify_artist": m.artist,
                    "spotify_album": m.album, "score": m.score or "", "method": m.method,
                })
    print(f"\n매칭 {matched}/{total}곡. 결과: {out}")
    print("못 찾은 곡(spotify_uri 비어 있음)은 Spotify 곡 링크를 spotify_uri 칸에 붙여 넣으면 push 때 함께 추가됩니다.")


_TRACK_LINK = re.compile(r"open\.spotify\.com/(?:intl-[a-z]+/)?track/([A-Za-z0-9]{22})")


def to_uri(value: str) -> str:
    value = value.strip()
    m = _TRACK_LINK.search(value)
    if m:
        return f"spotify:track:{m.group(1)}"
    return value if value.startswith("spotify:track:") else ""


def _read_csv_text(path: Path) -> str:
    # 엑셀에서 고쳐 'CSV(쉼표로 분리)'로 저장하면 UTF-8이 아니라 CP949로 저장된다
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp949")


def read_match_csv(path: Path) -> "OrderedDict[str, list[str]]":
    groups: "OrderedDict[str, list[str]]" = OrderedDict()
    with io.StringIO(_read_csv_text(path), newline="") as f:
        for row in csv.DictReader(f):
            uris = groups.setdefault(row["playlist"], [])
            uri = to_uri(row.get("spotify_uri", ""))
            if uri:
                uris.append(uri)
    return groups


def cmd_push(args: argparse.Namespace) -> None:
    groups = read_match_csv(Path(args.csv))
    if args.only:
        groups = OrderedDict((k, v) for k, v in groups.items() if k in args.only)
    client = _client(args)
    for name, uris in groups.items():
        if not uris:
            print(f"- {name}: 추가할 곡 없음, 건너뜀")
            continue
        title = f"{args.prefix}{name}"
        if args.dry_run:
            print(f"- [dry-run] '{title}' 에 {len(uris)}곡 추가 예정")
            continue
        playlist = client.create_playlist(title, description="playlist-extractor로 이전", public=args.public)
        client.add_items(playlist["id"], uris)
        print(f"✔ '{title}' {len(uris)}곡 → {playlist.get('external_urls', {}).get('spotify', '')}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="playlist-extractor", description="벅스/VIBE 플레이리스트 → Spotify")
    sub = parser.add_subparsers(dest="command", required=True)

    for service, label in (("vibe", "네이버 VIBE 보관함"), ("bugs", "벅스 곡 목록(내 앨범·최근 들은 곡 등)")):
        p = sub.add_parser(service, help=f"{label} 추출")
        p.add_argument("-o", "--output", help=f"결과 JSON (기본 output/{service}.json)")
        p.add_argument("--dump", action="store_true", help="원본 응답/HTML을 output/raw_*/ 에 저장 (구조 확인용)")
        p.add_argument("--chrome", action="store_true", help="설치된 Chrome으로 실행 (로그인 차단 시)")
        p.add_argument("--overwrite", action="store_true", help="기존 결과 파일에 이어 붙이지 않고 덮어쓰기")
        p.set_defaults(func=cmd_extract, service=service)

    p = sub.add_parser("match", help="추출 결과를 Spotify 곡과 매칭해 CSV 생성")
    p.add_argument("inputs", nargs="+", help="vibe.json / bugs.json")
    p.add_argument("-o", "--output", help="결과 CSV (기본 output/match.csv)")
    p.add_argument("--only", nargs="+", help="이 이름의 플레이리스트만")
    p.add_argument("--client-id")
    p.set_defaults(func=cmd_match)

    p = sub.add_parser("push", help="매칭 CSV로 Spotify 플레이리스트 생성")
    p.add_argument("csv")
    p.add_argument("--prefix", default="", help="Spotify 플레이리스트 이름 앞에 붙일 문자열")
    p.add_argument("--public", action="store_true", help="공개 플레이리스트로 생성 (기본 비공개)")
    p.add_argument("--only", nargs="+", help="이 이름의 플레이리스트만")
    p.add_argument("--dry-run", action="store_true", help="실제로 만들지 않고 계획만 출력")
    p.add_argument("--client-id")
    p.set_defaults(func=cmd_push)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)
