from pathlib import Path

from playlist_extractor import bugs, vibe
from playlist_extractor.browser import CapturedResponse, merge_playlist
from playlist_extractor.models import Playlist, Track, load_playlists, save_playlists

FIXTURES = Path(__file__).parent / "fixtures"


def read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_vibe_json_tracks():
    tracks = list(vibe.iter_tracks(vibe.parse_body(read("vibe_playlist.json"))))
    assert [t.title for t in tracks] == ["밤편지", "Hype Boy", "봄날 (feat. 누군가)"]
    assert tracks[0].artists == ["아이유"]
    assert tracks[0].album == "밤편지"
    assert tracks[2].artists == ["방탄소년단", "누군가"]
    assert tracks[1].source_id == "1002"


def test_vibe_xml_tracks():
    tracks = list(vibe.iter_tracks(vibe.parse_body(read("vibe_playlist.xml"))))
    assert [(t.title, t.artists, t.album) for t in tracks] == [
        ("Ditto", ["NewJeans"], "OMG"),
        ("Love wins all", ["아이유", "V"], "Love wins all"),
    ]


def test_vibe_prefers_responses_for_current_playlist():
    playlist = CapturedResponse(
        "https://apis.naver.com/vibeWeb/musicapiweb/myMusic/mylist/12345/tracks?start=1", "application/json",
        read("vibe_playlist.json"),
    )
    recommend = CapturedResponse(
        "https://apis.naver.com/vibeWeb/musicapiweb/recommend/tracks", "application/xml", read("vibe_playlist.xml")
    )
    tracks, exact = vibe.tracks_from_responses([recommend, playlist], "https://vibe.naver.com/mylist/12345")
    assert exact
    assert [t.title for t in tracks] == ["밤편지", "Hype Boy", "봄날 (feat. 누군가)"]

    tracks, exact = vibe.tracks_from_responses([recommend, playlist], "https://vibe.naver.com/library/tracks")
    assert not exact
    assert len(tracks) == 5


def test_vibe_dedupes_paged_responses():
    r = CapturedResponse("https://apis.naver.com/vibeWeb/x/12345", "application/json", read("vibe_playlist.json"))
    tracks, _ = vibe.tracks_from_responses([r, r], "https://vibe.naver.com/mylist/12345")
    assert len(tracks) == 3


def test_vibe_parse_body_ignores_garbage():
    assert vibe.parse_body("not json") is None
    assert vibe.parse_body("<broken") is None


def test_bugs_html_tracks():
    tracks = bugs.parse_tracks(read("bugs_myalbum.html"))
    assert [(t.title, t.artists, t.album, t.source_id) for t in tracks] == [
        ("Supernova", ["aespa (에스파)"], "Armageddon - The 1st Album", "3001"),
        ("사건의 지평선", ["윤하 (YOUNHA)"], "END THEORY : Final Edition", "3002"),
    ]


def test_merge_playlist_replaces_same_url_and_appends_next_page():
    a1 = Playlist("A", "bugs", "u1", [Track("x", ["a"], source_id="1")])
    a1_again = Playlist("A", "bugs", "u1", [Track("x", ["a"], source_id="1"), Track("y", ["a"], source_id="2")])
    a_page2 = Playlist("A", "bugs", "u1?page=2", [Track("y", ["a"], source_id="2"), Track("z", ["a"], source_id="3")])
    b = Playlist("B", "bugs", "u2", [Track("w", ["b"], source_id="9")])

    pls = merge_playlist([], a1)
    pls = merge_playlist(pls, a1_again)
    assert [len(p.tracks) for p in pls] == [2]
    pls = merge_playlist(pls, a_page2)
    pls = merge_playlist(pls, b)
    assert [(p.name, [t.source_id for t in p.tracks]) for p in pls] == [("A", ["1", "2", "3"]), ("B", ["9"])]


def test_save_and_load_roundtrip(tmp_path):
    pls = [Playlist("내 리스트", "vibe", "u", [Track("밤편지", ["아이유"], "밤편지", "1")])]
    save_playlists(pls, tmp_path / "out.json")
    assert load_playlists(tmp_path / "out.json") == pls
