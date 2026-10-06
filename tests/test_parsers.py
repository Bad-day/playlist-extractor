from pathlib import Path

from playlist_extractor import bugs, vibe
from playlist_extractor.browser import CapturedResponse, merge_playlist
from playlist_extractor.models import Playlist, Track, load_playlists, save_playlists, uniquify_names

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

    # 플레이리스트 페이지인데 그 ID의 응답이 없으면 다른 목록을 섞지 않고 비워 둔다
    tracks, exact = vibe.tracks_from_responses([recommend], "https://vibe.naver.com/mylist/12345")
    assert (tracks, exact) == ([], False)


def test_vibe_playlist_name_from_response():
    body = '{"response": {"result": {"mylist": {"mylistId": 74895567, "mylistName": "운동", "trackCount": 11}}}}'
    other = '{"result": {"mylists": [{"mylistId": 1, "mylistName": "다른거"}]}}'
    responses = [CapturedResponse("u", "application/json", other), CapturedResponse("u", "application/json", body)]
    assert vibe.name_from_responses(responses, "74895567") == "운동"
    assert vibe.name_from_responses(responses, "999") == ""


def test_vibe_clean_card_text():
    assert vibe.clean_card_text("운동\n11곡") == "운동"
    assert vibe.clean_card_text("\n☠️\n5곡") == "☠️"
    assert vibe.clean_card_text("11곡") == ""


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


def test_uniquify_names():
    pls = [Playlist("A", "vibe"), Playlist("B", "vibe"), Playlist("A", "vibe"), Playlist("A", "vibe")]
    uniquify_names(pls)
    assert [p.name for p in pls] == ["A", "B", "A (2)", "A (3)"]


def test_merge_playlist_keeps_different_playlists_with_same_name():
    a = Playlist("같은이름", "vibe", "https://vibe.naver.com/mylist/1", [Track("x", ["a"], source_id="1")])
    b = Playlist("같은이름", "vibe", "https://vibe.naver.com/mylist/2", [Track("y", ["a"], source_id="2")])
    assert len(merge_playlist(merge_playlist([], a), b)) == 2


def test_vibe_cards_from_library_response():
    body = (
        '{"response": {"result": {"mylists": ['
        '{"mylistId": 74895567, "mylistName": "운동", "tracks": [{"trackId": 1, "trackTitle": "x"}]},'
        '{"mylistId": 74895566, "mylistName": "☠️"}]}}}'
    )
    cards = vibe.cards_from_responses(
        [CapturedResponse("u", "application/json", body)], "https://vibe.naver.com/library/playlists"
    )
    assert [(c["url"], vibe.clean_card_text(c["texts"][0])) for c in cards] == [
        ("https://vibe.naver.com/mylist/74895567", "운동"),
        ("https://vibe.naver.com/mylist/74895566", "☠️"),
    ]
