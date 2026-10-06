from playlist_extractor.cli import read_match_csv, to_uri
from playlist_extractor.matcher import clean_title, match_track, similarity
from playlist_extractor.models import Track


def cand(name, artists, uri, album=""):
    return {"name": name, "artists": [{"name": a} for a in artists], "uri": uri, "album": {"name": album}}


def test_clean_title():
    assert clean_title("봄날 (feat. 누군가)") == "봄날"
    assert clean_title("Hype Boy [Prod. 250]") == "Hype Boy"
    assert clean_title("Yesterday - Remastered 2009") == "Yesterday"
    assert clean_title("사건의 지평선") == "사건의 지평선"


def test_similarity():
    assert similarity("Hype Boy", "hype-boy!") == 1.0
    assert similarity("밤편지", "밤편지 (Through the Night)") == 0.9
    assert similarity("Ditto", "Butter") < 0.5


def test_filtered_search_trusts_spotify_artist_alias():
    # VIBE는 '아이유', Spotify는 'IU' — 아티스트 필터 검색 결과면 제목만 보고 채택
    queries = []

    def search(q):
        queries.append(q)
        if q.startswith("track:"):
            return [cand("Through the Night", ["IU"], "spotify:track:x"), cand("밤편지", ["IU"], "spotify:track:ok")]
        return []

    m = match_track(Track("밤편지", ["아이유"]), search)
    assert m.uri == "spotify:track:ok"
    assert m.method == "filtered"
    assert queries == ['track:"밤편지" artist:"아이유"']


def test_falls_back_to_loose_search():
    def search(q):
        if q.startswith("track:"):
            return []
        return [
            cand("Supernova", ["Someone Else"], "spotify:track:wrong"),
            cand("Supernova", ["aespa"], "spotify:track:right", album="Armageddon - The 1st Album"),
        ]

    m = match_track(Track("Supernova", ["aespa (에스파)"], "Armageddon - The 1st Album"), search)
    assert m.uri == "spotify:track:right"
    assert m.method == "loose"


def test_no_match():
    m = match_track(Track("없는 노래", ["무명"]), lambda q: [cand("Totally Different", ["X"], "spotify:track:z")])
    assert m.uri == ""


def test_to_uri():
    assert to_uri("https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC?si=abc") == "spotify:track:4uLU6hMCjMI75M1A2tKUQC"
    assert to_uri("https://open.spotify.com/intl-ko/track/4uLU6hMCjMI75M1A2tKUQC") == "spotify:track:4uLU6hMCjMI75M1A2tKUQC"
    assert to_uri("spotify:track:4uLU6hMCjMI75M1A2tKUQC") == "spotify:track:4uLU6hMCjMI75M1A2tKUQC"
    assert to_uri("") == ""


def test_read_match_csv_groups_and_skips_empty(tmp_path):
    p = tmp_path / "m.csv"
    p.write_text(
        "playlist,source,title,artist,album,spotify_uri,spotify_title,spotify_artist,spotify_album,score,method\n"
        "A,vibe,t1,a,,spotify:track:aaaaaaaaaaaaaaaaaaaaaa,,,,,\n"
        "A,vibe,t2,a,,,,,,,\n"
        "B,bugs,t3,b,,https://open.spotify.com/track/bbbbbbbbbbbbbbbbbbbbbb,,,,,\n",
        encoding="utf-8-sig",
    )
    groups = read_match_csv(p)
    assert dict(groups) == {
        "A": ["spotify:track:aaaaaaaaaaaaaaaaaaaaaa"],
        "B": ["spotify:track:bbbbbbbbbbbbbbbbbbbbbb"],
    }
