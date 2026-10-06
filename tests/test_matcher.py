from playlist_extractor.cli import read_match_csv, to_uri
from playlist_extractor.matcher import artist_variants, clean_title, match_track, romanize, similarity
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
    assert similarity("Somebody That I Used To Know", "Somebody That I Used To Know Remix") == 0.9
    # 짧은 단어가 우연히 포함되는 경우는 높게 보지 않는다 ('eat' ⊂ 'featcrush')
    assert similarity("뻔한 멜로디 (Feat. Crush)", "Eat") < 0.5
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
    assert match_track(Track("없는 노래", ["무명"]), lambda q: []).uri == ""
    # 필터 검색에 아무것도 없고, 필터 없는 검색 결과도 전혀 안 닮았으면 추정도 하지 않는다
    m = match_track(
        Track("없는 노래", ["무명"]),
        lambda q: [] if "artist:" in q or q.startswith("track:") else [cand("Totally Different", ["X"], "spotify:track:z")],
    )
    assert m.uri == ""


def test_guess_takes_spotify_top_result_when_titles_differ():
    # Spotify에는 영문 제목(T.B.H)으로만 있어 제목 비교는 실패하지만, 아티스트 필터 검색 1위가 그 곡
    def search(q):
        if q.startswith('track:"고민중독" artist:'):
            return [cand("T.B.H", ["QWER"], "spotify:track:tbh"), cand("Discord", ["QWER"], "spotify:track:d")]
        return []

    m = match_track(Track("고민중독", ["QWER"]), search)
    assert (m.uri, m.method, m.is_guess) == ("spotify:track:tbh", "guess", True)


def test_bracket_artist_variants_and_romanized_title():
    queries = []

    def search(q):
        queries.append(q)
        if q == 'track:"위잉위잉" artist:"HYUKOH"':
            return [cand("Wi ing Wi ing", ["HYUKOH"], "spotify:track:wiing")]
        return []

    m = match_track(Track("위잉위잉", ["혁오(HYUKOH)"]), search)
    assert (m.uri, m.method) == ("spotify:track:wiing", "filtered")
    assert queries == [
        'track:"위잉위잉" artist:"혁오(HYUKOH)"',
        'track:"위잉위잉" artist:"혁오"',
        'track:"위잉위잉" artist:"HYUKOH"',
    ]
    assert artist_variants("GRAY (그레이)") == ["GRAY (그레이)", "GRAY", "그레이"]
    assert artist_variants("카더가든") == ["카더가든"]
    assert romanize("위잉위잉") == "wiingwiing"


def test_english_subtitle_in_brackets():
    def search(q):
        return [cand("노래 (The Song)", ["Zion.T"], "spotify:track:song")] if q.startswith("track:") else []

    m = match_track(Track("노래", ["Zion.T"]), search)
    assert (m.uri, m.method) == ("spotify:track:song", "filtered")


def test_no_false_match_on_feat_substring():
    # 예전에는 '뻔한 멜로디 (Feat. Crush)' 가 'Eat' 으로 잘못 매칭됐다
    def search(q):
        return [] if q.startswith("track:") else [cand("Eat", ["Zion.T"], "spotify:track:eat")]

    m = match_track(Track("뻔한 멜로디 (Feat. Crush)", ["Zion.T"]), search)
    assert m.method != "loose"


def test_title_only_search_when_artist_spelling_differs():
    def search(q):
        if q == 'track:"Hello"':
            return [cand("Hello", ["Someone"], "spotify:track:no"), cand("Hello", ["Adele"], "spotify:track:adele")]
        return []

    m = match_track(Track("Hello", ["ADELE (아델)"]), search)
    assert (m.uri, m.method) == ("spotify:track:adele", "title")


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


def test_read_match_csv_saved_by_excel_in_cp949(tmp_path):
    p = tmp_path / "m.csv"
    p.write_bytes(
        ("playlist,source,title,artist,album,spotify_uri,spotify_title,spotify_artist,spotify_album,score,method\r\n"
         "국힙&외힙,vibe,곡,가수,,spotify:track:aaaaaaaaaaaaaaaaaaaaaa,,,,,\r\n").encode("cp949")
    )
    assert dict(read_match_csv(p)) == {"국힙&외힙": ["spotify:track:aaaaaaaaaaaaaaaaaaaaaa"]}


ACHOO = (
    "Achoo Remix (Feat. 미란이(Mirani), pH-1, 먼치맨, Skinny Brown, Louie, 릴러말즈 (Leellamarz), "
    "Ourealgoat (아우릴고트), Dbo (디보), 식케이 (Sik-K), 오왼 (Owen), Kid Milli, 스윙스, Nudeboi Seo, "
    "TRADE L, 쿠기 (Coogie), Blase (블라세), sokodomo, Khundi Panda, 휘민 (Lil Moshpit), Khakii (카키))"
)


def test_clean_title_nested_parentheses():
    assert clean_title(ACHOO) == "Achoo Remix"
    assert clean_title("긴 겨울 (With 오존 (O3ohn))") == "긴 겨울"
    assert clean_title("Hero (Feat. JUSTHIS, Golden) (Prod. GroovyRoom)") == "Hero"
    assert clean_title("밤새 (취향저격 그녀 X 카더가든)") == "밤새 (취향저격 그녀 X 카더가든)"


def test_queries_stay_within_spotify_limit():
    queries = []
    long_title = "가" * 400 + " (Feat. " + "나" * 300 + ")"
    match_track(Track(long_title, ["다" * 200]), lambda q: queries.append(q) or [])
    match_track(Track(ACHOO, ["그루비룸(GroovyRoom)", "저스디스(JUSTHIS)"]), lambda q: queries.append(q) or [])
    assert queries and all(len(q) <= 250 for q in queries)
    assert 'track:"Achoo Remix" artist:"그루비룸(GroovyRoom)"' in queries


def test_read_match_csv_excludes_guesses_and_dedupes(tmp_path):
    p = tmp_path / "m.csv"
    p.write_text(
        "playlist,source,title,artist,album,spotify_uri,spotify_title,spotify_artist,spotify_album,score,method\n"
        "A,vibe,t1,a,,spotify:track:aaaaaaaaaaaaaaaaaaaaaa,,,,1.0,filtered\n"
        "A,vibe,t1 다른 앨범,a,,spotify:track:aaaaaaaaaaaaaaaaaaaaaa,,,,1.0,filtered\n"
        "A,vibe,t2,a,,spotify:track:gggggggggggggggggggggg,,,,0.5,guess\n",
        encoding="utf-8-sig",
    )
    assert read_match_csv(p)["A"] == ["spotify:track:aaaaaaaaaaaaaaaaaaaaaa", "spotify:track:gggggggggggggggggggggg"]
    assert read_match_csv(p, exclude_guesses=True)["A"] == ["spotify:track:aaaaaaaaaaaaaaaaaaaaaa"]
