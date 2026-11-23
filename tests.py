"""Run with:  python -m pytest -q tests.py
Sample API payloads follow the official cbbd client's field names (TeamSeasonStats, GameInfo)."""
import json
from datetime import date

import pytest

import config, fetch, ledger, model, webpage as site


def unit(fgm, fga, ftm, fta, orb, drb, tov, pts):
    return {"fieldGoals": {"made": fgm, "attempted": fga, "pct": None},
            "freeThrows": {"made": ftm, "attempted": fta, "pct": None},
            "rebounds": {"offensive": orb, "defensive": drb, "total": orb + drb},
            "turnovers": {"total": tov, "teamTotal": 1},
            "points": {"total": pts, "inPaint": 0, "offTurnovers": 0, "fastBreak": 0}}


def stats_row(tid, name, games=10, **kw):
    t = unit(300, 600, 150, 200, 100, 250, 110, 800)
    o = unit(280, 620, 120, 170, 90, 240, 130, 760)
    t.update(kw.get("team", {}))
    o.update(kw.get("opp", {}))
    return {"season": 2027, "seasonLabel": "2026-27", "teamId": tid, "team": name, "conference": "X",
            "games": games, "wins": 5, "losses": 5, "teamStats": t, "opponentStats": o}


def game(gid, start, away, aid, home, hid, status="scheduled", ap=None, hp=None, aper=None, hper=None):
    return {"id": gid, "startDate": start, "startTimeTbd": False, "status": status, "neutralSite": False,
            "awayTeam": away, "awayTeamId": aid, "homeTeam": home, "homeTeamId": hid,
            "awayPoints": ap, "homePoints": hp, "awayPeriodPoints": aper, "homePeriodPoints": hper}


# ---------------- parsers ----------------
def test_parse_team_stats_per_game():
    nd = dict(stats_row(3, "Elms College"), conference=None)
    rows = [dict(stats_row(1, "A"), seasonLabel="20262027"), stats_row(2, "B", games=0), nd]
    team, opp, label = fetch.parse_team_stats(rows)
    assert label == "2026-27" and list(team) == [1]          # 0-game and non-D1 teams dropped
    a = team[1]
    assert a["PPG"] == 80 and a["FGA"] == 60 and a["FG%"] == 0.5 and a["FTA"] == 20
    assert a["FT%"] == 0.75 and a["ORB"] == 10 and a["DRB"] == 25 and a["TOV"] == 11
    assert opp[1]["PPG"] == 76


def test_parse_games_times_and_finals():
    g = fetch.parse_games([
        game(1, "2026-11-04T00:00:00.000Z", "Wofford", 10, "Tennessee", 20),          # 7 PM ET Nov 3
        game(2, "2026-11-03T17:00:00.000Z", "La Salle", 30, "Davidson", 40, "final", 64, 71, [27, 37], [33, 38]),
    ])
    assert g[0]["date"] == "2026-11-03" and g[0]["when"] == "Nov 3, 2026 7:00 PM ET"
    assert g[0]["away_pts"] is None and g[0]["away_h1"] is None
    assert (g[1]["away_pts"], g[1]["home_pts"], g[1]["away_h1"], g[1]["home_h1"]) == (64, 71, 27, 33)
    # a "final" without a winner is a game that was never played (the API lists some placeholder
    # matchups that way, 0-0): it is not a result and must never be graded
    ghost = fetch.parse_games([game(3, "2026-11-14T18:00:00.000Z", "Towson", 50, "Morgan State", 60, "final", 0, 0)])[0]
    assert ghost["away_pts"] is None and ghost["home_pts"] is None
    rows = []
    ledger.lock(rows, "2026-11-14", [{"when": ghost["when"], "away_id": 50, "away": "Towson", "home_id": 60, "home": "Morgan State",
                                      "away_rating": 1.3, "home_rating": 1.2, "pick": "Towson", "differential": 0.1,
                                      "strong_pick": "", "total": 144.2}], "2026-27", "t")
    assert ledger.grade(rows, "2026-11-14", [ghost]) == 0 and rows[0]["pick_correct"] == ""


def test_a_row_graded_from_a_tie_goes_back_to_ungraded():
    import build
    row = {k: "" for k in ledger.FIELDS}
    ghost = dict(row, date="2026-11-14", away="Towson", home="Morgan State", away_pts="0", home_pts="0", pick_correct="1", total_error="-144.2")
    real = dict(row, date="2026-11-14", away="UMBC", home="Towson", away_pts="42", home_pts="68", pick_correct="1")
    open_ = dict(row, date="2026-11-18", away="A", home="B")
    rows = [ghost, real, open_]
    assert build.ungrade_ties(rows) == [ghost]
    assert (ghost["away_pts"], ghost["home_pts"], ghost["pick_correct"], ghost["total_error"]) == ("", "", "", "")
    assert real["home_pts"] == "68" and build.ungrade_ties(rows) == []


def test_never_played_games_leave_the_schedule_strength_data(tmp_path, monkeypatch):
    import build
    monkeypatch.setattr(build, "RAW", tmp_path)
    monkeypatch.setattr(build, "REFRESH", True)
    saved = {"format": 2, "through": "2026-11-17", "games": [["2026-11-10", 1, 2, 0, 0, 0], ["2026-11-12", 1, 3, 70, 60, 0],
                                                              ["2026-11-14", 4, 5, 0, 0, 1]]}
    (tmp_path / "season_games_2027.json").write_text(json.dumps(saved))
    assert build.season_games(2027, date(2026, 11, 18)) == [(1, 3, 70, 60, False)]      # the two 0-0 "ties" are gone


def test_first_half_last3():
    gl = fetch.parse_games([
        game(i, f"2026-11-{d:02d}T23:00:00Z", "A", 1, "B", 2, "final", 70, 71, [a1, 35], [b1, 35])
        for i, (d, a1, b1) in enumerate([(1, 10, 20), (3, 30, 40), (5, 40, 50), (7, 50, 60), (9, 99, 99)])])
    fh = fetch.first_half_last3(gl, "2026-11-09")    # Nov 9 game excluded (not before the date)
    assert fh[1] == pytest.approx((30 + 40 + 50) / 3)
    assert fh[2] == pytest.approx((40 + 50 + 60) / 3)


def test_parse_teams_prefers_dark_logo():
    t = fetch.parse_teams([{"id": 150, "mascot": "Blue Devils", "primaryColor": "001A57", "abbreviation": "DUKE",
                            "logos": ["https://x/500/150.png", "https://x/500-dark/150.png"]},
                           {"id": 2, "mascot": None, "primaryColor": None, "logos": None}])
    assert t["150"] == {"mascot": "Blue Devils", "color": "001A57", "logo": "https://x/500-dark/150.png", "abbr": "DUKE",
                        "espn": "", "conf": ""}
    assert t["2"]["logo"] == "" and t["2"]["mascot"] == ""


def test_predicted_score_matches_pick():
    r = {"total": "150.0", "differential": "0.05", "pick": "Home St", "home": "Home St"}
    a, h = site.predicted_score(r)
    assert h > a and a + h in (149, 150, 151)          # 164 x 0.05 = 8.2 pt margin
    r.update(differential="0.0001")                      # tiny gap still shows the pick winning
    a, h = site.predicted_score(r)
    assert h > a


# ---------------- model math ----------------
T = {"name": "A", "PPG": 80.0, "FGA": 60.0, "FTA": 20.0, "TOV": 10.0, "FG%": 0.48, "FT%": 0.75, "ORB": 10.0, "DRB": 25.0}
O = {"name": "A", "PPG": 70.0, "FGA": 58.0, "FTA": 18.0, "TOV": 12.0, "FG%": 0.42, "FT%": 0.70, "ORB": 9.0, "DRB": 24.0}


def test_rating_by_hand():
    r = model.team_rating(T, O)
    tov = 10 / (60 + 0.44 * 20 + 10)
    otov = 12 / (58 + 0.44 * 18 + 12)
    off = 0.4 * 0.48 + 0.25 * (1 - tov) + 0.2 * (10 / 34) + 0.15 * 0.75
    de = 0.4 * 0.58 + 0.25 * otov + 0.2 * (1 - 9 / 34) + 0.15 * 0.30
    assert r["rating"] == pytest.approx(off + de) and r["ppg"] == pytest.approx(75.0)


def test_predict_rules_with_home_court():
    K, H = config.POINTS_PER_RATING, config.HOME_COURT_POINTS
    rat = {1: {"rating": 1.10, "ppg": 75.0}, 2: {"rating": 1.20, "ppg": 70.0}}
    g = {"away_id": 1, "away": "Away U", "home_id": 2, "home": "Home St", "when": "x"}
    p = model.predict(g, rat)
    assert p["margin"] == pytest.approx(K * 0.10 + H)                     # rating edge + home court
    assert p["pick"] == "Home St" and p["differential"] == pytest.approx(0.10 + H / K)
    assert p["strong_pick"] == "Home St" and p["total"] == pytest.approx(145.0)
    # first half: same side as the game pick, leading by FIRST_HALF_SHARE of the projected margin
    assert p["fh_pick"] == "Home St" and p["fh_margin"] == pytest.approx(config.FIRST_HALF_SHARE * (K * 0.10 + H))
    assert model.predict(g, rat, {1: 40.0, 2: 35.0})["fh_pick"] == "Home St"   # old 1H scoring argument is ignored
    # strong pick = projected margin past STRONG_PICK_GAP (about 15 points)
    rat[2]["rating"] = 1.10 + (K * config.STRONG_PICK_GAP - H + 0.5) / K
    assert model.predict(g, rat)["strong_pick"] == "Home St"
    rat[2]["rating"] = 1.10 + (K * config.STRONG_PICK_GAP - H - 0.5) / K
    assert model.predict(g, rat)["strong_pick"] == "" and model.predict(g, rat)["pick"] == "Home St"
    # equal ratings: home court decides at home, nobody gets it at a neutral site (tie -> away, like the sheet)
    rat[2]["rating"] = 1.10
    assert model.predict(g, rat, {})["pick"] == "Home St"
    assert model.predict({**g, "neutral": True}, rat, {})["pick"] == "Away U"
    # away team better by less than home court -> home still picked; by more -> away picked
    rat[1]["rating"] = 1.10 + (H - 1) / K
    assert model.predict(g, rat, {})["pick"] == "Home St"
    rat[1]["rating"] = 1.10 + (H + 1) / K
    assert model.predict(g, rat, {})["pick"] == "Away U"
    none = model.predict({**g, "away_id": 999}, rat, {})
    assert none["pick"] is None and none["fh_pick"] is None
    # a coin-flip game still shows a first-half lean of at least half a point
    rat[1]["rating"] = 1.10 + (H + 0.1) / K
    assert model.predict(g, rat)["fh_margin"] == pytest.approx(0.5)


def test_results_ratings():
    # neutral-site games: X beats Y by 10, Y beats Z by 10 -> X > Y > Z, evenly spaced
    g = [("Y", "X", 60, 70, True), ("Z", "Y", 60, 70, True), ("Y", "X", 61, 71, True), ("Z", "Y", 61, 71, True)]
    r = model.results_ratings(g)
    assert r["X"] > r["Y"] > r["Z"]
    assert (r["X"] - r["Y"]) == pytest.approx(r["Y"] - r["Z"], abs=0.5)
    assert sum(r.values()) == pytest.approx(0, abs=1e-9)
    # blowouts are capped at 25
    big = model.results_ratings([("B", "A", 40, 100, True)] * 4)
    capped = model.results_ratings([("B", "A", 40, 65, True)] * 4)
    assert big["A"] == pytest.approx(capped["A"])
    # home court is learned from home games and removed from team strength
    home = model.results_ratings([("P", "Q", 70, 74, False), ("Q", "P", 70, 74, False)] * 3)
    assert home["P"] == pytest.approx(home["Q"], abs=1e-6)       # each won at home by 4: equal teams


def test_schedule_adjust():
    # A and B have identical four-factor numbers, but A played the strong team S and B the weak W
    base = lambda: {"offense": .57, "defense": .45, "rating": 1.02, "ppg": 70.0, "name": "x"}  # noqa: E731
    rat = {"A": base(), "B": base(), "S": base(), "W": base()}
    games = [("W", "S", 50, 80, True), ("W", "S", 55, 80, True),      # S crushes W
             ("A", "S", 65, 70, True), ("A", "S", 66, 70, True),      # A plays S close
             ("B", "W", 70, 65, True), ("B", "W", 71, 66, True)]      # B beats W
    model.schedule_adjust(rat, games)
    assert rat["A"]["rating"] > rat["A"]["raw_rating"] == pytest.approx(1.02)   # tough schedule credited
    assert rat["B"]["rating"] < rat["B"]["raw_rating"]                          # soft schedule docked
    assert rat["A"]["sos"] > 0 > rat["B"]["sos"]
    # weight 0 leaves ratings untouched
    rat2 = {"A": base(), "S": base()}
    model.schedule_adjust(rat2, [("A", "S", 60, 80, True)], weight=0)
    assert rat2["A"]["rating"] == pytest.approx(1.02)

def test_season_label():
    assert config.season_for(date(2026, 11, 5)) == 2027 and config.season_for(date(2027, 3, 15)) == 2027


# ---------------- ledger ----------------
def test_lock_idempotent_and_grade_with_halves():
    rows = []
    base = {"when": "Mar 1, 2026 12:00 PM ET", "away_rating": 1.3, "home_rating": 1.4, "differential": 0.1, "total": 140.0}
    preds = [dict(base, away_id=30, away="La Salle", home_id=40, home="Davidson", pick="Davidson",
                  strong_pick="Davidson", fh_pick="La Salle", fh_margin=2.0),
             dict(base, away_id=50, away="Tulane", home_id=60, home="South Florida", pick="Tulane",
                  strong_pick="", fh_pick=None, fh_margin=None)]
    assert ledger.lock(rows, "2026-03-01", preds, "2025-26", "t") == 2
    preds[0]["pick"] = "La Salle"
    assert ledger.lock(rows, "2026-03-01", preds, "2025-26", "t2") == 0 and rows[0]["pick"] == "Davidson"
    finals = fetch.parse_games([
        game(1, "2026-03-01T17:00:00Z", "La Salle", 30, "Davidson", 40, "final", 64, 71, [27, 37], [33, 38]),
        game(2, "2026-03-01T17:00:00Z", "Tulane", 50, "South Florida", 60, "final", 62, 90, [30, 32], [30, 60])])
    assert ledger.grade(rows, "2026-03-01", finals) == 2
    r0, r1 = rows
    assert (r0["pick_correct"], r0["strong_correct"], r0["total_error"], r0["fh_correct"]) == ("1", "1", "-5.0", "0")
    assert (r1["pick_correct"], r1["strong_correct"], r1["fh_correct"]) == ("0", "", "")   # no 1H pick


# ---------------- end to end (API mocked) ----------------
def test_end_to_end(tmp_path, monkeypatch):
    import build
    stats = [stats_row(i, f"T{i}") for i in range(1, 321)]
    stats.append(stats_row(500, "Tennessee", team=unit(320, 600, 160, 200, 110, 260, 90, 860)))
    stats.append(stats_row(600, "Wofford"))
    games = [
        # yesterday's final (graded) and last week's games (1H history)
        game(1, "2026-11-10T00:00:00Z", "Wofford", 600, "Tennessee", 500),                      # Nov 9 7PM ET
        game(2, "2026-11-09T00:00:00Z", "T1", 1, "T2", 2, "final", 60, 70, [25, 35], [40, 30]),  # Nov 8
        game(3, "2026-11-08T00:00:00Z", "Wofford", 600, "T3", 3, "final", 70, 60, [33, 37], [30, 30]),
        game(4, "2026-11-08T01:00:00Z", "Tennessee", 500, "T4", 4, "final", 80, 60, [41, 39], [30, 30]),
        game(5, "2026-11-09T23:00:00Z", "Bethesda", 9999, "T5", 5),                              # non-D1
    ]
    monkeypatch.setattr(build, "DATA", tmp_path)
    monkeypatch.setattr(build, "RAW", tmp_path / "raw")
    for fn in (ledger.load, ledger.save):
        monkeypatch.setattr(fn, "__defaults__", (tmp_path / "ledger.csv",))
    monkeypatch.setattr(site.write, "__defaults__", ("", tmp_path / "docs", "", "", ""))
    monkeypatch.setattr(site, "DOCS", tmp_path / "docs")
    import bets, video
    for fn in (bets.load_book, bets.save_book):
        monkeypatch.setattr(fn, "__defaults__", (tmp_path / "bets.csv",))
    monkeypatch.setattr(video, "daily_video", lambda *a, **k: None)      # no ffmpeg render in tests
    monkeypatch.setattr(fetch, "team_stats", lambda s: stats if s == 2027 else [])
    monkeypatch.setattr(fetch, "lines", lambda a, b: [_gl(600, "Wofford", 500, "Tennessee",
                        [{"provider": "consensus", "spread": -9.5, "overUnder": 152.5}])])
    monkeypatch.setattr(fetch, "teams", lambda: [{"id": 500, "mascot": "Volunteers", "primaryColor": "FF8200",
                                                   "abbreviation": "TENN", "logos": ["https://x/500/2633.png"]}])
    monkeypatch.setattr(fetch, "games", lambda a, b: [g for g in games if a.isoformat() <= fetch.parse_games([g])[0]["date"] <= b.isoformat()])
    # the clock stands at that afternoon: the sitemap lists a game page only while its game is recent
    from datetime import datetime
    monkeypatch.setattr(config, "now_et", lambda: datetime(2026, 11, 9, 16, 0, tzinfo=config.ET))
    # day 1: Nov 8 picks get locked for T1@T2 ... (none of interest); run Nov 9
    monkeypatch.setattr("sys.argv", ["build.py", "--date", "2026-11-09"])
    build.main()
    rows = ledger.load(tmp_path / "ledger.csv")
    assert [(r["away"], r["home"]) for r in rows] == [("Wofford", "Tennessee")]   # non-D1 skipped
    r = rows[0]
    assert r["pick"] == "Tennessee" and r["stats_season"] == "2026-27"
    assert r["fh_pick"] == "Tennessee"                     # first half follows the game pick
    assert float(r["fh_margin"]) == pytest.approx(
        config.FIRST_HALF_SHARE * float(r["differential"]) * config.POINTS_PER_RATING, abs=0.06)
    html = (tmp_path / "docs" / "index.html").read_text()
    assert "Tennessee \u22129.5" in html and "152.5" in html
    assert "Best Bets" in (tmp_path / "docs" / "bets.html").read_text()
    gp = tmp_path / "docs" / "games" / "2026-11-09" / "wofford-vs-tennessee.html"
    assert gp.exists() and "Wofford vs Tennessee prediction" in gp.read_text() and "SportsEvent" in gp.read_text()
    sm = (tmp_path / "docs" / "sitemap.xml").read_text()
    assert f"<loc>{config.SITE_URL}/games/2026-11-09/wofford-vs-tennessee.html</loc>" in sm
    assert f"<loc>{config.SITE_URL}/</loc><lastmod>" in sm and "index.html" not in sm     # home page = the bare domain
    # every page names itself as the address search engines should list
    assert f'<link rel="canonical" href="{config.SITE_URL}/games/2026-11-09/wofford-vs-tennessee.html">' in gp.read_text()
    assert f'<link rel="canonical" href="{config.SITE_URL}/">' in html
    assert "<title>College Basketball Predictions Today, Nov 9 | " in html
    assert "including Wofford vs Tennessee" in html and (tmp_path / "canonical_fixed.txt").exists()
    assert "6:00" in html and "Tennessee" in html          # 7:00 PM ET shown as 6:00 PM Central and "Volunteers" in html and "https://x/500/2633.png" in html
    # same evening, game over: a re-run moves it to Results (halftime score not posted yet)
    games[0].update(status="final", awayPoints=60, homePoints=75)
    build.main()
    r = ledger.load(tmp_path / "ledger.csv")[0]
    assert (r["pick_correct"], r["fh_correct"]) == ("1", "")
    html = (tmp_path / "docs" / "index.html").read_text()
    assert "<article" not in html and "1 finished game now on Results" in html and "games are final" in html
    assert "Wofford" in (tmp_path / "docs" / "results.html").read_text()
    # next day: halftime score has arrived -> 1H graded too
    games[0].update(awayPeriodPoints=[28, 32], homePeriodPoints=[36, 39])
    monkeypatch.setattr("sys.argv", ["build.py", "--date", "2026-11-10"])
    build.main()
    r = ledger.load(tmp_path / "ledger.csv")[0]
    assert (r["pick_correct"], r["fh_correct"], r["total_error"]) == ("1", "1", f"{135 - float(r['total']):.1f}")
    assert "1-0" in (tmp_path / "docs" / "results.html").read_text()
    assert "Correct." in gp.read_text() and "Tennessee won 75-60" in gp.read_text()


def test_missing_key_is_clear(monkeypatch):
    monkeypatch.delenv("CBBD_API_KEY", raising=False)
    with pytest.raises(fetch.FetchError, match="CBBD_API_KEY"):
        fetch.team_stats(2027)

# ---------------- betting lines ----------------
def _gl(aid, away, hid, home, books):
    return {"gameId": 1, "awayTeamId": aid, "awayTeam": away, "homeTeamId": hid, "homeTeam": home, "lines": books}


def test_parse_lines_favorite_spread_total():
    rows = [
        # moneylines decide the favorite (home -300 vs away +240 -> home favored)
        _gl(1, "Wofford", 2, "Tennessee", [{"provider": "Bovada", "spread": -14.5, "overUnder": 141.5,
                                            "homeMoneyline": -300, "awayMoneyline": 240}]),
        # no moneylines: spread is from the home side, +3.5 means the AWAY team is favored
        _gl(3, "Duke", 4, "Clemson", [{"provider": "ESPN Bet", "spread": 3.5, "overUnder": 150}]),
        # pick'em
        _gl(5, "A", 6, "B", [{"provider": "consensus", "spread": 0, "overUnder": 140}]),
        # consensus preferred over other books
        _gl(7, "C", 8, "D", [{"provider": "Bovada", "spread": -2, "overUnder": 130},
                             {"provider": "consensus", "spread": -4, "overUnder": 133.5}]),
        # no usable numbers -> skipped
        _gl(9, "E", 10, "F", [{"provider": "x", "spread": None, "overUnder": None}]),
    ]
    m = fetch.parse_lines(rows)
    assert m[(1, 2)] == {"fav": "Tennessee", "spread": 14.5, "total": 141.5, "book": "Bovada", "aml": 240, "hml": -300}
    assert m[(3, 4)]["fav"] == "Duke" and m[(3, 4)]["spread"] == 3.5
    assert m[(5, 6)]["fav"] == "" and m[(5, 6)]["spread"] == 0
    assert m[(7, 8)]["spread"] == 4 and m[(7, 8)]["book"] == "consensus"
    assert (9, 10) not in m


def test_lines_on_ledger_and_page():
    rows = []
    pred = {"when": "Nov 3, 2026 7:00 PM ET", "away_id": 1, "away": "Wofford", "home_id": 2, "home": "Tennessee",
            "away_rating": 1.0, "home_rating": 1.1, "pick": "Tennessee", "differential": 0.1, "strong_pick": "Tennessee",
            "total": 140.0, "fh_pick": None, "fh_margin": None}
    ledger.lock(rows, "2026-11-03", [pred], "2026-27", "t")
    lm = {(1, 2): {"fav": "Tennessee", "spread": 14.5, "total": 141.5, "book": "consensus"}}
    assert ledger.attach_lines(rows, "2026-11-03", lm) == 1
    assert ledger.attach_lines(rows, "2026-11-03", {(1, 2): {"fav": "Wofford", "spread": 1, "total": 1, "book": "x"}}) == 0
    assert (rows[0]["line_fav"], rows[0]["line_spread"], rows[0]["line_total"]) == ("Tennessee", "14.5", "141.5")
    html = site.today_page(rows, "Tuesday, Nov 3", "now", "note", {})
    assert "Tennessee \u221214.5" in html and "141.5" in html and "Strong pick" in html
    rows[0]["line_spread"], rows[0]["line_fav"] = "0", ""
    assert "Pick\u2019em" in site.today_page(rows, "x", "now", "note", {})


# ---------------- O/U plays and upset picks ----------------
def _r(**kw):
    base = {"home": "Home St", "away": "Away U", "home_id": "2", "away_id": "1", "pick": "Home St", "strong_pick": "",
            "total": "150.0", "line_fav": "Home St", "line_spread": "4.5", "line_total": "145.5",
            "away_pts": "", "home_pts": "", "differential": "0.02", "when": "x", "pick_correct": ""}
    base.update(kw)
    return base


def test_ou_play_threshold_and_grading():
    E = config.OU_EDGE_POINTS
    assert site.ou_play(_r(total=str(145.5 + E))) == "Over"
    assert site.ou_play(_r(total=str(145.5 - E))) == "Under"
    assert site.ou_play(_r(total=str(145.5 + E - 0.1))) == ""
    assert site.ou_play(_r(line_total="")) == ""
    over = _r(total="160", away_pts="80", home_pts="70")                 # 150 > 145.5 -> Over wins
    assert site.ou_result(over) == "1"
    assert site.ou_result(_r(total="130", away_pts="80", home_pts="70")) == "0"     # Under, went over
    assert site.ou_result(_r(total="160", line_total="150", away_pts="80", home_pts="70")) == ""  # push


def test_upset_and_ultra():
    assert site.upset(_r()) == ""                                       # model agrees with favorite
    assert site.upset(_r(pick="Away U")) == "upset"                     # model takes the underdog
    assert site.upset(_r(pick="Away U", strong_pick="Away U")) == "ultra"
    assert site.upset(_r(pick="Away U", line_spread="0", line_fav="")) == ""   # pick'em: no favorite
    assert site.upset(_r(pick="Away U", line_fav="", line_spread="")) == ""    # no line


def test_today_page_tags_and_counts():
    rows = [_r(), _r(pick="Away U", total="160"), _r(pick="Away U", strong_pick="Away U", total="120")]
    html = site.today_page(rows, "x", "now", "note", {})
    assert "How to read this page" in html
    assert 'data-f="ou"' in html and 'data-f="upset"' in html
    assert '<b>2</b><span>O/U plays' in html and '<b>2</b><span>upset picks' in html
    games = html.split('class="games"')[1]                    # past the legend
    assert games.count("Upset pick</span>") == 1 and games.count("Ultra upset</span>") == 1
    assert ">Over<" in games and ">Under<" in games


# ---------------- time blocks + live score hooks ----------------
def test_slots_and_central_time():
    assert site.slot_of("Nov 3, 2026 12:00 PM ET") == "early"      # 11 AM CT
    assert site.slot_of("Nov 3, 2026 3:30 PM ET") == "aft"         # 2:30 PM CT
    assert site.slot_of("Nov 3, 2026 7:00 PM ET") == "eve"         # 6 PM CT
    assert site.slot_of("Nov 3, 2026 9:00 PM ET") == "late"        # 8 PM CT
    assert site.slot_of("Nov 3, 2026 11:59 PM ET") == "late"
    assert site.tip_ct("Mar 10, 2027 8:00 PM ET").hour == 19      # daylight time handled
    assert site._tip("Nov 3, 2026 7:00 PM ET") == "6:00<br> PM"


def test_today_page_live_hooks():
    teams = {"1": {"espn": "2390"}, "2": {"espn": "150"}}
    rows = [_r(when="Nov 3, 2026 7:00 PM ET", away_id="1", home_id="2"),
            _r(when="Nov 3, 2026 9:30 PM ET", away_id="1", home_id="2")]
    html = site.today_page(rows, "Tuesday, Nov 3", "now", "note", teams, "2026-11-03")
    assert 'data-date="2026-11-03"' in html
    assert 'data-ea="2390"' in html and 'data-eh="150"' in html and 'data-pick="h"' in html
    assert 'data-slot="eve"' in html and 'data-slot="late"' in html
    assert 'data-s="eve"' in html and 'data-s="late"' in html and 'data-s="aft"' not in html   # empty blocks hidden
    assert 'class="lv" hidden' in html and "LIVE" in html and "site.api.espn.com" in html


def test_results_stats_switch(monkeypatch):
    import webpage
    row = {k: "" for k in ledger.FIELDS}
    row.update(date="2026-11-02", away="A", home="B", pick="B", pick_correct="1", away_pts="60", home_pts="70",
               pred_away="62", pred_home="71", total="133", differential="0.05", when="Nov 2, 2026 7:00 PM ET")
    monkeypatch.setattr(config, "SHOW_RESULTS_STATS", False)
    off = webpage.results_page([row], "now")
    assert 'class="stats"' not in off and "Season results" in off and "Monday, Nov 2" in off
    monkeypatch.setattr(config, "SHOW_RESULTS_STATS", True)
    assert "all picks" in webpage.results_page([row], "now")


def test_best_bets_math_and_page():
    import bets
    assert bets.decimal(-110) == pytest.approx(1.9091, abs=1e-4) and bets.decimal(150) == 2.5
    assert bets.american(2.5) == 150 and bets.american(1.5) == -200
    assert bets.chance(0, 10) == pytest.approx(0.5)

    def row(i, pick_home, diff, total):
        return {"away_id": str(2 * i), "away": f"Away{i}", "home_id": str(2 * i + 1), "home": f"Home{i}",
                "pick": f"Home{i}" if pick_home else f"Away{i}", "differential": str(diff), "total": str(total),
                "when": "Nov 2, 2026 8:00 PM ET"}
    rows = [row(i, True, 0.04 + 0.004 * i, 140) for i in range(1, 10)]
    lm = {(2 * i, 2 * i + 1): {"fav": f"Home{i}", "spread": 3.5, "total": 140.5, "aml": 150, "hml": -180}
          for i in range(1, 10)}
    # game 1: model says home by ~11.9 vs a 3.5 line -> home spread (or ML) qualifies
    b = bets.game_bets(rows[0], lm[(2, 3)])
    sp = [x for x in b if x["kind"] == "Spread" and x["side"] == "home"][0]
    est = 3.5 + bets.MODEL_WEIGHT * (170 * 0.044 - 3.5)         # line nudged toward the model
    assert sp["label"] == "Home1 \u22123.5" and sp["chance"] == pytest.approx(bets.chance(est - 3.5, bets.MARGIN_SD))
    under = [x for x in b if x["label"] == "Under 140.5"][0]
    assert under["chance"] == pytest.approx(1 - bets.chance(bets.MODEL_WEIGHT * -0.5, bets.TOTAL_SD))
    # calibration: model margins half the size of the spreads -> scale 2
    cal_rows = [row(i, True, 0.05, 140) for i in range(20)]
    cal_lines = {(2 * i, 2 * i + 1): {"fav": f"Home{i}", "spread": 17.0, "total": 145} for i in range(20)}
    cal = bets.calibrate(cal_rows, cal_lines)
    assert cal["scale"] == pytest.approx(2.0) and cal["total_shift"] == pytest.approx(5.0)
    # a slate too small to calibrate uses SMALL_SLATE_SCALE; the fit may go below 1 but not below MIN_SCALE
    assert bets.calibrate(rows, lm)["scale"] == bets.SMALL_SLATE_SCALE == 1.0
    big_lines = {k: dict(v, spread=6.375) for k, v in cal_lines.items()}                 # model 8.5 vs line 6.375
    assert bets.calibrate(cal_rows, big_lines)["scale"] == pytest.approx(0.75)
    tiny_lines = {k: dict(v, spread=1.0) for k, v in cal_lines.items()}
    assert bets.calibrate(cal_rows, tiny_lines)["scale"] == bets.MIN_SCALE
    rows = [row(i, True, 0.064 + 0.0064 * i, 140) for i in range(1, 10)]       # home by 12 to 21 on a 3.5 line
    best = bets.best(rows, lm)
    assert best["pool"] == 9 and len(best["singles"]) == 6
    assert len({(x["away"]) for x in best["singles"]}) == 6                     # one bet per game
    edges = [x["edge"] for x in best["singles"]]
    assert edges == sorted(edges, reverse=True) and all(x["chance"] >= 0.6 for x in best["singles"])
    p3 = best["parlays"][3]
    assert p3["legs"] == best["singles"][:3]
    assert p3["chance"] == pytest.approx(best["singles"][0]["chance"] * best["singles"][1]["chance"] * best["singles"][2]["chance"])
    assert best["parlays"][8] is not None
    html = site.bets_page(best, "Monday, Nov 2", "now", {})
    assert "Top 6 single bets" in html and "3-leg parlay" in html and "8-leg parlay" in html and "$10 pays" in html
    small = bets.best(rows[:4], lm)
    assert small["parlays"][6] is None and "not enough for 6 legs" in site.bets_page(small, "x", "now", {})
    assert "No qualifying bets" in site.bets_page(bets.best([], {}), "x", "now", {})


def test_blend_fades_last_season_in():
    prev = {"A": {"rating": 1.00, "ppg": 70.0, "name": "A"}, "B": {"rating": 1.10, "ppg": 80.0, "name": "B"},
            "C": {"rating": 0.90, "ppg": 60.0, "name": "C"}}
    cur = {"A": {"rating": 1.20, "ppg": 90.0, "name": "A"}, "B": {"rating": 1.10, "ppg": 80.0, "name": "B"},
           "D": {"rating": 1.05, "ppg": 75.0, "name": "D"}}
    out = model.blend(prev, cur, {"A": 5, "B": 40, "D": 2}, n_full=20)
    assert out["A"]["rating"] == pytest.approx(1.05) and out["A"]["ppg"] == pytest.approx(75) and out["A"]["blend"] == 0.25
    assert out["B"]["blend"] == 1.0 and out["B"]["rating"] == 1.10          # 40 games: all this season
    assert out["C"]["rating"] == 0.90 and out["C"]["blend"] == 0.0           # hasn't played yet: last season
    # new to D-I: no last season, so it fades in from a stand-in near the bottom of last season's
    # ratings (here C, the lowest of three) with a middle-of-the-pack scoring level
    assert model.new_team_prior(prev) == {"rating": 0.90, "ppg": 70.0}
    assert out["D"]["rating"] == pytest.approx(0.9 * 0.90 + 0.1 * 1.05) and out["D"]["ppg"] == pytest.approx(0.9 * 70 + 0.1 * 75)
    assert out["D"]["blend"] == pytest.approx(0.1) and out["D"]["new_team"] is True and "new_team" not in out["A"]
    assert model.blend(prev, cur, {"D": 25}, n_full=20)["D"]["rating"] == 1.05          # 20+ games: all its own
    assert model.blend({}, cur, {"D": 2}, n_full=20)["D"]["rating"] == 1.05             # nothing to stand in with


def test_best_bets_book_lock_and_grade(tmp_path):
    import bets
    spread = {"kind": "Spread", "side": "away", "num": "31.5", "label": "Mercyhurst +31.5"}
    assert bets.grade_bet(spread, 50, 80) == "W" and bets.grade_bet(spread, 50, 82) == "L"
    assert bets.grade_bet(dict(spread, num="30"), 50, 80) == "P"
    assert bets.grade_bet({"kind": "ML", "side": "home"}, 70, 75) == "W"
    assert bets.grade_bet({"kind": "Total", "side": "under", "num": "140.5"}, 70, 71) == "L"
    assert bets.grade_bet({"kind": "Total", "side": "over", "num": "140.5"}, 70, 71) == "W"
    single = {"kind": "Spread", "side": "home", "label": "Home1 \u22123.5", "odds": -110, "chance": 0.68, "edge": 0.16,
              "num": -3.5, "away_id": "2", "home_id": "3", "away": "Away1", "home": "Home1", "when": "Nov 2, 2026 8:00 PM ET"}
    book = []
    assert bets.lock_day(book, "2026-11-02", [single], "Nov 02, 2026 03:30 AM CT") == 1
    assert bets.lock_day(book, "2026-11-02", [single], "later") == 0           # locked once only
    row = {k: "" for k in ledger.FIELDS}
    row.update(date="2026-11-02", away_id="2", home_id="3", away_pts="60", home_pts="70")
    assert bets.grade_book(book, [row]) == 1 and book[0]["result"] == "W"
    assert bets.record(book) == (1, 0, 0) and bets.record(book, "2026-11-01") == (0, 0, 0)
    bets.save_book(book, tmp_path / "b.csv")
    assert bets.load_book(tmp_path / "b.csv")[0]["label"] == "Home1 \u22123.5"
    empty = bets.best([], {})
    html = site.bets_page(empty, "Tuesday, Nov 3", "now", {}, book, "2026-11-03")
    assert "top bets yesterday" in html and "1-0" in html and "Monday, Nov 2" in html and 'res W big' in html
    html = site.bets_page(empty, "Monday, Nov 2", "now", {}, book, "2026-11-02")
    assert "Today\u2019s top 1 single bets" in html and "final: 1-0" in html


def test_bet_rules_skip_junk_favorites_and_relock():
    import bets
    assert not bets.qualifies({"kind": "ML", "odds": -10000, "chance": 0.99, "edge": 0.001})   # no real edge
    assert not bets.qualifies({"kind": "ML", "odds": -400, "chance": 0.85, "edge": 0.05})       # too short a price
    assert bets.qualifies({"kind": "Spread", "odds": -110, "chance": 0.57, "edge": 0.045})
    assert not bets.qualifies({"kind": "Spread", "odds": -110, "chance": 0.54, "edge": 0.02})
    junk = {"kind": "ML", "side": "home", "label": "Butler ML", "odds": -10000, "chance": 0.99, "edge": 0.001, "num": None,
            "away_id": "1", "home_id": "2", "away": "FDU", "home": "Butler", "when": "Nov 4, 2026 7:00 PM ET"}
    good = dict(junk, kind="Spread", label="FDU +26.5", odds=-110, chance=0.57, edge=0.045, num=26.5)
    book = []
    bets.lock_day(book, "2026-11-04", [junk], "early")
    assert bets.lock_day(book, "2026-11-04", [good], "later") == 1 and [b["label"] for b in book] == ["FDU +26.5"]
    book[0]["result"] = "W"
    assert bets.lock_day(book, "2026-11-04", [junk], "later") == 0           # graded: never replaced


def test_site_pages_brand_and_ads(monkeypatch):
    import webpage
    monkeypatch.setattr(config, "ADSENSE_CLIENT", "")
    html = webpage.about_page("now")
    assert config.SITE_NAME in html and "1-800-GAMBLER" in html and "adsbygoogle" not in html
    assert 'href="privacy.html"' in html and "Bball Draft" not in html
    monkeypatch.setattr(config, "ADSENSE_CLIENT", "ca-pub-123")
    html = webpage.privacy_page("now")
    assert html.count("adsbygoogle") >= 2 and "ca-pub-123" in html


def test_writeups_and_conference_filter():
    import writeup
    rat = {1: {"rating": 1.10, "offense": 0.56, "defense": 0.54, "sos": 0.01, "ppg": 80, "blend": 1.0},
           2: {"rating": 1.00, "offense": 0.50, "defense": 0.50, "sos": -0.01, "ppg": 70, "blend": 0.5},
           3: {"rating": 1.05, "offense": 0.52, "defense": 0.53, "sos": 0.0, "ppg": 75, "blend": 1.0}}
    rk = writeup.ranks(rat)
    assert rk[1]["rank"] == 1 and rk[2]["rank"] == 3 and rk[1]["off"] == 1 and rk[3]["def"] == 2
    row = {"away_id": "2", "home_id": "1", "away": "Army", "home": "Duke", "pick": "Duke",
           "differential": f"{0.10 + 2.7 / 170:.4f}", "total": "150.0", "neutral": "", "game_key": "k"}
    wu = writeup.game_writeup(row, rat, rk, {"fav": "Duke", "spread": 12.5, "total": 140})
    assert wu["headline"].startswith("Duke comfortably") and wu["away_rank"] == 3 and wu["home_rank"] == 1
    text = " ".join(wu["lines"])
    assert "Duke rates 1st of 3 teams" in text and "offense" in text and "Home court adds" in text
    assert "spread value is on Duke" in text and "the Over is the play" in text and "last season" in text
    assert "spread value is on Army +12.5" in " ".join(writeup.game_writeup(row, rat, rk, {"fav": "Duke", "spread": 12.5, "total": 140}, scale=0.3)["lines"])
    assert writeup.game_writeup(dict(row, home_id="9"), rat, rk) is None
    assert "new to Division I" not in text
    # the write-up says which of its sentences is about the spread and which about the over/under...
    assert wu["lines"][wu["about"]["spread"]].startswith("The books have Duke by 12.5")
    assert wu["lines"][wu["about"]["total"]].startswith("Projected total 150 vs an over/under of 140")
    assert writeup.game_writeup(row, rat, rk)["about"] == {"spread": None, "total": None}       # no line: no such sentences
    # ...so the Game of the day card, with room for five reasons, never drops the one behind its own bet
    assert len(wu["lines"]) > 5 and wu["about"]["total"] >= 5                     # the first five alone would lose it
    under = writeup.for_bet(wu, "Total")["lines"]
    assert len(under) == 5 and under[-1].startswith("Projected total") and not any("spread value" in x for x in under)
    side = writeup.for_bet(wu, "Spread")["lines"]
    assert len(side) == 5 and side[-1].startswith("The books have") and not any("Projected total" in x for x in side)
    assert writeup.for_bet(wu, "ML")["lines"] == side and under[:4] == side[:4] == wu["lines"][:4]
    short = dict(wu, lines=wu["lines"][:3])
    assert writeup.for_bet(short, "Total") is short and writeup.for_bet(None, "Total") is None   # fits already / unrated team
    assert writeup.for_bet({"lines": list("abcdefg")}, "Total")["lines"] == list("abcde")       # no positions known: the first five
    rat[2].update(new_team=True, blend=0.25)                     # Army as a first-year D-I team
    newbie = " ".join(writeup.game_writeup(row, rat, rk)["lines"])
    assert "Army is new to Division I" in newbie and "last season\u2019s" not in newbie   # no "75% last season" claim for it
    rat[2].pop("new_team"); rat[2]["blend"] = 0.5
    teams = {"1": {"conf": "ACC", "abbr": "DUKE"}, "2": {"conf": "Patriot"}}
    html = site.today_page([dict(_r(), game_key="k", away_id="2", home_id="1", away="Army", home="Duke", pick="Duke")],
                           "x", "now", "note", teams, writeups={"k": wu})
    assert 'data-conf="ACC|Patriot"' in html and 'data-top25="1"' in html and ">#1<" in html
    assert '<option value="ACC">ACC (1)</option>' in html and "Top 25 (1)" in html
    assert "Why Duke?" in html and "spread value is on Duke" in html


def test_game_of_day_and_share_image(tmp_path):
    import share
    rows = [dict(_r(), game_key="a", differential="0.1500"), dict(_r(), game_key="b", differential="0.0100"),
            dict(_r(), game_key="c", differential="0.0100")]
    wus = {"a": {"away_rank": 1, "home_rank": 2}, "b": {"away_rank": 1, "home_rank": 2}, "c": {"away_rank": 40, "home_rank": 3}}
    assert share.game_of_day(rows, wus)["game_key"] == "b"          # best teams, then the closer game
    assert share.game_of_day(rows, {}) is None
    wu = {"away_rank": 5, "home_rank": 12, "headline": "Home U by 7", "lines": ["one", "two"]}
    p = share.share_image(tmp_path / "og.png", "Wednesday, Nov 4", rows[1], wu, {}, (70, 77), (17, 2))
    from PIL import Image
    assert Image.open(p).size == (1200, 630)
    share.share_image(tmp_path / "og2.png", "Wednesday, Nov 4")        # off day
    html = site.today_page(rows, "x", "now", "note", {}, "2026-11-04", writeups={"b": wu}, gotd=rows[1])
    assert "Game of the day" in html and "#5" in html and "Projected winner: <b>Home St</b>" in html and "<li>one</li>" in html
    assert 'property="og:image"' in html and 'rel="icon"' in html


def test_game_page_and_caption():
    import video
    r = dict(_r(), date="2026-11-04", game_key="k", when="Nov 4, 2026 8:00 PM ET", start="2026-11-04T20:00:00-05:00")
    assert site.game_path(r) == "games/2026-11-04/away-u-vs-home-st.html"
    wu = {"headline": "Home St by 3", "lines": ["reason one"], "away_rank": 50, "home_rank": 20}
    html = site.game_page(r, {}, wu, "now")
    assert "Away U vs Home St prediction" in html and "reason one" in html and 'href="../../index.html"' in html
    assert '"@type": "SportsEvent"' in html and "Breakdown" not in html
    done = dict(r, away_pts="70", home_pts="65", pick_correct="0")
    html = site.game_page(done, {}, wu, "now")
    assert "Missed." in html and "Away U won 70-65" in html and "(70-65) result" in html
    cap = video.caption(r, wu, (66, 69))
    # built for search: the phrase people type comes first, then the call, then five specific tags
    assert cap.splitlines()[0].startswith("Away U vs Home St prediction")
    assert "The model has Home St winning 69-66." in cap and "Model ranks: Away U #50, Home St #20." in cap
    assert cap.splitlines()[-1] == "#awayubasketball #homestbasketball #collegebasketball #cbb #collegehoops"
    assert "tipoffedge.com" in cap and video.flagged(cap) == []
    page = site.today_page([r], "x", "now", "note", {}, "2026-11-04", writeups={"k": wu}, gotd=r, caption=cap)
    assert "daily.mp4" not in page and "Copy caption" not in page and "Full breakdown" in page   # public page: no clip box
    studio = site.studio_page("now", "x", r, {}, wu, cap, (17, 2))
    assert 'href="daily.mp4"' in studio and "Copy caption" in studio and "noindex" in studio and "17-2" in studio


def test_favorites_markup():
    html = site.today_page([_r(date="2026-11-04", game_key="k")], "x", "now", "note", {}, "2026-11-04")
    assert 'data-teams="1|2"' in html and html.count('class="fav" data-tid=') == 2
    assert 'data-f="fav"' in html and "te_favs" in html and 'data-empty="fav"' in html
    done = dict(_r(), date="2026-11-02", away_pts="60", home_pts="70", pick_correct="1", total_error="1.0")
    res = site.results_page([done], "now", {})
    assert 'data-res="W"' in res and 'data-f="fav"' in res


def test_live_page_data():
    teams = {"1": {"espn": "10"}, "2": {"espn": "20"}}
    r = _r(date="2026-11-04", game_key="k", differential="0.05", total="150.0")
    html = site.live_page([r, _r(away_id="7", home_id="8")], teams, "now", "2026-11-04", "x")
    data = json.loads(html.split('id="live-data">')[1].split("</script>")[0])
    assert data["date"] == "2026-11-04" and len(data["games"]) == 1              # team without an ESPN id is skipped
    g = data["games"][0]
    assert g["m"] == 8.5 and g["hl"] == -4.5 and g["ou"] == 145.5 and g["lineTxt"] == "Home St \u22124.5"
    assert "Live calls" in html and 'href="live.html" class="on"' in html


def test_bet_pills_on_today_page():
    bet = {"kind": "Spread", "side": "away", "label": "Away U +4.5", "odds": -110, "chance": 0.63, "edge": 0.1, "num": 4.5,
           "away_id": "1", "home_id": "2", "away": "Away U", "home": "Home St", "when": "x"}
    r = _r(date="2026-11-04", game_key="k")
    html = site.today_page([r], "x", "now", "note", {}, "2026-11-04", gotd=r, bets_by_game={"k": bet})
    assert html.count("Away U +4.5") >= 2 and "Today’s best bet" in html and 'betpill strong' in html
    # a day with lines but nothing worth a bet, and a morning before any line is posted: the card says which
    none = site.today_page([r], "x", "now", "note", {}, "2026-11-04", gotd=r)
    assert "No bet today" in none and "line already prices it in" not in none and 'data-kind="' not in none
    early = dict(r, line_fav="", line_spread="", line_total="")
    assert "Not posted yet" in site.today_page([early], "x", "now", "note", {}, "2026-11-04", gotd=early)


def test_game_of_the_day_is_the_days_top_bet():
    """The card at the top of the Today page is the game behind the day's top bet, not the biggest
    matchup on the slate, and it follows that bet to its result."""
    import build
    teams = {"1": {"espn": "2547"}, "2": {"espn": "2856"}, "3": {"espn": "356"}, "4": {"espn": "150"}}
    big = _r(date="2026-11-17", game_key="2026-11-17|3|4", away_id="3", home_id="4", away="Duke", home="Kansas",
             pick="Kansas", line_fav="Kansas")
    small = _r(date="2026-11-17", game_key="2026-11-17|1|2", when="Nov 17, 2026 7:00 PM ET")
    book = [_book_row(2, away_id="3", home_id="4", away="Duke", home="Kansas", label="Kansas ML"),
            _book_row(1, kind="Spread", side="away", label="Away U +4.5", num="4.5", odds="-110", chance="0.630", edge="0.110"),
            _book_row(1, date="2026-11-16", label="Old ML", result="L")]
    live = {"kind": "ML", "side": "home", "label": "Kansas ML", "odds": -140, "chance": 0.66, "edge": 0.08, "num": None,
            "away_id": "3", "home_id": "4", "away": "Duke", "home": "Kansas", "when": "x"}
    f = build.bet_of_the_day(book, "2026-11-17", [live], [big, small])
    assert f["row"] is small and f["bet"]["label"] == "Away U +4.5" and f["final"] == ""       # the locked #1, whatever the board says now
    assert (f["bet"]["odds"], f["bet"]["chance"], f["bet"]["edge"]) == (-110, 0.63, 0.11)
    assert build.bet_of_the_day([], "2026-11-17", [live], [big, small])["row"] is big          # before the lock: the best bet on the board
    assert build.bet_of_the_day([], "2026-11-17", [], [big, small]) is None                    # a day with nothing to bet
    assert build.bet_of_the_day(book, "2026-11-17", [], [big]) is None                         # its game is not on the slate
    html = site.today_page([big, small], "x", "now", "note", teams, "2026-11-17", gotd=big, feature=f)
    card = html.split('<section class="gotd"')[1].split("</section>")[0]
    assert html.count('<span class="kicker">Game of the day</span>') == 1
    assert "Away U" in card and "Home St" in card and "Kansas" not in card                     # the bet's game, not Duke-Kansas
    assert "Today’s best bet" in card and "Away U +4.5 <i>−110</i>" in card and "63% model chance, +11 pts edge" in card
    assert 'data-ea="2547" data-eh="2856" data-kind="Spread" data-side="away" data-num="4.5" data-res=""' in card
    assert '<div class="gst" hidden></div>' in card and 'href="bets.html"' in card and "6:00 PM CT" in card
    assert "including Duke vs Kansas" in html                                                  # search description: still the big game
    # once a build has graded it the card shows the result, and the page's script leaves it alone
    done = dict(small, away_pts="70", home_pts="72", pick_correct="1")
    won = build.bet_of_the_day([dict(book[1], result="W")], "2026-11-17", [live], [big, done])
    assert won["row"] is done and won["final"] == "70-72" and won["bet"]["result"] == "W"
    html = site.today_page([big], "x", "now", "note", teams, "2026-11-17", gotd=big, feature=won)
    assert 'class="gbet top W"' in html and '<span class="res W">Won</span><em>Final 70-72</em>' in html and 'data-res="W"' in html
    lost = site.gotd_card(done, teams, None, 70, 72, bet=dict(won["bet"], result="L"), top=True, final="70-72")
    assert 'class="gbet top L"' in lost and '<span class="res L">Lost</span>' in lost
    # the script: live score while the game is on, then the same three rules as bets.grade_bet
    js = site.JS
    assert "const gd=document.querySelector('.gotd[data-ea]');" in js and "if(gd&&!gd.dataset.res){" in js
    assert "k==='Total'?(a+h-n)*(s==='over'?1:-1):(s==='home'?h-a:a-h)+(k==='Spread'?n:0)" in js
    assert "(r==='W'?'Won':r==='L'?'Lost':'Push')" in js and "'Final '+a+'-'+h" in js
    # an older build.py hands over no top bet: the card takes the best bet among the games still open
    mine = dict(live, label="Home St ML", away_id="1", home_id="2", away="Away U", home="Home St", edge=0.2)
    old = site.today_page([big, small], "x", "now", "note", teams, "2026-11-17", gotd=big,
                          bets_by_game={big["game_key"]: live, small["game_key"]: mine})
    assert "Home St ML" in old.split('<section class="gotd"')[1].split("</section>")[0]
    # the private posting page shows the clip's game, which is this same game, with no bet box
    page = site.studio_page("now", "x", small, teams, None, "cap", matches_site=True)
    studio = page.split('<section class="gotd"')[1].split("</section>")[0]
    assert '<span class="kicker">Game of the day clip</span>' in studio and "Away U" in studio
    assert "best bet" not in studio and "gbet" not in studio and 'href="daily.mp4"' in page
    plain = site.studio_page("now", "x", big, teams, None, "cap")                        # the build did not say it is the same game
    assert '<span class="kicker">Today’s clip</span>' in plain and "Game of the day clip" not in plain
    waiting = site.studio_page("now", "x", small, teams, None, "")                       # no clip rendered for today yet
    assert "not ready yet" in waiting and 'href="daily.mp4"' not in waiting and "Copy caption" not in waiting
    assert "Game of the day</b>The game behind the day’s top bet" in html                # explained in "How to read this page"


def test_bet_guards_big_spreads_and_bad_data():
    import bets
    assert not bets.qualifies({"kind": "Spread", "odds": -110, "chance": 0.7, "edge": 0.17, "num": 18.5})
    assert not bets.qualifies({"kind": "Spread", "odds": -110, "chance": 0.7, "edge": 0.17, "num": "-10"})
    assert bets.qualifies({"kind": "Spread", "odds": -110, "chance": 0.6, "edge": 0.07, "num": 6.5})
    r = {"away_id": "1", "home_id": "2", "away": "New U", "home": "FIU", "pick": "New U", "differential": "0.2771",
         "total": "160", "when": "x"}
    assert bets.game_bets(r, {"fav": "FIU", "spread": 14.5, "total": 158.5}, {"scale": 1.5, "total_shift": 0}) == []


# ---------------- Nov 17, 2026 tune-up ----------------
def test_last_season_leans_harder_on_schedule(monkeypatch):
    import build
    base = lambda: {"offense": .57, "defense": .45, "rating": 1.02, "ppg": 70.0, "name": "x"}  # noqa: E731
    games = [("W", "S", 50, 80, True), ("A", "S", 65, 70, True), ("B", "W", 70, 65, True)]
    one, two = {k: base() for k in "ABSW"}, {k: base() for k in "ABSW"}
    model.schedule_adjust(one, games)                                   # this season: config.SOS_WEIGHT
    model.schedule_adjust(two, games, config.SOS_WEIGHT_PREV)           # the carried-over season
    ratio = config.SOS_WEIGHT_PREV / config.SOS_WEIGHT
    assert ratio == pytest.approx(2.0)
    for t in "AB":
        assert two[t]["sos"] == pytest.approx(one[t]["sos"])            # same schedule strength...
        assert two[t]["rating"] - 1.02 == pytest.approx(ratio * (one[t]["rating"] - 1.02))   # ...counted twice as hard
    # the build asks for the heavier weight for last season only
    calls = []
    monkeypatch.setattr(build, "season_ratings", lambda season, today, sos_weight=None: calls.append((season, sos_weight)))
    with pytest.raises(SystemExit):
        build.current_ratings(date(2026, 11, 18))
    assert calls == [(2027, None), (2026, config.SOS_WEIGHT_PREV)] and config.SOS_WEIGHT_PREV == 2.0


def test_search_addresses_and_titles(tmp_path):
    r = dict(_r(), date="2026-11-04", game_key="k", when="Nov 4, 2026 8:00 PM ET")
    today = site.today_page([r], "Wednesday, Nov 4", "Nov 04, 2026 03:24 AM CT", "note", {}, "2026-11-04", gotd=r)
    assert "<title>College Basketball Predictions Today, Nov 4 | " in today
    assert f'<link rel="canonical" href="{config.SITE_URL}/">' in today and f'property="og:url" content="{config.SITE_URL}/"' in today
    assert "the college basketball game on Wednesday, Nov 4, including Away U vs Home St" in today
    assert "College basketball predictions for the one game today" in today and '"@type": "WebSite"' in today
    assert "<title>College Basketball Predictions Today | " in site.today_page([], "x", "now", "note")   # no date given
    assert f'<link rel="canonical" href="{config.SITE_URL}/results.html">' in site.results_page([], "now")
    import bets
    assert "<title>College Basketball Best Bets Today, Nov 4 | " in site.bets_page(bets.best([], {}), "x", "now", {}, [], "2026-11-04")
    # an older game page that named the Today tab as its address gets its own address back, once
    old = tmp_path / "games" / "2026-11-03" / "a-vs-b.html"
    old.parent.mkdir(parents=True)
    old.write_text(f'<head><link rel="canonical" href="{config.SITE_URL}/index.html">'
                   f'<meta property="og:url" content="{config.SITE_URL}/index.html"></head>', encoding="utf-8")
    assert site.fix_canonicals(tmp_path) == 1 and site.fix_canonicals(tmp_path) == 0
    own = f"{config.SITE_URL}/games/2026-11-03/a-vs-b.html"
    assert f'rel="canonical" href="{own}"' in old.read_text() and f'og:url" content="{own}"' in old.read_text()
    # sitemap: bare domain for the home page, dates on the daily pages and the game pages
    site.write("i", "r", "b", docs=tmp_path, stamp="Nov 04, 2026 03:24 AM CT", live_html="l")
    sm = (tmp_path / "sitemap.xml").read_text()
    assert f"<loc>{config.SITE_URL}/</loc><lastmod>2026-11-04</lastmod>" in sm
    assert f"<loc>{own}</loc><lastmod>2026-11-04</lastmod>" in sm and f"<loc>{config.SITE_URL}/about.html</loc></url>" in sm


def test_analytics_hook(monkeypatch):
    monkeypatch.setattr(config, "CF_ANALYTICS_TOKEN", "", raising=False)
    assert "cloudflareinsights" not in site.about_page("now") and "Visit counts" not in site.privacy_page("now")
    monkeypatch.setattr(config, "CF_ANALYTICS_TOKEN", " 0123456789abcdef0123456789abcdef ", raising=False)
    html = site.about_page("now")
    assert html.count("static.cloudflareinsights.com/beacon.min.js") == 1
    snippet = ("<!-- Cloudflare Web Analytics --><script type='module' src='https://static.cloudflareinsights.com/beacon.min.js' "
               """data-cf-beacon='{"token": "0123456789abcdef0123456789abcdef"}'></script><!-- End Cloudflare Web Analytics -->""")
    assert snippet + "</body></html>" in html                                    # Cloudflare's own snippet, last thing on the page
    assert "Visit counts" in site.privacy_page("now") and "My teams" in site.privacy_page("now")
    assert "cloudflareinsights" not in site.studio_page("now", "x")              # the private page is not counted


def test_older_game_pages_get_the_counter(tmp_path, monkeypatch):
    old = tmp_path / "games" / "2026-11-03" / "a-vs-b.html"
    old.parent.mkdir(parents=True)
    old.write_text("<html><body><p>game</p></body></html>", encoding="utf-8")
    monkeypatch.setattr(config, "CF_ANALYTICS_TOKEN", "", raising=False)
    assert site.add_beacon(tmp_path) == 0 and "beacon" not in old.read_text()   # tracking off: untouched
    monkeypatch.setattr(config, "CF_ANALYTICS_TOKEN", "aaaa1111", raising=False)
    assert site.add_beacon(tmp_path) == 1 and site.add_beacon(tmp_path) == 0     # added once
    html = old.read_text()
    assert html.count("beacon.min.js") == 1 and html.endswith("<!-- End Cloudflare Web Analytics --></body></html>")
    assert '"token": "aaaa1111"' in html
    monkeypatch.setattr(config, "CF_ANALYTICS_TOKEN", "bbbb2222", raising=False)  # a new token replaces the old counter
    assert site.add_beacon(tmp_path) == 1
    html = old.read_text()
    assert html.count("beacon.min.js") == 1 and '"token": "bbbb2222"' in html and "aaaa1111" not in html
    assert html.count("<!-- Cloudflare Web Analytics -->") == 1


# ---------------- the daily clip and what it may say ----------------
def _clip_game(**kw):
    g = dict(_r(), date="2026-11-17", game_key="k", when="Nov 17, 2026 7:00 PM ET", away="Illinois", home="Duke", pick="Duke",
             differential="0.0300", away_id="1", home_id="2")
    g.update(kw)
    return g


def test_betting_words_never_reach_the_clip_or_caption():
    import video
    for bad in ("Duke -8.5 is the play", "take the over", "Vegas likes Duke", "best bets today", "+150 on the moneyline",
                "lock of the day", "the books have Duke", "against the spread", "3-leg parlay", "Duke covers", "5 units",
                "odds are", "DraftKings", "our top picks", "pick'em", "the line moved", "O/U 150.5", "can't lose"):
        assert video.flagged(bad), bad
    for ok in ("Illinois vs Duke prediction", "The model has Duke winning 78-73.", "tipoffedge.com", "Tipoff Edge", "SLIGHT EDGE",
               "BY 5", "TUE NOV 17", "TIP-OFF 6:00 PM CT", "Bethune-Cookman", "the overall record", "#3 AGAINST #6", "POINTS FOR HOME COURT"):
        assert video.flagged(ok) == [], ok
    wu = {"headline": "Duke by 5 in a close one", "away_rank": 6, "home_rank": 3, "n": 366,
          "lines": ["The books have Duke by 8.5; the model likes Duke by more than that, so the spread value is on Duke \u22128.5."],
          "facts": {"unit": "defense", "unit_rank": 1, "vs_rank": 2}}
    teams = {"1": {"abbr": "ILL", "color": "ff5f05"}, "2": {"abbr": "DUKE", "color": "013088"}}
    for g, pred in ((_clip_game(), (73, 78)), (_clip_game(neutral="1"), (73, 78)),
                    (_clip_game(pick="Illinois", differential="0.0050"), (75, 74)),
                    (_clip_game(away="Texas A&M-Corpus Christi", home="St. Thomas-Minnesota", pick="St. Thomas-Minnesota"), (60, 81)),
                    (_clip_game(), (None, None))):
        words = video.clip_text(g, wu, teams, pred, "Tuesday, Nov 17")
        assert words and all(video.flagged(w) == [] for w in words), [w for w in words if video.flagged(w)]
        assert not any("pick" in w.lower() or "bet" in w.lower().split() for w in words)
        cap = video.caption(g, wu, pred)
        assert video.flagged(cap) == [] and cap.splitlines()[0] == f"{g['away']} vs {g['home']} prediction \U0001F3C0"
        tags = cap.splitlines()[-1].split()
        assert len(tags) == 5 and all(t.startswith("#") and t[1:].isalnum() for t in tags)
    # the write-up's sentence about the betting line never makes it into the clip
    assert not any("books" in w.lower() or "spread" in w.lower() for w in video.clip_text(_clip_game(), wu, teams, (73, 78), "Tuesday, Nov 17"))
    # hashtags: the two schools first (short names get "basketball"), nothing generic like #fyp
    assert video.hashtags(_clip_game()) == "#illinoisbasketball #dukebasketball #collegebasketball #cbb #collegehoops"
    assert video.hashtags(_clip_game(away="Texas A&M-Corpus Christi")).split()[0] == "#texasamcorpuschristi"


def test_clip_cards_and_frames():
    import video
    wu = {"headline": "Duke by 5", "away_rank": 6, "home_rank": 3, "n": 366, "lines": [], "facts": {"unit": "defense", "unit_rank": 1, "vs_rank": 2}}
    teams = {"1": {"abbr": "ILL", "color": "ff5f05"}, "2": {"abbr": "DUKE", "color": "013088"}}
    c = video.Clip(_clip_game(), wu, teams, (73, 78), "Tuesday, Nov 17", render=False)
    assert c.stamp == ["DUKE", "WINS"] and c.by == "BY 5" and (c.level, c.level_word) == (2, "SLIGHT EDGE")
    assert c.cards == [("#3", "DUKE IN THE MODEL", "ILLINOIS IS #6 OF 366"), ("#1", "DUKE DEFENSE", "AGAINST THE #2 OFFENSE"),
                       (f"{config.HOME_COURT_POINTS:g}", "POINTS FOR HOME COURT", "DUKE PLAYS AT HOME")]
    assert c.date == "TUE NOV 17" and c.tip == "TIP-OFF 6:00 PM CT" and c.unsafe == []
    # the lower-ranked team picked on the road at a toss-up: no boast about ranks, no signed numbers
    road = video.Clip(_clip_game(pick="Illinois", differential="0.0050"), dict(wu, away_rank=40, home_rank=12, facts={}), teams,
                      (75, 74), "Tuesday, Nov 17", render=False)
    assert road.cards[0] == ("EVEN", "CLOSE IN THE MODEL", "#40 AGAINST #12") and road.cards[-1][0] == "ROAD" and road.by == "BY A BUCKET"
    assert video.Clip(_clip_game(neutral="1"), wu, teams, (73, 78), "x", render=False).cards[-1] == ("0", "HOME COURT EDGE", "NEUTRAL SITE GAME")
    assert video.name_lines("Texas A&M-Corpus Christi") == ["TEXAS A&M-", "CORPUS CHRISTI"] and video.name_lines("Duke") == ["DUKE"]
    assert video.tone((1, 48, 136))[2] > 180 and video.tone((0, 0, 0)) == video.tone((20, 20, 20))        # navy lifted, black -> grey
    # two blue teams: one side turns silver so the split still reads
    same = video.Clip(_clip_game(), wu, {"1": {"color": "003087"}, "2": {"color": "013088"}}, (73, 78), "x", render=False)
    assert same.col[0] == (226, 230, 238) and same.col[1] != same.col[0]
    # every scene draws without error, at full size, with or without logos and write-up
    full = video.Clip(_clip_game(), wu, teams, (73, 78), "Tuesday, Nov 17")
    for t in (0.0, 0.5, 2.6, 4.0, 4.92, 5.9, 8.5, 11.5):
        im = full.frame(t)
        assert im.size == (1080, 1920) and im.mode == "RGB"
    bare = video.Clip(_clip_game(away="Texas A&M-Corpus Christi"), None, {}, (None, None), "")
    assert bare.frame(1.5).size == (1080, 1920) and bare.frame(5.5).size == (1080, 1920) and bare.frame(8.0).size == (1080, 1920)


# ---------------- robots.txt, live Best Bets, night score updates ----------------
def test_robots_file_names_nothing_private(tmp_path):
    site.write("<html></html>", "<html></html>", "<html></html>", tmp_path, "Nov 18, 2026 10:00 AM CT", studio_html="<html></html>")
    robots = (tmp_path / "robots.txt").read_text()
    assert robots == f"User-agent: *\nAllow: /\nSitemap: {config.SITE_URL}/sitemap.xml\n"
    assert "Disallow" not in robots and "studio" not in robots and "daily.mp4" not in robots
    assert (tmp_path / config.STUDIO_PAGE).exists()                                    # the page is still made...
    assert config.STUDIO_PAGE not in (tmp_path / "sitemap.xml").read_text()            # ...and still listed nowhere
    assert 'content="noindex,nofollow"' in site.studio_page("now", "x")                # it keeps itself out of search


def _book_row(rank, **kw):
    b = {"date": "2026-11-17", "rank": str(rank), "kind": "ML", "side": "home", "label": "Home ML", "odds": "-130",
         "chance": "0.650", "edge": "0.085", "num": "", "away_id": "1", "home_id": "2", "away": "Away U", "home": "Home St",
         "when": "Nov 17, 2026 7:00 PM ET", "locked_at": "Nov 17, 2026 08:45 AM CT", "result": ""}
    b.update(kw)
    return b


def test_best_bets_rows_follow_their_games():
    import bets
    teams = {"1": {"espn": "2547"}, "2": {"espn": "2856"}, "3": {"espn": "356"}, "4": {"espn": "150"}}
    book = [_book_row(1, kind="Spread", label="Home St +9.5", num="9.5", odds="-110"),
            _book_row(2, kind="Total", side="under", label="Under 163.5", num="163.5", odds="-110", away_id="3", home_id="4"),
            _book_row(3, kind="ML", side="away", label="Away U ML", result="W"),
            _book_row(1, date="2026-11-16", label="Old ML", result="L")]
    empty = bets.best([], {})
    finals = {("2026-11-17", "1", "2"): "83-54", ("2026-11-16", "1", "2"): "61-70"}
    html = site.bets_page(empty, "Tuesday, Nov 17", "now", teams, book, "2026-11-17", finals)
    assert '<div class="singles" id="bets-live" data-day="2026-11-17">' in html and 'id="bets-sub"' in html
    today, past = html.split('id="bets-live"')[1].split('class="singles past"')
    # what the page's script needs to follow each game and grade the bet the way bets.grade_bet does
    assert ('data-ea="2547" data-eh="2856" data-kind="Spread" data-side="home" data-num="9.5" data-res=""') in today
    assert ('data-ea="356" data-eh="150" data-kind="Total" data-side="under" data-num="163.5" data-res=""') in today
    assert 'data-kind="ML" data-side="away" data-num="" data-res="W"' in today
    assert '<span class="res W big">W</span><small class="fin">Final 83-54</small>' in today    # graded by a build: score shown
    assert 'data-ea="' not in past and '<span class="res L big">L</span><small class="fin">Final 61-70</small>' in past
    assert "1-0 so far, 2 still to play" in html
    fresh = [dict(b, result="") for b in book]                                          # nothing graded yet: when the bets locked
    assert '<span id="bets-sub">locked in at 8:45 AM CT</span>' in site.bets_page(empty, "x", "now", teams, fresh, "2026-11-17")
    js = site.BETS_JS
    assert js in html and "site.api.espn.com" in js and "t.completed===true" in js and "et(5)" in js
    # the same three rules as bets.grade_bet: total, spread (points added to the side), moneyline
    assert "k==='Total'?(a+h-n)*(s==='over'?1:-1):(s==='home'?h-a:a-h)+(k==='Spread'?n:0)" in js
    # no script when there is nothing locked to follow: preview list, or a day with no bets
    assert site.BETS_JS not in site.bets_page(empty, "x", "now", teams, book, "2026-11-18")
    assert site.BETS_JS not in site.bets_page(empty, "x", "now", {})
    assert site._status(_from := site._from_book(_book_row(1, result="P")), "70-70").count("Push") == 1 and _from["odds"] == -130


def test_today_page_live_scores_run_through_the_night():
    # after midnight Eastern the page keeps following last evening's late games until 5 AM Eastern,
    # and a postponed game (ESPN: state "post" but not completed) is never shown as a final
    assert "const lateNight=box&&!isToday&&box.dataset.date===etDay(5);" in site.JS
    assert "if(!isToday&&!lateNight)return;" in site.JS and "box.dataset.date<etDay(5)" in site.JS
    assert "done:st.completed===true" in site.JS and "if(m.state!=='in'&&!m.done){" in site.JS


def test_api_allowance_is_recorded(monkeypatch):
    from requests.structures import CaseInsensitiveDict      # what a real response's headers are

    class R:
        def __init__(self, code, headers=None, text="[]"):
            self.status_code, self.headers, self.text = code, CaseInsensitiveDict(headers or {}), text

        def json(self):
            return json.loads(self.text)
    monkeypatch.setenv("CBBD_API_KEY", "k")
    monkeypatch.setattr(fetch.time, "sleep", lambda s: pytest.fail("no waiting expected"))
    monkeypatch.setattr(fetch, "CALLS_LEFT", None)
    calls = []

    def get(url, **kw):
        calls.append(url)
        return replies.pop(0)
    monkeypatch.setattr(fetch.requests, "get", get)
    replies = [R(200, {"x-calllimit-remaining": "612"})]
    assert fetch.teams() == [] and fetch.CALLS_LEFT == 612
    replies = [R(200, {})]                                   # no header: the last known count stays
    fetch.teams()
    assert fetch.CALLS_LEFT == 612
    replies = [R(429, text='{"message":"Monthly call quota exceeded."}'), R(200)]
    with pytest.raises(fetch.FetchError, match="allowance is used up"):
        fetch.teams()
    assert fetch.CALLS_LEFT == 0 and len(replies) == 1      # no retries: they cannot help until the 1st


def _site_in(tmp_path, monkeypatch):
    """Point the build at a scratch folder (data, ledger, bets book, pages)."""
    import bets, build, video
    monkeypatch.setattr(build, "DATA", tmp_path)
    monkeypatch.setattr(build, "RAW", tmp_path / "raw")
    for fn in (ledger.load, ledger.save):
        monkeypatch.setattr(fn, "__defaults__", (tmp_path / "ledger.csv",))
    monkeypatch.setattr(site.write, "__defaults__", ("", tmp_path / "docs", "", "", ""))
    monkeypatch.setattr(site, "DOCS", tmp_path / "docs")
    for fn in (bets.load_book, bets.save_book):
        monkeypatch.setattr(fn, "__defaults__", (tmp_path / "bets.csv",))
    monkeypatch.setattr(video, "daily_video", lambda *a, **k: None)
    monkeypatch.setattr(fetch, "CALLS_LEFT", None)
    return build


def test_night_score_updates(tmp_path, monkeypatch):
    """A whole night on a scratch copy: what a score update grades, what it must never touch, and
    when it makes no data call at all."""
    import bets
    from datetime import datetime
    build = _site_in(tmp_path, monkeypatch)
    stats = [stats_row(i, f"T{i}") for i in range(1, 321)]
    stats.append(stats_row(500, "Tennessee", team=unit(320, 600, 160, 200, 110, 260, 90, 860)))
    stats.append(stats_row(600, "Wofford"))
    games = [
        game(2, "2026-11-09T00:00:00Z", "T1", 1, "T2", 2, "final", 60, 70, [25, 35], [40, 30]),      # Nov 8, already final
        game(10, "2026-11-10T00:00:00Z", "Wofford", 600, "Tennessee", 500),                           # Nov 9, 7:00 PM ET
        game(11, "2026-11-10T02:30:00Z", "T3", 3, "T4", 4),                                           # Nov 9, 9:30 PM ET
        game(12, "2026-11-10T03:00:00Z", "T5", 5, "T6", 6),                                           # Nov 9, 10:00 PM ET
        game(20, "2026-11-11T00:00:00Z", "T7", 7, "T8", 8),                                           # Nov 10, 7:00 PM ET
    ]
    clock, calls = {}, {"games": [], "other": 0}

    def at(when):
        clock["now"] = datetime.strptime(when, "%Y-%m-%d %H:%M").replace(tzinfo=config.ET)
    monkeypatch.setattr(config, "now_et", lambda: clock["now"])

    def other(*a, **k):
        calls["other"] += 1
        return []

    def get_games(a, b):
        calls["games"].append((a.isoformat(), b.isoformat()))
        fetch.CALLS_LEFT = 900 - len(calls["games"])                     # what the API's header would say
        return [g for g in games if a.isoformat() <= fetch.parse_games([g])[0]["date"] <= b.isoformat()]
    monkeypatch.setattr(fetch, "team_stats", lambda s: stats if s == 2027 else [])
    monkeypatch.setattr(fetch, "lines", lambda a, b: [_gl(600, "Wofford", 500, "Tennessee",
                        [{"provider": "consensus", "spread": -9.5, "overUnder": 152.5}])])
    monkeypatch.setattr(fetch, "teams", lambda: [{"id": 500, "sourceId": "2633"}, {"id": 600, "sourceId": "2747"}])
    monkeypatch.setattr(fetch, "games", get_games)

    def run(*flags):
        monkeypatch.setattr("sys.argv", ["build.py", *flags])
        return build.main()

    def rows():
        return {r["game_key"]: r for r in ledger.load(tmp_path / "ledger.csv")}
    docs = tmp_path / "docs"

    # --- the day's regular build (10 AM Eastern, Nov 9): three picks locked, one bet in the book
    at("2026-11-09 10:00")
    run()
    assert sorted(r["away"] for r in rows().values() if r["date"] == "2026-11-09") == ["T3", "T5", "Wofford"]
    locked = {k: (r["pick"], r["differential"], r["total"], r["locked_at"]) for k, r in rows().items()}
    assert (tmp_path / "api_calls_left.txt").read_text().split()[0] == str(900 - len(calls["games"]))
    bets.save_book([_book_row(1, date="2026-11-09", away_id="600", home_id="500", away="Wofford", home="Tennessee",
                              label="Tennessee ML", when="Nov 9, 2026 7:00 PM ET")], tmp_path / "bets.csv")
    studio_before = (docs / config.STUDIO_PAGE).read_bytes()
    (docs / "og.png").write_bytes(b"share image of the day")
    (tmp_path / "caption.txt").write_text("caption of the day\n")
    monkeypatch.setattr(fetch, "team_stats", other)                      # from here on only the schedule may be downloaded
    monkeypatch.setattr(fetch, "lines", other)
    monkeypatch.setattr(fetch, "teams", other)
    n0 = len(calls["games"])

    # --- 8:30 PM Central (9:30 PM Eastern): the 7 PM game tipped 150 minutes ago; the API has it final
    games[1].update(status="final", awayPoints=60, homePoints=75, awayPeriodPoints=[28, 32], homePeriodPoints=[36, 39])
    index_before = (docs / "index.html").read_text()
    at("2026-11-09 21:10")                                               # 130 minutes after tip: too early to be worth a call
    assert run("--scores") == 0 and len(calls["games"]) == n0 and (docs / "index.html").read_text() == index_before
    at("2026-11-09 21:30")
    run("--scores")
    assert calls["games"][n0:] == [("2026-11-09", "2026-11-09")] and calls["other"] == 0      # one call: tonight's schedule
    r = rows()["2026-11-09|600|500"]
    assert (r["away_pts"], r["home_pts"], r["pick_correct"], r["fh_correct"]) == ("60", "75", "1", "1")
    assert bets.load_book(tmp_path / "bets.csv")[0]["result"] == "W"
    bets_html = (docs / "bets.html").read_text()
    assert '<span class="res W big">W</span><small class="fin">Final 60-75</small>' in bets_html and "final: 1-0" in bets_html
    assert 'data-res="W"' in bets_html and 'data-day="2026-11-09"' in bets_html
    # the Today page's Game of the day is still that bet's game (now off the list of open games), with its result
    card = (docs / "index.html").read_text().split('<section class="gotd"')[1].split("</section>")[0]
    assert "Wofford" in card and "Tennessee ML" in card and 'data-res="W"' in card
    assert '<span class="res W">Won</span><em>Final 60-75</em>' in card and "<li>" in card      # and it kept its write-up
    assert "Wofford" in (docs / "results.html").read_text() and 'data-date="2026-11-09"' in (docs / "index.html").read_text()
    assert "1 finished game now on Results" in (docs / "index.html").read_text()
    assert '<section class="early"' not in (docs / "index.html").read_text()        # a 10 PM game is still to tip: no early look yet
    assert (tmp_path / "api_calls_left.txt").read_text().split()[0] == str(900 - len(calls["games"]))
    # ...and it left the posting page, the share image, the caption and the day's stamp alone
    assert (docs / config.STUDIO_PAGE).read_bytes() == studio_before and (docs / "og.png").read_bytes() == b"share image of the day"
    assert (tmp_path / "caption.txt").read_text() == "caption of the day\n" and (tmp_path / "last_build.txt").read_text().strip() == "2026-11-09"

    # --- 9:30 PM Central: nothing else can be final yet (9:30 and 10 PM Eastern tips) -> no call, nothing written
    n1 = len(calls["games"])
    at("2026-11-09 22:30")
    assert run("--scores") == 0 and len(calls["games"]) == n1

    # --- 11:45 PM Central = 12:45 AM Eastern, Nov 10: still last evening's slate, no picks for the new day
    games[2].update(status="final", awayPoints=71, homePoints=64, awayPeriodPoints=[30, 41], homePeriodPoints=[33, 31])
    at("2026-11-10 00:45")
    run("--scores")
    # the day's last game has tipped off, so the update also downloads the next day's schedule (one more call)...
    assert calls["games"][n1:] == [("2026-11-09", "2026-11-09"), ("2026-11-10", "2026-11-10")]
    # ...and the Today page carries an early look at it, under the game that is still being played
    page = (docs / "index.html").read_text()
    look = page.split('<section class="early"')[1].split("</section>")[0]
    assert "Tuesday, Nov 10" in look and "<span>T7<" in look and "<span>T8<" in look and "not official picks yet" in look
    assert "about 3:30 AM Central" in look and 'href="#early"' in page
    assert page.index('<div class="games"') < page.index('<section class="early"') and 'data-date="2026-11-09"' in page
    assert json.loads((tmp_path / "raw" / "games_tomorrow.json").read_text())["date"] == "2026-11-10"
    got = rows()
    assert got["2026-11-09|3|4"]["away_pts"] == "71" and got["2026-11-09|5|6"]["away_pts"] == ""      # 10 PM tip: still playing
    assert not [k for k in got if k.startswith("2026-11-10")]                                         # tomorrow's game not locked
    assert (tmp_path / "last_build.txt").read_text().strip() == "2026-11-09"
    assert "<title>College Basketball Predictions Today, Nov 9 | " in (docs / "index.html").read_text()
    assert {k: (r["pick"], r["differential"], r["total"], r["locked_at"]) for k, r in got.items()} == locked   # no pick changed

    # --- the allowance: with too few calls left for the rest of the month, the update stands down
    games[3].update(status="final", awayPoints=80, homePoints=70)
    at("2026-11-10 01:20")                                               # 12:20 AM Central, 10 PM tip is 200 minutes old
    n2 = len(calls["games"])
    (tmp_path / "api_calls_left.txt").write_text("629\nnote\n")
    assert build.calls_held_back(clock["now"]) == 21 * build.CALL_RESERVE_PER_DAY == 630              # Nov 10-30
    assert run("--scores") == 0 and len(calls["games"]) == n2 and rows()["2026-11-09|5|6"]["away_pts"] == ""
    (tmp_path / "api_calls_left.txt").write_text("630\nnote\n")
    run("--scores")
    assert calls["games"][n2:] == [("2026-11-09", "2026-11-09"), ("2026-11-10", "2026-11-10")]
    assert rows()["2026-11-09|5|6"]["away_pts"] == "80"
    # every game is final now: instead of an empty page, the day's top bet with its result and the early look
    page = (docs / "index.html").read_text()
    assert "All of today's games are final." in page and 'class="empty"' not in page and 'class="stats"' not in page
    assert '<span class="res W">Won</span><em>Final 60-75</em>' in page.split('<section class="gotd"')[1].split("</section>")[0]
    assert page.index('<section class="gotd"') < page.index('class="alldone"') < page.index('<section class="early"')
    assert "<span>T7<" in page and 'href="#early"' not in page and "<title>College Basketball Predictions Today, Nov 9 | " in page

    # --- everything graded: no call; a slate that is not today's or last night's: no call
    n3 = len(calls["games"])
    at("2026-11-10 01:50")
    assert run("--scores") == 0 and len(calls["games"]) == n3
    (tmp_path / "last_build.txt").write_text("2026-11-07\n")
    assert build.slate_date(clock["now"]) is None and run("--scores") == 0 and len(calls["games"]) == n3
    (tmp_path / "last_build.txt").write_text("2026-11-09\n")

    # --- a run by hand at 12:55 AM Central (1:55 AM Eastern) is still last evening's build, not tomorrow's
    monkeypatch.setattr(fetch, "team_stats", lambda s: stats if s == 2027 else [])
    monkeypatch.setattr(fetch, "lines", lambda a, b: [])
    monkeypatch.setattr(fetch, "teams", lambda: [])
    at("2026-11-10 01:55")
    (tmp_path / "api_calls_left.txt").write_text("100\nnote\n")          # too few to spend one on an extra: the kept copy will do
    n_next = calls["games"].count(("2026-11-10", "2026-11-10"))
    run()
    assert not [k for k in rows() if k.startswith("2026-11-10")] and (tmp_path / "last_build.txt").read_text().strip() == "2026-11-09"
    assert calls["games"].count(("2026-11-10", "2026-11-10")) == n_next and "<span>T7<" in (docs / "index.html").read_text()

    # --- the overnight build (3:23 AM Central): the new day starts, last night's grades stand
    at("2026-11-10 04:23")
    run()
    got = rows()
    assert [k for k in got if k.startswith("2026-11-10")] == ["2026-11-10|7|8"]
    assert (tmp_path / "last_build.txt").read_text().strip() == "2026-11-10"
    assert (got["2026-11-09|600|500"]["home_pts"], got["2026-11-09|3|4"]["away_pts"], got["2026-11-09|5|6"]["home_pts"]) == ("75", "71", "70")
    page = (docs / "index.html").read_text()
    assert 'data-date="2026-11-10"' in page and '<section class="early"' not in page and "Early look" not in page


def test_the_clip_shows_the_game_of_the_day(tmp_path, monkeypatch):
    """The daily clip, its caption and the posting page are made for the same game as the card at the
    top of the Today page. Two days on a scratch copy, with a stand-in for the renderer."""
    import bets, video
    from datetime import datetime
    from pathlib import Path
    build = _site_in(tmp_path, monkeypatch)
    a, b = {"game_key": "a"}, {"game_key": "b"}
    assert build.clip_target(a, True, None) is a and build.clip_target(a, True, b) is a      # a bet: the clip is for its game
    assert build.clip_target(a, False, None) is a and build.clip_target(a, False, b) is b    # no bet: a clip that exists stays
    assert build.clip_target(None, False, None) is None                                       # no games: no clip
    stats = [stats_row(i, f"T{i}") for i in range(1, 321)]
    stats.append(stats_row(500, "Tennessee", team=unit(320, 600, 160, 200, 110, 260, 90, 860)))
    stats.append(stats_row(600, "Wofford"))
    games = [
        game(10, "2026-11-10T00:00:00Z", "Wofford", 600, "Tennessee", 500),      # Nov 9, 7:00 PM ET
        game(11, "2026-11-10T02:30:00Z", "T3", 3, "T4", 4),                       # Nov 9, 9:30 PM ET: the two best-ranked teams left
        game(20, "2026-11-10T17:00:00Z", "T7", 7, "T8", 8),                       # Nov 10, noon ET
        game(21, "2026-11-11T02:00:00Z", "T9", 9, "T10", 10),                     # Nov 10, 9:00 PM ET
    ]
    WT, T34, T78 = "2026-11-09|600|500", "2026-11-09|3|4", "2026-11-10|7|8"
    clock, feed, made, works = {}, {"lines": []}, [], {"yes": True}
    monkeypatch.setattr(config, "now_et", lambda: clock["now"])
    monkeypatch.setattr(fetch, "team_stats", lambda s: stats if s == 2027 else [])
    monkeypatch.setattr(fetch, "lines", lambda a, b: feed["lines"])
    monkeypatch.setattr(fetch, "teams", lambda: [])
    monkeypatch.setattr(fetch, "games", lambda a, b: [g for g in games if a.isoformat() <= fetch.parse_games([g])[0]["date"] <= b.isoformat()])

    def render(path, label, row, wu, teams, pred, **kw):                # stands in for video.daily_video
        made.append(row["game_key"])
        if not works["yes"]:
            return None                                                  # what a failed render returns: nothing written
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(("clip for " + row["game_key"]).encode())
        return Path(path)
    monkeypatch.setattr(video, "daily_video", render)

    def run(when, *flags):
        """One build at that Eastern time; returns the games a clip was rendered for (usually none or one)."""
        clock["now"] = datetime.strptime(when, "%Y-%m-%d %H:%M").replace(tzinfo=config.ET)
        monkeypatch.setattr("sys.argv", ["build.py", *flags])
        made.clear()
        assert build.main() == 0
        return list(made)
    docs = tmp_path / "docs"

    def card(page="index.html"):
        return (docs / page).read_text().split('<section class="gotd"')[1].split("</section>")[0]

    def clip_is_for(key, away, home):
        return ((tmp_path / "clip_game.txt").read_text().strip() == key and (docs / "daily.mp4").read_text() == "clip for " + key
                and (tmp_path / "caption.txt").read_text().startswith(f"{away} vs {home} prediction")
                and f">{away}<" in card(config.STUDIO_PAGE) and f">{home}<" in card(config.STUDIO_PAGE))

    # --- the overnight build, before any line is out: no bet yet, so the day's biggest matchup leads
    assert run("2026-11-09 04:23") == [T34] and clip_is_for(T34, "T3", "T4")
    assert ">T3<" in card() and "Not posted yet" in card()
    studio = (docs / config.STUDIO_PAGE).read_text()
    assert "Game of the day clip" in studio and 'href="daily.mp4"' in studio and "T3 vs T4 prediction" in studio
    assert run("2026-11-09 08:40", "--refresh") == []                    # nothing new: the clip is left alone

    # --- the lines come out and the model's best bet is in the other game (a total 18 points under its
    #     own number): the card moves there, and so does the clip
    feed["lines"] = [_gl(600, "Wofford", 500, "Tennessee", [{"provider": "consensus", "spread": -9.5, "overUnder": 140.5}])]
    assert run("2026-11-09 09:45", "--refresh") == [WT] and clip_is_for(WT, "Wofford", "Tennessee")
    assert ">Wofford<" in card() and "Today’s best bet" in card() and "Over 140.5" in card() and ">T3<" not in card()
    # the game's page gives more reasons than the card has room for; the card keeps the one behind its bet
    # (the over/under) and lets the one about the spread go
    page = (docs / "games" / "2026-11-09" / "wofford-vs-tennessee.html").read_text()
    assert page.count("<li>") > 5 and "The books have Tennessee by 9.5" in page and "the Over is the play." in page
    assert card().count("<li>") == 5 and "the Over is the play." in card() and "The books have" not in card()
    studio = (docs / config.STUDIO_PAGE).read_text()
    assert "Game of the day clip" in studio and "Wofford vs Tennessee prediction" in studio
    assert "best bet" not in card(config.STUDIO_PAGE) and video.flagged((tmp_path / "caption.txt").read_text()) == []
    assert run("2026-11-09 11:45", "--refresh") == []                    # same game: not rendered again

    # --- the day's bets lock with another game on top: the card follows the locked #1, and the clip with it
    bets.save_book([_book_row(1, date="2026-11-09", away_id="3", home_id="4", away="T3", home="T4", label="T4 ML",
                              when="Nov 9, 2026 9:30 PM ET")], tmp_path / "bets.csv")
    assert run("2026-11-09 14:45", "--refresh") == [T34] and clip_is_for(T34, "T3", "T4")
    assert ">T3<" in card() and "T4 ML" in card()
    assert run("2026-11-09 17:45", "--refresh") == []

    # --- at night a score update renders nothing and leaves the clip, the caption and the posting page as they are
    games[0].update(status="final", awayPoints=60, homePoints=75)
    before = [(docs / config.STUDIO_PAGE).read_bytes(), (tmp_path / "caption.txt").read_bytes(), (docs / "daily.mp4").read_bytes()]
    assert run("2026-11-09 21:30", "--scores") == [] and "Wofford" in (docs / "results.html").read_text()
    assert before == [(docs / config.STUDIO_PAGE).read_bytes(), (tmp_path / "caption.txt").read_bytes(), (docs / "daily.mp4").read_bytes()]
    # ...and a run by hand makes the clip again, for the same game (how a new clip design gets onto the page)
    assert run("2026-11-09 22:00") == [T34] and clip_is_for(T34, "T3", "T4")

    # --- next morning the render fails: yesterday's clip is not offered as today's, and the next build tries again
    feed["lines"] = []
    works["yes"] = False
    assert run("2026-11-10 04:23") == [T78]
    assert (tmp_path / "clip_game.txt").read_text().strip() == T34 and ">T7<" in card()
    studio = (docs / config.STUDIO_PAGE).read_text()
    assert "not ready yet" in studio and 'href="daily.mp4"' not in studio and "Copy caption" not in studio and ">T7<" in studio
    works["yes"] = True
    assert run("2026-11-10 09:45", "--refresh") == [T78] and clip_is_for(T78, "T7", "T8")
    assert "Game of the day clip" in (docs / config.STUDIO_PAGE).read_text()

    # --- a day with no bet: once that game is over the card moves on to the biggest game still to play,
    #     but the clip (already posted by then) stays on the game it was made for, and so does its caption
    games[2].update(status="final", awayPoints=70, homePoints=60)
    assert run("2026-11-10 17:45", "--refresh") == [] and clip_is_for(T78, "T7", "T8")
    assert ">T9<" in card() and ">T7<" not in card()
    studio = (docs / config.STUDIO_PAGE).read_text()
    assert '<span class="kicker">Today’s clip</span>' in studio and "Game of the day clip" not in studio


def test_early_look_on_the_today_page():
    """From the day's last tip-off until the overnight build the Today page adds the next day's games
    as an early look. With every game final it is what the page shows, instead of an empty box."""
    teams = {"1": {"color": "aa0000"}, "2": {"color": "0000aa"}}
    nxt = [_r(date="2026-11-21", when="Nov 21, 2026 12:00 PM ET", away_id="3", away="Road A&M", home_id="4", home="Host <U>",
              pick="Road A&M", neutral="1"),
           _r(date="2026-11-21", when="Nov 21, 2026 1:00 PM ET"),
           _r(date="2026-11-21", when="TBD", away_id="5", away="Late U", home_id="6", home="Night St", pick="Night St")]
    early = {"date": "2026-11-21", "label": "Saturday, Nov 21", "rows": nxt, "ranks": {"1": 12, "2": 3, "3": 250},
             "waiting": 2, "official": "3:30 AM"}
    look = site.early_look(early, teams)
    assert look.startswith('<section class="early" id="early"><span class="kicker">Early look</span><h2>Saturday, Nov 21</h2>')
    assert "scores for <b>3 games</b>, visitor listed first" in look and "<b>These are not official picks yet.</b>" in look
    assert "post overnight (about 3:30 AM Central)" in look and "2 more games are waiting on a matchup." in look
    # one compact row per game, in the order given: Central time, visitor on top, the projected winner marked
    pa, ph = site.predicted_score(nxt[1])
    assert pa < ph and look.count('<div class="eg"') == 3
    assert look.index("11:00 AM") < look.index("12:00 PM") < look.index("Time TBD")
    assert f'<div class="et"><span>Away U<i class="rk" title="Model rank">#12</i></span><b>{pa}</b></div>' in look
    assert f'<div class="et w"><span>Home St<i class="rk" title="Model rank">#3</i></span><b>{ph}</b></div>' in look
    assert '<div class="et w"><span>Road A&amp;M<i class="rk" title="Model rank">#250</i></span>' in look     # picked on the road
    assert "<span>Host &lt;U&gt;</span>" in look and look.count("<small>Neutral</small>") == 1                 # no rank known: none shown
    assert f'style="--pc:{site._vivid("0000aa")}"' in look                                                     # the stripe is the winner's color
    # nothing in it for the page's script to treat as one of today's games, and no line, bet, pick badge or link
    for hook in ('class="g', "data-ea", "data-slot", 'class="fav"', "<a ", "Bet", "Strong pick", "O/U", "Line"):
        assert hook not in look, hook
    assert site.early_look(None) == "" and site.early_look({"rows": []}) == "" and site.early_look({}, teams) == ""
    one = site.early_look(dict(early, rows=nxt[:1], waiting=1, official=""))
    assert "score for <b>1 game</b>" in one and "1 more game is waiting on a matchup." in one and "post overnight, and" in one

    today = [_r(date="2026-11-20", game_key="2026-11-20|1|2", when="Nov 20, 2026 11:00 PM ET")]
    # 1) a late game is still on the board: the early look goes under the list, with a link to it up top
    page = site.today_page(today, "Friday, Nov 20", "now", "note", teams, "2026-11-20", 50, early=early)
    assert page.index('<div class="games"') < page.index('<section class="early"') and 'class="stats"' in page
    assert '<a class="donelink" href="#early">Early look at Saturday, Nov 21 &darr;</a>' in page
    # 2) every game is final: the Game of the day with its result, one line about the day, then the early look
    bet = dict(_book_row(1, kind="Total", side="under", label="Under 145.5", num="145.5", odds="-110", result="W"), odds=-110, chance=0.65, edge=0.12)
    done = dict(today[0], away_pts="60", home_pts="70", pick_correct="1")
    feature = {"bet": bet, "row": done, "final": "60-70"}
    page = site.today_page([], "Friday, Nov 20", "now", "note", teams, "2026-11-20", 51, feature=feature, early=early)
    assert page.index('<section class="gotd"') < page.index('<div class="alldone">') < page.index('<section class="early"')
    assert "<b>All of today's games are final.</b>" in page and 'class="empty"' not in page and 'href="#early"' not in page
    assert 'class="stats"' not in page and "51 finished games now on Results" in page and "Under 145.5" in page
    # ...and without an early look (no games tomorrow, or the schedule could not be had) the page is as it was
    page = site.today_page([], "Friday, Nov 20", "now", "note", teams, "2026-11-20", 51)
    assert '<div class="empty"><b>All of today\'s games are final</b>' in page and 'class="stats"' in page and "Early look" not in page
    assert 'class="alldone"' not in page and '<section class="early"' not in page
    # 3) a day with no games at all: the next day's early look, all day
    page = site.today_page([], "Thursday, Dec 24", "now", "note", teams, "2026-12-24", early=early)
    assert "<b>No games today</b>" in page and page.index("No games today") < page.index('<section class="early"') and 'class="stats"' not in page
    # 4) no early look handed over (every build before the last tip-off): nothing about one anywhere
    page = site.today_page(today, "Friday, Nov 20", "now", "note", teams, "2026-11-20", 50)
    assert '<section class="early"' not in page and "Early look" not in page and 'href="#early"' not in page


def test_early_look_is_made_from_the_next_days_schedule(tmp_path, monkeypatch):
    """What the builds hand to the page: the next day's games projected with tonight's ratings, saved
    nowhere near the ledger, with one data call that the month's allowance can veto."""
    import build, writeup
    from datetime import datetime
    build = _site_in(tmp_path, monkeypatch)
    monkeypatch.setattr(build, "ROOT", tmp_path)
    now = datetime(2026, 11, 21, 0, 50, tzinfo=config.ET)                 # 11:50 PM Central on Friday the 20th
    # when is it time? Once no game on the board is still to tip.
    late = _r(when="Nov 20, 2026 11:00 PM ET")
    assert build.still_to_tip([dict(late, when="Nov 21, 2026 1:00 AM ET")], now)                 # a Hawaii tip is still ahead
    assert not build.still_to_tip([late], now) and not build.still_to_tip([], now)             # tipped (still playing) / no games today
    assert not build.still_to_tip([dict(late, when="TBD")], now)                                # no tip time to wait for
    assert not build.still_to_tip([dict(late, when="Nov 21, 2026 1:00 AM ET", away_pts="70", home_pts="60")], now)

    rat = {1: {"rating": 0.30, "ppg": 75.0}, 2: {"rating": 0.25, "ppg": 70.0}, 3: {"rating": 0.10, "ppg": 68.0},
           4: {"rating": 0.20, "ppg": 72.0}, 245: {"rating": 0.22, "ppg": 71.0}, 213: {"rating": 0.21, "ppg": 69.0}}
    rk = writeup.ranks(rat)
    sched = [game(1, "2026-11-22T00:00:00Z", "T1", 1, "T2", 2),                                  # Sat 7:00 PM ET
             game(2, "2026-11-21T17:00:00Z", "T3", 3, "T4", 4),                                  # Sat noon ET
             game(3, "2026-11-21T20:00:00Z", "T1", 1, "Elms College", 99),                       # not a rated team: no projection
             dict(game(4, "2026-11-21T22:00:00Z", "Rutgers", 245, "TBD", 1543), sourceId="401920513", neutralSite=True),
             game(5, "2026-11-22T05:30:00Z", "T4", 4, "T3", 3),                                  # 12:30 AM ET Sunday: not Saturday's
             dict(game(6, "2026-11-21T05:00:00Z", "T2", 2, "T4", 4), startTimeTbd=True)]         # tip time not announced
    asked = []

    def get_games(a, b):
        asked.append((a.isoformat(), b.isoformat()))
        return [dict(g) for g in sched]
    monkeypatch.setattr(fetch, "games", get_games)
    monkeypatch.setattr(fetch, "espn_matchups", lambda day: {})          # ESPN has not set the bracket game either
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "teams.json").write_text(json.dumps(TBD_TEAMS))
    look = build.early_look(date(2026, 11, 20), rat, rk, "2026-27", now)
    assert asked == [("2026-11-21", "2026-11-21")]                       # one call: Saturday's schedule
    assert (look["date"], look["label"], look["official"], look["waiting"]) == ("2026-11-21", "Saturday, Nov 21", "3:30 AM", 1)
    assert [r["game_key"] for r in look["rows"]] == ["2026-11-21|3|4", "2026-11-21|1|2", "2026-11-21|2|4"]      # by tip; no time last
    first = look["rows"][0]
    assert set(first) == set(ledger.FIELDS) and first["pick"] == "T4" and first["locked_at"] == "" and first["line_spread"] == ""
    assert site.predicted_score(first)[1] > site.predicted_score(first)[0] and look["ranks"]["1"] == 1 and look["ranks"]["3"] == 6
    assert not (tmp_path / "ledger.csv").exists() and not (tmp_path / "bets.csv").exists()                      # nothing is locked
    assert json.loads((tmp_path / "raw" / "games_tomorrow.json").read_text())["date"] == "2026-11-21"
    assert "<span>T3<" in site.early_look(look)                           # and the page can draw it as it comes
    # summer time: the overnight build lands an hour later by the Central clock
    assert build.early_look(date(2027, 3, 19), rat, rk, "2026-27", now) is None                 # (this schedule has no March games)
    sched.append(game(7, "2027-03-20T23:00:00Z", "T1", 1, "T2", 2))
    assert build.early_look(date(2027, 3, 19), rat, rk, "2026-27", now)["official"] == "4:30 AM"
    del sched[-1], asked[:]

    # a bracket game decided tonight: ESPN names the opponent, the game joins the list, and the find is kept
    # for the overnight build without touching today's own finds
    monkeypatch.setattr(fetch, "espn_matchups", lambda day: {"401920513": ("164", "87")} if day == date(2026, 11, 21) else {})
    look = build.early_look(date(2026, 11, 20), rat, rk, "2026-27", now)
    assert look["waiting"] == 0 and "2026-11-21|245|213" in [r["game_key"] for r in look["rows"]]
    kept = json.loads((tmp_path / "raw" / "matchups_tomorrow.json").read_text())
    assert kept["date"] == "2026-11-21" and kept["games"] == {"401920513": ["164", "87"]}
    assert not (tmp_path / "raw" / "matchups_today.json").exists()

    def turned_away(day):
        raise fetch.FetchError("ESPN scoreboard: HTTP 403")
    monkeypatch.setattr(fetch, "espn_matchups", turned_away)             # 3:23 AM: ESPN turns the machine away, the find still counts
    morning = [dict(g) for g in sched]
    assert [g["id"] for g in build.fill_tbd(morning, date(2026, 11, 21))] == [4] and morning[3]["homeTeam"] == "Notre Dame"
    assert build.fill_tbd([dict(g) for g in sched], date(2026, 11, 22)) == []                   # ...but only for its own day

    # the feed is down: the copy kept by the last build stands in, as long as it is that day's
    def down(a, b):
        asked.append("down")
        raise fetch.FetchError("/games: HTTP 503")
    monkeypatch.setattr(fetch, "games", down)
    assert len(build.early_look(date(2026, 11, 20), rat, rk, "2026-27", now)["rows"]) == 4
    assert build.early_look(date(2026, 11, 21), rat, rk, "2026-27", now) is None               # no copy for Sunday: no early look
    # the month's calls are nearly gone: no call is spent on it at all
    del asked[:]
    (tmp_path / "api_calls_left.txt").write_text("10\nnote\n")
    assert len(build.early_look(date(2026, 11, 20), rat, rk, "2026-27", now)["rows"]) == 4 and asked == []


def test_score_update_skips_postponed_and_stale_games(tmp_path, monkeypatch):
    from datetime import datetime
    build = _site_in(tmp_path, monkeypatch)
    now = datetime(2026, 11, 9, 23, 0, tzinfo=config.ET)                 # 11 PM Eastern
    row = {k: "" for k in ledger.FIELDS}

    def r(aid, when, **kw):
        return dict(row, date="2026-11-09", away_id=str(aid), home_id=str(aid + 1), when=when, **kw)
    rows = [r(1, "Nov 9, 2026 8:00 PM ET"),                              # 180 minutes ago: due
            r(3, "Nov 9, 2026 9:00 PM ET"),                              # 120 minutes: not yet
            r(5, "Nov 9, 2026 8:45 PM ET"),                              # exactly 135: due
            r(7, "Nov 9, 2026 5:30 PM ET"),                              # 330 minutes and still not final: given up on
            r(9, "Nov 9, 2026 7:00 PM ET", away_pts="70", home_pts="60"),   # graded already
            r(11, "Nov 9, 2026 7:00 PM ET"),                             # postponed in the saved schedule
            r(13, "TBD"),
            dict(r(15, "Nov 8, 2026 7:00 PM ET"), date="2026-11-08")]    # another day
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "games_today.json").write_text(json.dumps([{"awayTeamId": 11, "homeTeamId": 12, "status": "postponed"},
                                                                    {"awayTeamId": 1, "homeTeamId": 2, "status": "in_progress"}]))
    assert [x["away_id"] for x in build.due_for_a_final(rows, "2026-11-09", now)] == ["1", "5"]
    (tmp_path / "raw" / "games_today.json").write_text("not json")
    assert [x["away_id"] for x in build.due_for_a_final(rows, "2026-11-09", now)] == ["1", "5", "11"]   # no schedule to consult
    # the allowance resets on the 1st (UTC): days left x the per-day reserve
    assert build.calls_held_back(datetime(2026, 11, 30, 23, 0, tzinfo=config.ET)) == 31 * build.CALL_RESERVE_PER_DAY   # already Dec 1 in UTC
    assert build.calls_held_back(datetime(2026, 12, 31, 12, 0, tzinfo=config.ET)) == build.CALL_RESERVE_PER_DAY
    assert build.calls_left_saved() is None
    monkeypatch.setattr(fetch, "CALLS_LEFT", 432)
    build.save_calls_left("Nov 9, 2026 10:00 PM CT")
    assert build.calls_left_saved() == 432 and "as of Nov 9, 2026 10:00 PM CT" in (tmp_path / "api_calls_left.txt").read_text()


# ---------------- bracket games the data feed lists against "TBD" ----------------
TBD_TEAMS = [{"id": 245, "sourceId": "164", "school": "Rutgers", "conference": "Big Ten", "conferenceId": 10},
             {"id": 213, "sourceId": "87", "school": "Notre Dame", "conference": "ACC", "conferenceId": 2},
             {"id": 113, "sourceId": "248", "school": "Houston"}, {"id": 87, "sourceId": "57", "school": "Florida"},
             {"id": 1543, "sourceId": "-1", "school": "TBD"}, {"id": 1217, "sourceId": "-2", "school": "TBD"}]


def _tbd_rows():
    return [dict(game(1, "2026-11-18T19:00:00.000Z", "Rutgers", 245, "TBD", 1543), sourceId="401920513", neutralSite=True),
            dict(game(2, "2026-11-18T21:30:00.000Z", "TBD", 1543, "Houston", 113), sourceId="401920514"),    # open on the away side
            dict(game(3, "2026-11-19T00:30:00.000Z", "TBD", 1543, "TBD", 1217), sourceId="401920599"),        # both sides open
            dict(game(4, "2026-11-19T02:00:00.000Z", "Rutgers", 245, "TBD", 1543), sourceId="401920600"),     # ESPN has no opponent either
            dict(game(5, "2026-11-19T02:00:00.000Z", "Houston", 113, "Florida", 87), sourceId="401920601"),   # an ordinary game
            dict(game(6, "2026-11-19T03:00:00.000Z", "Rutgers", 245, "TBD", 1543), sourceId="401920602")]     # ESPN's game 602 is other teams'


def test_bracket_games_listed_against_tbd_get_their_opponent(tmp_path, monkeypatch):
    import build
    monkeypatch.setattr(build, "RAW", tmp_path / "raw")
    monkeypatch.setattr(build, "ROOT", tmp_path)
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "teams.json").write_text(json.dumps(TBD_TEAMS))
    board = {"401920513": ("164", "87"),             # Rutgers (away) vs Notre Dame (home)
             "401920514": ("248", "57"),             # ESPN has Houston as the away team; the feed has it at home
             "401920599": ("87", "57"), "401920600": ("164", "-1"), "401920601": ("248", "57"), "401920602": ("248", "57")}
    asked = []
    monkeypatch.setattr(fetch, "espn_matchups", lambda day: asked.append(day) or dict(board))
    day = date(2026, 11, 18)
    g = _tbd_rows()
    assert [x["id"] for x in build.fill_tbd(g, day)] == [1, 2, 3] and asked == [day]
    assert (g[0]["awayTeam"], g[0]["homeTeam"], g[0]["homeTeamId"], g[0]["homeConference"]) == ("Rutgers", "Notre Dame", 213, "ACC")
    assert (g[1]["awayTeam"], g[1]["awayTeamId"], g[1]["homeTeam"]) == ("Florida", 87, "Houston")     # only the open side is filled
    assert (g[2]["awayTeam"], g[2]["homeTeam"]) == ("Notre Dame", "Florida")
    assert g[3]["homeTeam"] == "TBD" and g[4]["homeTeam"] == "Florida" and g[5]["homeTeam"] == "TBD"
    first = fetch.parse_games(g)[0]
    assert (first["away_id"], first["home_id"], first["home"], first["neutral"]) == (245, 213, "Notre Dame", True)

    def turned_away(day):
        raise fetch.FetchError("ESPN scoreboard: HTTP 403")
    monkeypatch.setattr(fetch, "espn_matchups", turned_away)
    assert [x["id"] for x in build.fill_tbd(_tbd_rows(), day)] == [1, 2, 3]           # what the earlier build found is reused
    (tmp_path / "matchups.json").write_text(json.dumps({"note": "by hand", "games": {"401920600": ["164", "57"]}}))
    g = _tbd_rows()
    assert [x["id"] for x in build.fill_tbd(g, day)] == [1, 2, 3, 4] and g[3]["homeTeam"] == "Florida"   # plus the hand-made list
    monkeypatch.setattr(fetch, "espn_matchups", lambda day: pytest.fail("a schedule without TBD never asks ESPN"))
    assert build.fill_tbd([_tbd_rows()[4]], day) == [] and build.fill_tbd([], day) == []
    monkeypatch.delattr(fetch, "espn_matchups")                                        # a fetch.py from before this existed
    assert [x["id"] for x in build.fill_tbd(_tbd_rows(), day)] == [1, 2, 3, 4]         # saved finds + the list still work
    (tmp_path / "matchups.json").unlink()
    assert build.fill_tbd(_tbd_rows(), date(2026, 11, 19)) == []                       # yesterday's finds are not carried into a new day


def test_espn_schedule_reader(monkeypatch):
    class R:
        status_code = 200

        def json(self):
            return {"events": [{"id": "401920513", "competitions": [{"competitors": [{"homeAway": "home", "team": {"id": "87"}},
                                                                                     {"homeAway": "away", "team": {"id": "164"}}]}]},
                               {"id": "401920999", "competitions": [{"competitors": [{"homeAway": "home", "team": {"id": "57"}}]}]},
                               {"id": "1", "competitions": []}]}
    seen = {}

    def get(url, **kw):
        seen.update(url=url, **kw)
        return R()
    monkeypatch.setattr(fetch.requests, "get", get)
    assert fetch.espn_matchups(date(2026, 11, 18)) == {"401920513": ("164", "87")}
    assert seen["params"]["dates"] == "20261118" and "espn.com" in seen["url"] and "Authorization" not in seen["headers"]   # no key sent to ESPN
    R.status_code = 403
    with pytest.raises(fetch.FetchError, match="HTTP 403"):
        fetch.espn_matchups(date(2026, 11, 18))


def test_tbd_game_gets_a_pick_before_it_tips(tmp_path, monkeypatch):
    from datetime import datetime
    build = _site_in(tmp_path, monkeypatch)
    monkeypatch.setattr(build, "ROOT", tmp_path)
    stats = [stats_row(i, f"T{i}") for i in range(1, 321)] + [stats_row(245, "Rutgers"), stats_row(213, "Notre Dame"),
                                                               stats_row(113, "Houston"), stats_row(87, "Florida")]
    games = [dict(game(1, "2026-11-18T19:00:00.000Z", "Rutgers", 245, "TBD", 1543), sourceId="401920513", neutralSite=True),   # 2 PM Eastern
             dict(game(2, "2026-11-18T21:30:00.000Z", "Houston", 113, "TBD", 1543), sourceId="401920514", neutralSite=True),   # 4:30 PM Eastern
             game(3, "2026-11-19T00:00:00.000Z", "T1", 1, "T2", 2)]
    monkeypatch.setattr(fetch, "team_stats", lambda s: stats if s == 2027 else [])
    monkeypatch.setattr(fetch, "games", lambda a, b: [dict(g) for g in games if a.isoformat() <= fetch.parse_games([g])[0]["date"] <= b.isoformat()])
    monkeypatch.setattr(fetch, "lines", lambda a, b: [])
    monkeypatch.setattr(fetch, "teams", lambda: TBD_TEAMS)
    board = {}
    monkeypatch.setattr(fetch, "espn_matchups", lambda day: dict(board))
    clock = {}
    monkeypatch.setattr(config, "now_et", lambda: clock["now"])

    def run(when, *flags):
        clock["now"] = datetime.strptime(when, "%Y-%m-%d %H:%M").replace(tzinfo=config.ET)
        monkeypatch.setattr("sys.argv", ["build.py", *flags])
        build.main()
        return {r["game_key"]: r for r in ledger.load(tmp_path / "ledger.csv")}
    rows = run("2026-11-18 04:23")                                     # overnight: nobody knows the opponents yet
    assert list(rows) == ["2026-11-18|1|2"]
    board.update({"401920513": ("164", "87"), "401920514": ("248", "57")})
    rows = run("2026-11-18 14:45", "--refresh")                         # 1:45 PM Central: ESPN has both; the 2 PM game has tipped
    assert set(rows) == {"2026-11-18|1|2", "2026-11-18|113|87"}
    r = rows["2026-11-18|113|87"]
    assert (r["away"], r["home"], r["neutral"], r["when"]) == ("Houston", "Florida", "1", "Nov 18, 2026 4:30 PM ET") and r["pick"] in ("Houston", "Florida")
    page = (tmp_path / "docs" / "index.html").read_text()
    assert "Florida" in page and "Notre Dame" not in page               # no pick, no row, for the game already under way
    # the feed catches up before the tip, with the two teams the other way round: still one pick
    games[1].update(awayTeam="Florida", awayTeamId=87, homeTeam="Houston", homeTeamId=113)
    assert set(run("2026-11-18 15:45", "--refresh")) == {"2026-11-18|1|2", "2026-11-18|113|87"}
    # ...and when the game goes final it is graded like any other (Houston 70, Florida 66)
    games[1].update(status="final", awayPoints=66, homePoints=70, awayPeriodPoints=[33, 33], homePeriodPoints=[30, 40])
    rows = run("2026-11-18 20:45", "--refresh")
    assert set(rows) == {"2026-11-18|1|2", "2026-11-18|113|87"}                          # the caught-up feed row is the same game, not a second pick
    assert (rows["2026-11-18|113|87"]["away_pts"], rows["2026-11-18|113|87"]["home_pts"]) == ("70", "66")


# ---------------- rankings, team pages, the method page ----------------
def _league():
    """Three rated teams, best first, with the season numbers behind them and the team list."""
    rat = {1: {"name": "Alpha", "rating": 1.20, "offense": 0.62, "defense": 0.58, "sos": 0.02, "ppg": 78.0, "blend": 0.3},
           2: {"name": "Beta State", "rating": 1.10, "offense": 0.56, "defense": 0.54, "sos": 0.0, "ppg": 74.0, "blend": 0.3},
           3: {"name": "Gamma A&M", "rating": 1.00, "offense": 0.50, "defense": 0.50, "sos": -0.02, "ppg": 70.0, "blend": 0.3}}
    team = {1: dict(T, name="Alpha", GP=6, **{"FG%": 0.50, "TOV": 9.0}),
            2: dict(T, name="Beta State", GP=6, **{"FG%": 0.45, "TOV": 12.0}),
            3: dict(T, name="Gamma A&M", GP=6, **{"FG%": 0.40, "TOV": 15.0})}
    opp = {1: dict(O, **{"FG%": 0.38, "TOV": 15.0}), 2: dict(O, **{"FG%": 0.42, "TOV": 12.0}), 3: dict(O, **{"FG%": 0.46, "TOV": 9.0})}
    teams = {"1": {"mascot": "Aces", "conf": "East", "color": "112233", "logo": "", "abbr": "ALP", "espn": "11"},
             "2": {"mascot": "Bears", "conf": "East", "color": "223344", "logo": "", "abbr": "BETA", "espn": "22"},
             "3": {"mascot": "Goats", "conf": "West", "color": "334455", "logo": "", "abbr": "GAM", "espn": "33"}}
    feed = [{"teamId": 1, "wins": 5, "losses": 1, "pace": 70.2}, {"teamId": 2, "wins": 3, "losses": 3, "pace": 68.0},
            {"teamId": 3, "wins": 1, "losses": 5, "pace": 66.0}]
    return rat, team, opp, teams, feed


def _pick(day, aid, away, hid, home, pick, diff="0.0500", total="150.0", **kw):
    row = {k: "" for k in ledger.FIELDS}
    row.update(game_key=ledger.key(day, aid, hid), date=day, when="Nov 10, 2026 7:00 PM ET", away_id=str(aid), away=away,
               home_id=str(hid), home=home, pick=pick, differential=diff, total=total)
    row.update(kw)
    return row


TODAY = "2026-11-21"


def _league_schedule(rat):
    """Every kind of game a team page has to show, for the three teams of _league()."""
    import teamdata
    played = [["2026-11-10", 2, 1, 61, 80, 0],          # Beta State at Alpha (the feed later corrected Beta's 60 to 61)
              ["2026-11-12", 1, 3, 70, 71, 1],          # Alpha vs Gamma A&M on a neutral floor, listed the other way round from its pick
              ["2026-11-14", 3, 9, 50, 90, 0]]          # Gamma A&M at a school the model does not rate
    picks = [_pick("2026-11-10", 2, "Beta State", 1, "Alpha", "Alpha", "0.1000", away_pts="60", home_pts="80", pick_correct="1"),
             _pick("2026-11-12", 3, "Gamma A&M", 1, "Alpha", "Alpha", "0.0200", away_pts="71", home_pts="70", pick_correct="0", neutral="1"),
             _pick(TODAY, 2, "Beta State", 3, "Gamma A&M", "Beta State", "0.0400", when="Nov 21, 2026 8:00 PM ET")]
    week = [{"date": "2026-11-23", "when": "Nov 23, 2026 7:00 PM ET", "away_id": 3, "away": "Gamma A&M", "home_id": 1, "home": "Alpha",
             "neutral": False, "away_pts": None, "home_pts": None},
            {"date": "2026-11-25", "when": "TBD", "away_id": 1543, "away": "TBD", "home_id": 2, "home": "Beta State",
             "neutral": True, "away_pts": None, "home_pts": None},
            {"date": "2026-11-26", "when": "TBD", "away_id": None, "away": "", "home_id": 2, "home": "Beta State",
             "neutral": True, "away_pts": None, "home_pts": None}]
    names = {1: "Alpha", 2: "Beta State", 3: "Gamma A&M", 9: "Tiny College", 1543: "TBD"}
    return teamdata.schedules(rat, played, picks, TODAY, week, names), picks


def _profiles(history=None):
    import teamdata, writeup
    rat, team, opp, teams, feed = _league()
    sched, _ = _league_schedule(rat)
    return teamdata.profiles(rat, writeup.ranks(rat), team, opp, feed, teams, sched, history or {}, TODAY), teams


def test_team_page_addresses():
    import teamdata
    for name, slug in (("San José State", "san-jose-state"), ("Texas A&M", "texas-am"), ("Saint Mary's", "saint-marys"),
                       ("William & Mary", "william-mary"), ("Miami (OH)", "miami-oh"), ("Hawai'i", "hawaii"),
                       ("Texas A&M-Corpus Christi", "texas-am-corpus-christi"), ("St. John's", "st-johns"), ("", "team")):
        assert teamdata.slug(name) == slug
    assert teamdata.team_path("North Carolina A&T") == "teams/north-carolina-at.html"


def test_rating_in_points_is_the_models_margin():
    import teamdata
    rat = _league()[0]
    pts = teamdata.points(rat)
    assert [round(pts[t], 1) for t in (1, 2, 3)] == [17.0, 0.0, -17.0]          # 170 points per rating point, around the average
    g = {"away_id": 3, "home_id": 1, "away": "Gamma A&M", "home": "Alpha", "neutral": False}
    assert model.predict(g, rat, {})["margin"] == pytest.approx(pts[1] - pts[3] + config.HOME_COURT_POINTS)
    assert model.predict(dict(g, neutral=True), rat, {})["margin"] == pytest.approx(pts[1] - pts[3])
    assert teamdata.points({}) == {}


def test_factor_ranks_point_the_right_way():
    import teamdata
    _, team, opp, _, _ = _league()
    fac, n = teamdata.factors(team, opp)
    assert n == 3
    # Alpha shoots best, turns it over least, allows the lowest shooting and forces the most turnovers: first in all four
    assert [fac[1][k][1] for k in ("fg", "tov", "opp_fg", "opp_tov")] == [1, 1, 1, 1]
    assert [fac[3][k][1] for k in ("fg", "tov", "opp_fg", "opp_tov")] == [3, 3, 3, 3]
    assert fac[1]["fg"][0] == 0.50 and fac[1]["tov"][0] == pytest.approx(model.tov_pct(team[1]))
    assert fac[2]["orb"][0] == pytest.approx(model.team_rating(team[2], opp[2])["reb_pct"])
    assert teamdata.averages(fac)["fg"] == pytest.approx(0.45) and teamdata.averages({}) == {}
    # a team whose numbers cannot be worked out is left out instead of stopping the page
    fac, n = teamdata.factors({**team, 4: dict(T, **{"FGA": 0.0, "FTA": 0.0, "TOV": 0.0})}, {**opp, 4: dict(O)})
    assert n == 3 and 4 not in fac


def test_a_teams_games_carry_the_models_pick():
    import teamdata
    rat = _league()[0]
    sched, picks = _league_schedule(rat)
    alpha, beta, gamma = sched[1], sched[2], sched[3]
    assert [(g["date"], g["opp"], g["where"], g["state"]) for g in alpha] == [
        ("2026-11-10", "Beta State", "home", "final"), ("2026-11-12", "Gamma A&M", "neutral", "final"),
        ("2026-11-23", "Gamma A&M", "home", "ahead")]
    won, lost, ahead = alpha
    # the score is the one the pick was graded on (the same as on the Results page), not the feed's later correction
    assert (won["pts"], won["opp_pts"], won["won"]) == (80, 60, True) and (beta[0]["pts"], beta[0]["opp_pts"]) == (60, 80)
    pa, ph = site.predicted_score(picks[0])
    assert won["pick"] == {"own": True, "pf": ph, "pa": pa, "official": True, "hit": True,
                           "path": "games/2026-11-10/beta-state-vs-alpha.html"}
    assert beta[0]["pick"]["own"] is False and (beta[0]["pick"]["pf"], beta[0]["pick"]["pa"]) == (pa, ph)
    # the game the feed lists the other way round still finds its pick, from the right side
    pa, ph = site.predicted_score(picks[1])              # Gamma A&M (away in the pick), Alpha (home)
    assert (lost["pts"], lost["opp_pts"], lost["won"]) == (70, 71, False)
    assert (lost["pick"]["own"], lost["pick"]["hit"], lost["pick"]["pf"], lost["pick"]["pa"]) == (True, False, ph, pa)
    assert (gamma[0]["pick"]["own"], gamma[0]["pick"]["pf"], gamma[0]["pick"]["pa"], gamma[0]["where"]) == (False, pa, ph, "neutral")
    # a game still ahead: the model's projection as of today, marked as not official
    proj = model.predict({"away_id": 3, "home_id": 1, "away": "Gamma A&M", "home": "Alpha", "neutral": False}, rat, {})
    assert ahead["pick"]["official"] is False and ahead["pick"]["own"] and ahead["pick"]["hit"] is None and ahead["pick"]["path"] == ""
    assert (ahead["pick"]["pa"], ahead["pick"]["pf"]) == teamdata._score(proj["total"], proj["differential"], True)
    # today's game is on the list once, with its locked pick and no result yet
    assert [(g["date"], g["state"], g["pick"]["official"], g["pick"]["hit"]) for g in beta if g["date"] == TODAY] == [(TODAY, "today", True, None)]
    # an opponent the model does not rate gets no pick; a bracket game waits for its opponent
    tiny = [g for g in gamma if g["opp"] == "Tiny College"][0]
    assert tiny["rated"] is False and "pick" not in tiny and (tiny["pts"], tiny["opp_pts"], tiny["won"]) == (50, 90, False)
    tbd = [g for g in beta if g["date"] == "2026-11-25"][0]
    assert tbd["opp"] == "TBD" and "pick" not in tbd and tbd["where"] == "neutral"
    assert not [g for g in beta if g["date"] == "2026-11-26"]            # a row with no team on one side is skipped
    assert teamdata.record(alpha) == (1, 1) and teamdata.model_record(alpha) == (1, 1) and teamdata.model_record(gamma) == (0, 1)


def test_team_page_score_is_the_game_cards_score():
    import teamdata
    for total in ("120.0", "139.5", "150.0", "161.3", "187.9"):
        for diff in ("0.0000", "0.0010", "0.0294", "0.0500", "0.0880", "0.1503", "0.3"):
            for home in (True, False):
                r = _r(total=total, differential=diff, pick="Home St" if home else "Away U")
                assert teamdata._score(total, diff, home) == site.predicted_score(r)


def test_places_moved_and_the_rank_history():
    import teamdata
    ranks = {1: 1, 2: 2, 3: 3}
    hist = {"2026-11-13": {"1": 2, "2": 1, "3": 3}, "2026-11-20": {"1": 1, "2": 2, "3": 3}}
    assert teamdata.moves(hist, TODAY, ranks) == ({1: 1, 2: -1, 3: 0}, "2026-11-13")       # the snapshot about a week back
    assert teamdata.moves({"2026-11-20": hist["2026-11-20"]}, TODAY, ranks) == ({1: 0, 2: 0, 3: 0}, "2026-11-20")   # younger site: the oldest there is
    assert teamdata.moves({TODAY: hist["2026-11-13"]}, TODAY, ranks) == ({}, "") and teamdata.moves({}, TODAY, ranks) == ({}, "")
    assert teamdata.moves(hist, TODAY, {1: 1, 4: 2})[0] == {1: 1}                             # a team with no earlier rank has no move
    kept = teamdata.remember({"2026-01-01": {"1": 3}, "2026-11-20": {"1": 2}}, TODAY, ranks)
    assert sorted(kept) == ["2026-11-20", TODAY] and kept[TODAY] == {"1": 1, "2": 2, "3": 3}


def test_team_profiles_and_conferences():
    import teamdata, writeup
    profs, _ = _profiles({"2026-11-13": {"1": 2, "2": 1, "3": 3}})
    assert [(p["name"], p["place"], p["slug"], p["conf"]) for p in profs] == [
        ("Alpha", 1, "alpha", "East"), ("Beta State", 2, "beta-state", "East"), ("Gamma A&M", 3, "gamma-am", "West")]
    a = profs[0]
    assert (a["wins"], a["losses"]) == (5, 1)                 # the feed's own record, which counts games it lists nowhere else
    assert (a["move"], a["move_since"], a["gp"], a["pace"], a["blend"], a["new_team"]) == (1, "2026-11-13", 6, 70.2, 0.3, False)
    assert round(a["points"], 1) == 17.0 and (a["off_rank"], a["def_rank"], a["sos_rank"]) == (1, 1, 1) and a["model_record"] == (1, 1)
    assert a["factors"]["fg"] == (0.50, 1) and a["n_factors"] == 3
    confs = teamdata.conferences(profs)
    assert [(c["conf"], c["n"], round(c["avg"], 1), c["best"]["name"], c["top25"]) for c in confs] == [
        ("East", 2, 8.5, "Alpha", 2), ("West", 1, -17.0, "Gamma A&M", 1)]
    # a rating carried over for a school the team list no longer puts in a conference gets no page
    rat, team, opp, teams, feed = _league()
    rat[4] = {"name": "Old Tech", "rating": 1.05, "offense": 0.5, "defense": 0.55, "sos": 0.0, "ppg": 70.0, "blend": 0.0}
    profs = teamdata.profiles(rat, writeup.ranks(rat), team, opp, feed, teams, {}, {}, TODAY)
    assert [p["name"] for p in profs] == ["Alpha", "Beta State", "Gamma A&M"] and [p["place"] for p in profs] == [1, 2, 3]
    assert profs[2]["rank"] == 4                              # ranked behind Old Tech by the model, third on the page
    # with fewer games in the feed's count than on the list, the list is what is shown
    profs = teamdata.profiles(_league()[0], writeup.ranks(_league()[0]), team, opp, [{"teamId": 1, "wins": 0, "losses": 0}],
                              teams, _league_schedule(_league()[0])[0], {}, TODAY)
    assert (profs[0]["wins"], profs[0]["losses"]) == (1, 1)


def test_departed_schools_leave_the_ratings():
    import build
    full = {str(i): {"conf": "East"} for i in range(1, 321)}
    rat = {1: {"blend": 0.4}, 2: {"blend": 0.0}, 900: {"blend": 0.0}, 901: {"blend": 0.3}}
    assert build.drop_departed(rat, dict(full, **{"900": {"conf": ""}, "901": {"conf": ""}})) == [900]
    assert sorted(rat) == [1, 2, 901]              # a team that has not played yet stays; so does one with games and no conference
    # a team list that did not load in full says nothing about who has left
    rat = {1: {"blend": 0.4}, 900: {"blend": 0.0}}
    assert build.drop_departed(rat, {"1": {"conf": "East"}}) == [] and sorted(rat) == [1, 900]
    assert build.drop_departed({900: {"blend": 0.0}}, {}) == []


def test_rankings_page(tmp_path, monkeypatch):
    import teamdata
    monkeypatch.setattr(site, "DOCS", tmp_path)
    profs, teams = _profiles()
    confs = teamdata.conferences(profs)
    html = site.rankings_page(profs, confs, "Nov 21, 2026 03:24 AM CT", teams, {"median_gp": 6})
    assert "<title>College Basketball Power Rankings: All 3 Division I Teams | " in html
    assert f'<link rel="canonical" href="{config.SITE_URL}/rankings.html">' in html
    assert '<a href="rankings.html" class="on">Rankings</a>' in html             # its own tab, lit
    for p in profs:
        assert f'<a href="teams/{p["slug"]}.html">{site.escape(p["name"])}</a>' in html and f'data-tid="{p["id"]}"' in html
    assert html.index("teams/alpha.html") < html.index("teams/beta-state.html") < html.index("teams/gamma-am.html")
    assert 'data-pts="17.00"' in html and ">+17.0<" in html and ">−17.0<" in html and 'data-conf="West"' in html
    assert '<option value="East">East</option>' in html and 'data-conf="East">East</a>' in html and "Conference strength" in html
    assert "the typical team has played 6 games, so about 70% of a typical rating still comes from last season" in html
    assert f"projects to win by about {12 + config.HOME_COURT_POINTS:g}" in html
    # no earlier day to compare with: no Move column; with one, it shows who went up and who went down
    assert 'data-k="move"' not in html and "c-mv" not in html.split("</style>")[1]
    profs, teams = _profiles({"2026-11-13": {"1": 2, "2": 1, "3": 3}})
    html = site.rankings_page(profs, teamdata.conferences(profs), "now", teams, {"median_gp": 25, "since": "2026-11-13"})
    assert 'title="Places moved since Nov 13"' in html and '<td class="c-mv up">▲1</td>' in html and '<td class="c-mv dn">▼1</td>' in html
    assert '<td class="c-mv">–</td>' in html and "Early-season note" not in html
    # the link to the method page only once that page exists
    assert 'href="model.html"' not in html
    (tmp_path / "model.html").write_text("x")
    assert 'href="model.html">How the model works</a>' in site.rankings_page(profs, [], "now", teams)
    assert "No teams" in site.rankings_page([], [], "now")                        # nothing rated: an empty table, not an error
    # the page's own script opens on a league when the address says so (rankings.html#conf=..., the link on every
    # team page), on arrival and when only that part of the address changes; a browser run checks the behaviour
    assert "addEventListener('hashchange',fromHash)" in site.RANK_JS and "apply();fromHash();" in site.RANK_JS
    assert site.RANK_JS in html and "decodeURIComponent" in site.RANK_JS


def test_new_styles_leave_the_old_pages_alone():
    """The new pages' styles are scoped to their own tables: a bare .up, .sc or .res rule would recolor
    the Upset pick flag and turn the score box and the W/L pills of the game rows inside out."""
    import re
    block = site.CSS[site.CSS.index("/* rankings, team pages, method page */"):site.CSS.index("@media (prefers-reduced-motion:no-preference){.g{")]
    css = re.sub(r"/\*.*?\*/", "", block, flags=re.S)
    rules = [r for r in re.findall(r"([^{}]+)\{", css) if not r.strip().startswith("@")]
    assert len(rules) > 60
    for rule in rules:
        for sel in rule.split(","):
            assert not re.fullmatch(r"\s*\.(up|dn|sc|res|n|t|d|m|k|g|flag|stat|chip|fav|disc|rk)\s*", sel), sel
    profs, teams = _profiles()
    page = site.team_page(profs[0], profs, "now", teams, {})
    assert 'class="rt sc"' not in page and 'class="res"' not in page


def test_team_page(tmp_path, monkeypatch):
    import teamdata
    monkeypatch.setattr(site, "DOCS", tmp_path)
    profs, teams = _profiles({"2026-11-13": {"1": 2, "2": 1, "3": 3}})
    avgs = teamdata.averages({p["id"]: p["factors"] for p in profs})
    (tmp_path / "games" / "2026-11-10").mkdir(parents=True)
    (tmp_path / "games" / "2026-11-10" / "beta-state-vs-alpha.html").write_text("x")      # the Nov 12 game never got a page
    html = site.team_page(profs[0], profs, "Nov 21, 2026 03:24 AM CT", teams, avgs)
    assert "<title>Alpha Aces Basketball: Model Rating, Schedule and Predictions | " in html
    assert f'<link rel="canonical" href="{config.SITE_URL}/teams/alpha.html">' in html
    assert '<a href="../rankings.html" class="on">Rankings</a>' in html and 'href="../index.html"' in html
    assert '<a href="../rankings.html#conf=East">East</a>' in html
    odd = dict(profs[0], conf="Big 12 & More")                      # a league name goes into the address encoded
    assert '<a href="../rankings.html#conf=Big%2012%20%26%20More">Big 12 &amp; More</a>' in site.team_page(odd, profs, "now", teams, avgs)
    assert "Alpha rates <b>1st of 3</b> Division I teams" in html and "the Aces <b>17.0 points better</b>" in html
    assert "That is up 1 place since Nov 13." in html
    assert "after 6 games, about 30% of this rating comes from this season and 70% from last season" in html
    assert "<b>#1</b><span>of 3 teams</span>" in html and "<b>+17.0</b><span>rating, in points</span>" in html
    assert "<b>1-1</b><span>model’s picks in their games</span>" in html and "5-1 this season. The model has had the winner in 1 of the 2 it picked." in html
    # results: newest first, the model's call linked to the game's page when that page exists
    assert html.index("Thu, Nov 12") < html.index("Tue, Nov 10")
    assert '<b class="up">W</b> 80–60' in html and '<b class="dn">L</b> 71–70' in html
    pa, ph = site.predicted_score(_league_schedule(_league()[0])[1][0])
    assert f'<a href="../games/2026-11-10/beta-state-vs-alpha.html">Alpha {ph}–{pa}</a> <span class="okx W">✓</span>' in html
    assert "games/2026-11-12" not in html and '<span class="okx L">✗</span>' in html
    assert 'vs <a href="../teams/gamma-am.html">Gamma A&amp;M</a> <i class="rk">#3</i> <i class="rk">neutral</i>' in html
    # coming up: an early projection, plainly not a locked pick
    assert "Coming up" in html and '<span class="soon">Early look</span> Alpha ' in html and "Mon, Nov 23<small>6:00 PM</small>" in html
    # the eight numbers behind the rating, with the Division I average and the rank
    assert "The numbers behind the rating" in html and "<b>Field goal %</b><small>40% of the offense rating</small>" in html
    assert '<td class="pts">50.0%<small>avg 45.0%</small></td>' in html and "<b>Turnover rate</b><small>25% · lower is better</small>" in html
    assert "at a pace of 70 possessions a game" in html and 'style="--p:100%"></span>1st' in html
    # league mates, each linked, this team marked
    assert '<a class="me" href="../teams/alpha.html"><i>#1</i> Alpha</a>' in html and '<a class="" href="../teams/beta-state.html">' in html
    assert "gamma-am.html\"><i>#3</i>" not in html.split('class="mates"')[1]              # another league
    ld = json.loads(html.split('<script type="application/ld+json">')[1].split("</script>")[0])
    assert ld[0]["@type"] == "SportsTeam" and ld[0]["name"] == "Alpha Aces" and ld[0]["memberOf"]["name"] == "East"
    assert ld[1]["itemListElement"][1]["item"] == f"{config.SITE_URL}/teams/alpha.html"
    # the other kinds of row: today's game, an unrated opponent, a bracket game without an opponent
    beta = site.team_page(profs[1], profs, "now", teams, avgs)
    assert '<span class="soon">Today</span>' in beta and "Opponent not set yet" in beta and "vs TBD" in beta
    gamma = site.team_page(profs[2], profs, "now", teams, avgs)
    assert 'at Tiny College <i class="rk">not D-I</i>' in gamma and "No pick: opponent not in Division I" in gamma
    assert "the Goats <b>17.0 points worse</b>" in gamma and "That is " not in gamma            # it has not moved: nothing to say
    # a team new to Division I says so instead of quoting a last season it never had
    new = dict(profs[2], new_team=True, mascot="", games=[], factors=None, move=None)
    page = site.team_page(new, profs, "now", teams, avgs)
    assert "is new to Division I" in page and "The model makes them" in page and "Coming up" not in page and "The numbers behind" not in page


def test_game_page_compares_the_two_teams(tmp_path, monkeypatch):
    monkeypatch.setattr(site, "DOCS", tmp_path)
    profs, teams = _profiles()
    by_id = {p["id"]: p for p in profs}
    r = dict(_r(away="Gamma A&M", away_id="3", home="Alpha", home_id="1", pick="Alpha", line_fav="", line_spread="", line_total=""),
             date=TODAY, game_key="k",
             when="Nov 21, 2026 8:00 PM ET", start="2026-11-21T20:00:00-05:00")
    wu = {"headline": "Alpha by 20", "lines": ["reason one"], "away_rank": 3, "home_rank": 1}
    html = site.game_page(r, teams, wu, "now", profiles=by_id)
    assert "How the two teams compare" in html and '<th>Gamma A&amp;M</th><th class="k"></th><th>Alpha</th>' in html
    assert '<tr><td class="">#3</td><td class="k">Model rank</td><td class="best">#1</td></tr>' in html
    assert '<tr><td class="">−17.0</td><td class="k">Rating, in points</td><td class="best">+17.0</td></tr>' in html
    assert '<tr><td class="">1-5</td><td class="k">Record</td><td class="">5-1</td></tr>' in html
    assert '<tr><td class="">40.0%</td><td class="k">Field goal %</td><td class="best">50.0%</td></tr>' in html
    # lower is better for turnovers and for what the opponents shoot
    tov = [f'{100 * by_id[t]["factors"]["tov"][0]:.1f}%' for t in (3, 1)]
    assert f'<tr><td class="">{tov[0]}</td><td class="k">Turnover rate</td><td class="best">{tov[1]}</td></tr>' in html
    assert '<tr><td class="">46.0%</td><td class="k">Opponents’ field goal %</td><td class="best">38.0%</td></tr>' in html
    # no profiles (an older build.py, or a team without one): the page is the one it always was
    assert "How the two teams compare" not in site.game_page(r, teams, wu, "now")
    assert "How the two teams compare" not in site.game_page(r, teams, wu, "now", profiles={1: by_id[1]})
    # a profile that is missing something leaves the table out; the game's page is still written
    broken = {1: by_id[1], 3: {k: v for k, v in by_id[3].items() if k != "points"}}
    page = site.game_page(r, teams, wu, "now", profiles=broken)
    assert "How the two teams compare" not in page and "Gamma A&amp;M vs Alpha prediction" in page and "reason one" in page
    assert "How the two teams compare" not in site.game_page(dict(r, away_id="x"), teams, wu, "now", profiles=by_id)
    # the team names link to the team pages once those exist (never to a page that is not there), from wherever the row sits
    assert 'class="tl"' not in html and "teams/" not in html
    (tmp_path / "teams").mkdir()
    (tmp_path / "teams" / "alpha.html").write_text("x")
    html = site.game_page(r, teams, wu, "now", profiles=by_id)
    assert '<b><a class="tl" href="../../teams/alpha.html">Alpha</a>' in html and "<b>Gamma A&amp;M<" in html
    assert '<th>Gamma A&amp;M</th><th class="k"></th><th><a class="tl" href="../../teams/alpha.html">Alpha</a></th>' in html
    today = site.today_page([r], "Saturday, Nov 21", "now", "note", teams, TODAY)
    assert '<b><a class="tl" href="teams/alpha.html">Alpha</a>' in today
    monkeypatch.setattr(site, "teamdata", None)                 # teamdata.py was not uploaded with this file
    html = site.game_page(r, teams, wu, "now", profiles=by_id)
    assert "How the two teams compare" not in html and 'class="tl"' not in html and "Gamma A&amp;M vs Alpha" in html


def _facts():
    return {"n_teams": 365, "median_gp": 5,
            "record": {"right": 651, "wrong": 202, "strong": (308, 18), "margin_miss": 11.7, "total_miss": 13.7, "last": "Nov 20, 2026",
                       "bands": [("Under 3 points", 84, 83), ("3 to 6", 106, 52), ("25 or more", 22, 1), ("Empty band", 0, 0)]},
            "example": {"away": "UCF", "home": "Vanderbilt", "day": "Nov 20", "neutral": False, "away_rating": 1.0709,
                        "home_rating": 1.1171, "margin": 11.87, "total": 159.1, "pa": 74, "ph": 85, "pick": "Vanderbilt",
                        "final": (74, 82), "path": "games/2026-11-20/ucf-vs-vanderbilt.html"}}


def test_method_page_reads_its_numbers_from_the_settings(tmp_path, monkeypatch):
    import bets
    monkeypatch.setattr(site, "DOCS", tmp_path)
    monkeypatch.setattr(config, "SHOW_RESULTS_STATS", True)
    html = site.model_page("Nov 21, 2026 03:24 AM CT", _facts())
    assert "<title>How the College Basketball Model Works | " in html and f'<link rel="canonical" href="{config.SITE_URL}/model.html">' in html
    assert "Every Division I team (all 365 of them)" in html
    for part in (f">{100 * config.W_SHOOT:.0f}%<", f">{100 * config.W_TOV:.0f}%<", f">{100 * config.W_REB:.0f}%<", f">{100 * config.W_FT:.0f}%<",
                 f"worth {config.POINTS_PER_RATING} points of margin", f"gets {config.HOME_COURT_POINTS:g} points",
                 f"from game {config.BLEND_GAMES} on last season is gone", f"{100 * config.FIRST_HALF_SHARE:.0f}% of the projected final margin",
                 f"projects by {config.STRONG_PICK_GAP * config.POINTS_PER_RATING:.0f} points or more",
                 f"at least {config.OU_EDGE_POINTS} points away", f"moves {100 * bets.MODEL_WEIGHT:.0f}% of the way",
                 f"at least a {100 * bets.MIN_CHANCE:.0f}% chance", f"by {100 * bets.MIN_EDGE:.0f} percentage points or more",
                 f"spreads of {bets.MAX_SPREAD:g} points or more", f"shorter than {bets.fmt_odds(bets.MAX_FAV_ML)}",
                 f"more than {bets.MAX_DISAGREE:g} points apart", f"top {bets.SINGLES} single bets"):
        assert part in html, part
    assert "typical team has played 5 games, so about 25% of a typical rating is this season and 75% is last season" in html
    # a setting changed in config.py changes the page with it
    monkeypatch.setattr(config, "HOME_COURT_POINTS", 3.5)
    monkeypatch.setattr(config, "BLEND_GAMES", 16)
    changed = site.model_page("now", _facts())
    assert "plus about 3.5 points for the home team" in changed and "after 4 games a quarter of the rating is new" in changed
    monkeypatch.undo()
    monkeypatch.setattr(site, "DOCS", tmp_path)
    monkeypatch.setattr(config, "SHOW_RESULTS_STATS", True)
    # the worked example adds up on the page: gap x 170, plus home court, is the margin shown
    assert "UCF 1.0709, Vanderbilt 1.1171. Vanderbilt is ahead by 0.0462." in html
    gap = round(config.POINTS_PER_RATING * 0.0462, 1)
    assert f"0.0462 × {config.POINTS_PER_RATING} = {gap} points better than UCF on a neutral floor" in html
    assert f"which adds {config.HOME_COURT_POINTS:g} points to that gap" in html
    assert f"<b>Projected margin:</b> Vanderbilt by {gap + config.HOME_COURT_POINTS:.1f}." in html
    assert "UCF 74, Vanderbilt 85." in html and "Vanderbilt won 82–74. The pick was right, and the margin missed by 3 points." in html
    assert "This game’s own page" not in html                                  # that page is not on the site (yet)
    (tmp_path / "games" / "2026-11-20").mkdir(parents=True)
    (tmp_path / "games" / "2026-11-20" / "ucf-vs-vanderbilt.html").write_text("x")
    assert '<a href="games/2026-11-20/ucf-vs-vanderbilt.html">This game’s own page</a>' in site.model_page("now", _facts())
    away_fav = dict(_facts()["example"], away_rating=1.13, home_rating=1.12, pick="Vanderbilt", neutral=False)
    page = site.model_page("now", dict(_facts(), example=away_fav))
    assert f"which takes {config.HOME_COURT_POINTS:g} points off that gap" in page
    assert f"Vanderbilt by {abs(round(170 * 0.01, 1) - config.HOME_COURT_POINTS):.1f}." in page
    assert "Neutral floor, so nobody gets a home-court edge." in site.model_page("now", dict(_facts(), example=dict(away_fav, neutral=True)))
    # the record, split by how sure the model was; a band with no games is left out
    assert "picked the winner in <b>651 of 853 games (76%)</b>, and in 308 of 326 strong picks (94%)" in html
    assert '<td class="t">Under 3 points</td><td>167</td><td class="nw">84-83</td><td class="pts">50%</td>' in html
    assert "by 11.7 points on average, and the projected total by 13.7" in html and "Empty band" not in html
    # the switch that hides the record on the Results page hides it here too
    monkeypatch.setattr(config, "SHOW_RESULTS_STATS", False)
    hidden = site.model_page("now", _facts())
    assert "651 of 853" not in hidden and "Under 3 points" not in hidden and 'href="results.html">Results</a> page' in hidden
    # the questions are marked up for search engines exactly as they read on the page
    ld = json.loads(html.split('<script type="application/ld+json">')[1].split("</script>")[0])
    assert ld["@type"] == "FAQPage" and len(ld["mainEntity"]) == len(site.MODEL_FAQ) >= 6
    for q in ld["mainEntity"]:
        assert f"<h3>{site.escape(q['name'])}</h3><p>{q['acceptedAnswer']['text']}</p>" in html
    # with nothing from the build (no facts) it is still a whole page
    plain = site.model_page("now")
    assert "The short version" in plain and "Worked example" not in plain and "Right now the typical team" not in plain
    assert "Start from the" not in plain                                        # no Rankings on the site yet
    (tmp_path / "rankings.html").write_text("x")
    assert 'Start from the <a href="rankings.html">Rankings</a>' in site.model_page("now")


def test_about_page_shows_only_what_the_settings_give(tmp_path, monkeypatch):
    monkeypatch.setattr(site, "DOCS", tmp_path)
    for name in ("OWNER_NAME", "CONTACT_EMAIL"):
        monkeypatch.setattr(config, name, "", raising=False)
    monkeypatch.setattr(config, "SOCIAL_LINKS", {}, raising=False)
    html = site.about_page("now")
    assert f"<title>About {config.SITE_NAME}: Who Runs It and How It Works</title>" in html and '<h2 id="contact">Contact</h2>' in html
    assert "mailto:" not in html and "built and run by" not in html and "@" not in html.split("<main")[1].split("</main>")[0]
    assert "one-person project. It started" in html and "GitHub repository" in html
    # the pages the build has not made are not linked: not in the text, not in the tabs, not in the footer
    assert "model.html" not in html and "rankings.html" not in html and '<a href="about.html">About the model</a>' in html
    assert "along with power rankings" not in html and "team pages are recalculated" not in html
    for f in ("model.html", "rankings.html"):
        (tmp_path / f).write_text("x")
    html = site.about_page("now")
    assert 'is on <a href="model.html">How the model works</a>, and every team’s numbers are on the <a href="rankings.html">Rankings</a>.' in html
    assert ('<a href="model.html">How the model works</a><a href="about.html">About</a><a href="about.html#contact">Contact</a>'
            '<a href="privacy.html">Privacy</a>') in html
    assert '<a href="rankings.html" class="">Rankings</a>' in html and "along with power rankings for every team" in html
    # a name and an address appear only when config.py has them; the address goes on the Privacy page too
    monkeypatch.setattr(config, "OWNER_NAME", "Pat <Example>")
    monkeypatch.setattr(config, "CONTACT_EMAIL", " hello@example.com ")
    monkeypatch.setattr(config, "SOCIAL_LINKS", {"TikTok": "https://www.tiktok.com/@example", "Empty": ""})
    html = site.about_page("now")
    assert "built and run by Pat &lt;Example&gt;." in html
    assert '<a href="mailto:hello@example.com">hello@example.com</a>. You can also follow along on ' in html
    assert '<a href="https://www.tiktok.com/@example" rel="me noopener">TikTok</a>.' in html and "Empty" not in html
    assert '<a href="mailto:hello@example.com">hello@example.com</a>' in site.privacy_page("now")
    monkeypatch.setattr(config, "CONTACT_EMAIL", "")
    assert "Follow along on <a href=\"https://www.tiktok.com/@example\"" in site.about_page("now")
    assert "GitHub repository" in site.privacy_page("now")
    # a config.py from before these settings existed behaves like empty ones
    for name in ("OWNER_NAME", "CONTACT_EMAIL", "SOCIAL_LINKS"):
        monkeypatch.delattr(config, name)
    assert "GitHub repository" in site.about_page("now") and "mailto:" not in site.privacy_page("now")


def test_tabs_and_links_follow_the_pages_that_exist(tmp_path, monkeypatch):
    monkeypatch.setattr(site, "DOCS", tmp_path)
    monkeypatch.setattr(site, "COMING", set())
    plain = site.page("t", "index.html", "body", "now")
    assert "rankings.html" not in plain and "model.html" not in plain
    # pages the running build is about to write count as there (each of the new pages links to the other)
    site.COMING.update(("rankings.html", "model.html"))
    both = site.page("t", "index.html", "body", "now", root="../")
    assert '<a href="../rankings.html" class="">Rankings</a>' in both and '<a href="../model.html">How the model works</a>' in both
    site.COMING.clear()
    assert "rankings.html" not in site.page("t", "index.html", "body", "now")
    # a page always carries its own tab
    assert '<a href="rankings.html" class="on">Rankings</a>' in site.page("t", "rankings.html", "body", "now")
    assert 'href="model.html">How the model works</a>' in site.page("t", "model.html", "body", "now")
    # five tabs fit on a phone because the header goes to two lines there
    assert ".top{top:-42px}" in site.CSS and "nav a{padding:7px 9px;font-size:14px;white-space:nowrap}" in site.CSS


def test_sitemap_lists_what_matters_and_old_game_pages_step_back(tmp_path, monkeypatch):
    monkeypatch.setattr(site, "DOCS", tmp_path)
    stamp = "Nov 21, 2026 03:24 AM CT"
    head = f'<!doctype html><html><head><title>t</title></head><body><div>Updated {stamp}</div></body></html>'
    for day in ("2026-11-02", "2026-11-13", "2026-11-14", "2026-11-20", "2026-11-21"):
        (tmp_path / "games" / day).mkdir(parents=True)
        (tmp_path / "games" / day / "a-vs-b.html").write_text(head, encoding="utf-8")
    (tmp_path / "teams").mkdir()
    (tmp_path / "teams" / "alpha.html").write_text(head, encoding="utf-8")
    (tmp_path / "rankings.html").write_text(head, encoding="utf-8")
    (tmp_path / "model.html").write_text(head, encoding="utf-8")
    site.write("i", "r", "b", docs=tmp_path, stamp=stamp, live_html="l")
    sm = (tmp_path / "sitemap.xml").read_text()
    locs = [u.split("</loc>")[0] for u in sm.split("<loc>")[1:]]
    assert locs[:4] == [f"{config.SITE_URL}/", f"{config.SITE_URL}/live.html", f"{config.SITE_URL}/bets.html", f"{config.SITE_URL}/results.html"]
    assert f"<loc>{config.SITE_URL}/rankings.html</loc><lastmod>2026-11-21</lastmod>" in sm
    assert f"<loc>{config.SITE_URL}/teams/alpha.html</loc><lastmod>2026-11-21</lastmod>" in sm
    assert f"<loc>{config.SITE_URL}/model.html</loc></url>" in sm and f"<loc>{config.SITE_URL}/about.html</loc></url>" in sm
    # game pages: the last seven days only (Nov 14 on), each dated the day after its game but never in the future
    assert [u for u in locs if "/games/" in u] == [f"{config.SITE_URL}/games/{d}/a-vs-b.html" for d in ("2026-11-14", "2026-11-20", "2026-11-21")]
    assert "games/2026-11-20/a-vs-b.html</loc><lastmod>2026-11-21</lastmod>" in sm and "games/2026-11-21/a-vs-b.html</loc><lastmod>2026-11-21</lastmod>" in sm
    assert config.STUDIO_PAGE not in sm
    # write() never makes the method page itself: only build.py does, which also gets it committed
    (tmp_path / "model.html").unlink()
    site.write("i", "r", "b", docs=tmp_path, stamp=stamp, live_html="l")
    assert not (tmp_path / "model.html").exists() and "model.html" not in (tmp_path / "sitemap.xml").read_text()
    assert "model.html" not in (tmp_path / "about.html").read_text()
    # the older game pages are asked out of search results, once, and stay as they are otherwise
    old, edge, new = (tmp_path / "games" / d / "a-vs-b.html" for d in ("2026-11-13", "2026-11-14", "2026-11-21"))
    assert site.retire_old_games(tmp_path, "2026-11-21") == 2
    assert old.read_text() == head.replace("<head>", '<head><meta name="robots" content="noindex,follow">')
    assert edge.read_text() == head and new.read_text() == head
    assert site.retire_old_games(tmp_path, "2026-11-21") == 0
    # the next morning only the day that has just crossed the line is opened
    assert site.retire_old_games(tmp_path, "2026-11-22", "2026-11-21") == 1 and "noindex,follow" in edge.read_text()
    (tmp_path / "games" / "2026-11-02" / "late.html").write_text(head, encoding="utf-8")
    assert site.retire_old_games(tmp_path, "2026-11-23", "2026-11-22") == 0          # Nov 2 was dealt with long ago: not opened again
    assert site.retire_old_games(tmp_path, "2026-11-23") == 1                          # ...unless everything is checked (no date given)
    assert site.retire_old_games(tmp_path, "") == 0 and site.retire_old_games(tmp_path, "not a date") == 0
    # the window is a setting
    monkeypatch.setattr(config, "GAME_PAGE_DAYS", 1, raising=False)
    site.write("i", "r", "b", docs=tmp_path, stamp=stamp, live_html="l")
    assert [u.split("/games/")[1][:10] for u in (tmp_path / "sitemap.xml").read_text().split("<loc>")[1:] if "/games/" in u] == ["2026-11-20", "2026-11-21"]


def _hub_world(tmp_path, monkeypatch):
    """A scratch site with a full Division I: 322 teams this season, one more last season (it has
    since left), a few finished games, one game today and two in the coming week."""
    from datetime import datetime
    build = _site_in(tmp_path, monkeypatch)
    stats = [stats_row(i, f"T{i}") for i in range(1, 321)]
    stats.append(stats_row(500, "Tennessee", team=unit(320, 600, 160, 200, 110, 260, 90, 860)))
    stats.append(stats_row(600, "Wofford"))
    last = [dict(r, season=2026, seasonLabel="2025-26", games=30) for r in stats + [stats_row(700, "Old Tech")]]
    team_list = [{"id": i, "school": f"T{i}", "mascot": "Owls", "conference": "East" if i % 2 else "West"} for i in range(1, 321)]
    team_list += [{"id": 500, "school": "Tennessee", "mascot": "Volunteers", "conference": "SEC", "primaryColor": "FF8200", "abbreviation": "TENN"},
                  {"id": 600, "school": "Wofford", "mascot": "Terriers", "conference": "SoCon"},
                  {"id": 700, "school": "Old Tech", "mascot": "Ghosts", "conference": None},
                  {"id": 1543, "sourceId": "-1", "school": "TBD", "mascot": "TBD", "conference": None}]
    games = [
        game(2, "2026-11-09T00:00:00Z", "T1", 1, "T2", 2, "final", 60, 70, [25, 35], [40, 30]),      # Nov 8
        game(3, "2026-11-08T00:00:00Z", "Wofford", 600, "T3", 3, "final", 70, 60, [33, 37], [30, 30]),  # Nov 7
        game(1, "2026-11-10T00:00:00Z", "Wofford", 600, "Tennessee", 500),                            # Nov 9, 7 PM Eastern: today
        game(30, "2026-11-12T00:00:00Z", "Tennessee", 500, "T4", 4),                                  # Nov 11
        dict(game(31, "2026-11-13T00:30:00Z", "TBD", 1543, "Wofford", 600), neutralSite=True),        # Nov 12, opponent not set
    ]
    calls = []

    def get_games(a, b):
        calls.append((a.isoformat(), b.isoformat()))
        return [dict(g) for g in games if a.isoformat() <= fetch.parse_games([g])[0]["date"] <= b.isoformat()]
    monkeypatch.setattr(fetch, "team_stats", lambda s: stats if s == 2027 else last)
    monkeypatch.setattr(fetch, "lines", lambda a, b: [])
    monkeypatch.setattr(fetch, "teams", lambda: team_list)
    monkeypatch.setattr(fetch, "games", get_games)
    monkeypatch.setattr(fetch, "espn_matchups", lambda day: {})
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    clock = {}
    monkeypatch.setattr(config, "now_et", lambda: clock["now"])

    def run(when, *flags):
        clock["now"] = datetime.strptime(when, "%Y-%m-%d %H:%M").replace(tzinfo=config.ET)
        monkeypatch.setattr("sys.argv", ["build.py", *flags])
        del calls[:]
        return build.main()
    return build, run, calls, games


def test_rankings_and_team_pages_come_out_of_the_build(tmp_path, monkeypatch):
    build, run, calls, games = _hub_world(tmp_path, monkeypatch)
    docs = tmp_path / "docs"
    run("2026-11-09 04:23")                                               # the overnight build
    week = ("2026-11-10", "2026-11-16")
    assert calls.count(week) == 1                                         # one data call for the coming week
    assert json.loads((tmp_path / "raw" / "games_week.json").read_text())["from"] == "2026-11-10"
    assert list(json.loads((tmp_path / "rank_history.json").read_text())) == ["2026-11-09"]
    ranks = (docs / "rankings.html").read_text()
    assert "All 322 Division I Teams" in ranks and "Old Tech" not in ranks                     # the school that left is gone
    assert len(list((docs / "teams").glob("*.html"))) == 322 and not (docs / "teams" / "old-tech.html").exists()
    assert 'href="teams/tennessee.html">Tennessee</a>' in ranks and 'data-k="move"' not in ranks
    assert "the typical team has played 10 games, so about 50% of a typical rating" in ranks
    # every page of the build knows the new pages: the tab, the footer, the links between the two
    home = (docs / "index.html").read_text()
    assert '<a href="rankings.html" class="">Rankings</a>' in home and '<a href="model.html">How the model works</a>' in home
    assert '<a class="tl" href="teams/tennessee.html">Tennessee</a>' in home
    method = (docs / "model.html").read_text()
    assert '<a href="rankings.html" class="">Rankings</a>' in method and "(all 322 of them)" in method
    assert 'href="model.html">How the model works</a>' in ranks and "Worked example" not in method      # nothing graded yet
    assert 'href="model.html"' in (docs / "about.html").read_text()
    # the team pages: today's locked pick, the early look, the bracket game, a result from before the picks began
    tenn = (docs / "teams" / "tennessee.html").read_text()
    assert '<span class="soon">Today</span>' in tenn and 'href="../games/2026-11-09/wofford-vs-tennessee.html">Tennessee ' in tenn
    assert '<span class="soon">Early look</span> ' in tenn and 'at <a href="../teams/t4.html">T4</a>' in tenn
    assert "Volunteers · SEC · 5-5" in tenn and "about 50% of this rating comes from this season" in tenn
    woff = (docs / "teams" / "wofford.html").read_text()
    assert "vs TBD" in woff and "Opponent not set yet" in woff and '<b class="up">W</b> 70–60' in woff and "No pick</span>" in woff
    game_page = (docs / "games" / "2026-11-09" / "wofford-vs-tennessee.html").read_text()
    assert "How the two teams compare" in game_page and '<th><a class="tl" href="../../teams/wofford.html">Wofford</a></th>' in game_page
    sm = (docs / "sitemap.xml").read_text()
    for path in ("rankings.html", "model.html", "teams/tennessee.html", "teams/t320.html", "games/2026-11-09/wofford-vs-tennessee.html"):
        assert f"<loc>{config.SITE_URL}/{path}</loc>" in sm
    assert (tmp_path / "games_retired.txt").read_text().strip() == "2026-11-09"
    # a refresh: no call for the week, the rankings and team pages left exactly as the morning made them,
    # the pages it does rewrite still carry the tab and the comparison
    before = {p.name: p.read_bytes() for p in [docs / "rankings.html", docs / "model.html", docs / "teams" / "tennessee.html"]}
    run("2026-11-09 14:45", "--refresh")
    assert week not in calls and len(calls) == 1
    assert before == {p.name: p.read_bytes() for p in [docs / "rankings.html", docs / "model.html", docs / "teams" / "tennessee.html"]}
    assert '<a href="rankings.html" class="">Rankings</a>' in (docs / "index.html").read_text()
    assert "How the two teams compare" in (docs / "games" / "2026-11-09" / "wofford-vs-tennessee.html").read_text()
    assert list(json.loads((tmp_path / "rank_history.json").read_text())) == ["2026-11-09"]
    # a refresh on a site that has no rankings yet (the first build after these pages were added) writes them
    for p in list((docs / "teams").glob("*.html")) + [docs / "rankings.html", docs / "model.html"]:
        p.unlink()
    run("2026-11-09 16:45", "--refresh")
    assert (docs / "rankings.html").exists() and (docs / "model.html").exists() and len(list((docs / "teams").glob("*.html"))) == 322
    assert '<a href="rankings.html" class="">Rankings</a>' in (docs / "index.html").read_text()
    assert '<span class="soon">Early look</span>' in (docs / "teams" / "tennessee.html").read_text()   # from the week kept this morning
    # the game goes final at night: the score update grades it, the game page keeps its comparison, and the two
    # teams' own pages show the result the same night (nobody else's page is touched, nor are the rankings)
    others = {p.name: p.read_bytes() for p in [docs / "rankings.html", docs / "model.html", docs / "teams" / "t4.html"]}
    assert '<span class="soon">Today</span>' in (docs / "teams" / "tennessee.html").read_text()
    games[2].update(status="final", awayPoints=60, homePoints=75)
    run("2026-11-09 22:45", "--scores")
    assert week not in calls
    assert "Tennessee won 75-60" in (docs / "games" / "2026-11-09" / "wofford-vs-tennessee.html").read_text()
    tenn = (docs / "teams" / "tennessee.html").read_text()
    assert '<span class="soon">Today</span>' not in tenn and '<b class="up">W</b> 75–60' in tenn and '<span class="okx W">✓</span>' in tenn
    assert 'href="../games/2026-11-09/wofford-vs-tennessee.html">Tennessee ' in tenn and "Volunteers · SEC · 5-5" in tenn
    assert '<b class="dn">L</b> 75–60' in (docs / "teams" / "wofford.html").read_text()
    assert others == {p.name: p.read_bytes() for p in [docs / "rankings.html", docs / "model.html", docs / "teams" / "t4.html"]}
    # an hour later there is nothing new: no page is written twice for the same result
    after = (docs / "teams" / "tennessee.html").read_bytes()
    run("2026-11-09 23:45", "--scores")
    assert (docs / "teams" / "tennessee.html").read_bytes() == after
    # the next morning: the result is on both team pages with the model's call, the method page has its worked example
    # and its record, and the Move column has a day to compare with
    monkeypatch.setattr(config, "SHOW_RESULTS_STATS", True)
    run("2026-11-10 04:23")
    assert calls.count(("2026-11-11", "2026-11-17")) == 1
    tenn = (docs / "teams" / "tennessee.html").read_text()
    assert '<b class="up">W</b> 75–60' in tenn and '<span class="okx W">✓</span>' in tenn and "The model has had the winner in 1 of the 1 it picked." in tenn
    assert '<b class="dn">L</b> 75–60' in (docs / "teams" / "wofford.html").read_text()
    method = (docs / "model.html").read_text()
    assert "Worked example" in method and "Wofford at Tennessee, Nov 9" in method and "picked the winner in <b>1 of 1 games (100%)</b>" in method
    assert '<a href="games/2026-11-09/wofford-vs-tennessee.html">This game’s own page</a>' in method
    assert sorted(json.loads((tmp_path / "rank_history.json").read_text())) == ["2026-11-09", "2026-11-10"]
    assert 'title="Places moved since Nov 9"' in (docs / "rankings.html").read_text()
    # a re-run of an earlier day by hand never touches the rankings (they are today's)
    before = (docs / "rankings.html").read_bytes()
    monkeypatch.setattr("sys.argv", ["build.py", "--date", "2026-11-09"])
    build.main()
    assert (docs / "rankings.html").read_bytes() == before


def test_coming_week_is_one_call_and_never_a_reason_to_fail(tmp_path, monkeypatch):
    from datetime import datetime
    build = _site_in(tmp_path, monkeypatch)
    now = datetime(2026, 11, 9, 4, 23, tzinfo=config.ET)
    today = date(2026, 11, 9)
    asked = []

    def get_games(a, b):
        asked.append((a.isoformat(), b.isoformat()))
        return [game(30, "2026-11-12T00:00:00Z", "Tennessee", 500, "T4", 4)]
    monkeypatch.setattr(fetch, "games", get_games)
    monkeypatch.setattr(build, "REFRESH", False)
    assert len(build.week_ahead(today, now)) == 1 and asked == [("2026-11-10", "2026-11-16")]
    kept = tmp_path / "raw" / "games_week.json"
    assert json.loads(kept.read_text())["from"] == "2026-11-10"
    # a refresh reads what the morning kept; so does a morning when the feed is down or the calls are being held back
    monkeypatch.setattr(build, "REFRESH", True)
    assert len(build.week_ahead(today, now)) == 1 and len(asked) == 1
    monkeypatch.setattr(build, "REFRESH", False)

    def down(a, b):
        raise fetch.FetchError("feed is down")
    monkeypatch.setattr(fetch, "games", down)
    assert len(build.week_ahead(today, now)) == 1
    (tmp_path / "api_calls_left.txt").write_text("5 at x\n")
    monkeypatch.setattr(fetch, "games", get_games)
    assert len(build.week_ahead(today, now)) == 1 and len(asked) == 1                # held back: no call
    # what was kept for another day is not shown as this week's
    assert build.week_ahead(date(2026, 11, 10), now) == []
    kept.write_text("not json")
    assert build.week_ahead(today, now) == []
    # a refresh with nothing kept for today (the first build with the team pages, uploaded during the day)
    # may make the call once, when it is the build that writes those pages, and then lives on what it kept
    (tmp_path / "api_calls_left.txt").unlink()
    monkeypatch.setattr(build, "REFRESH", True)
    assert build.week_ahead(today, now, download=False) == [] and len(asked) == 1
    assert len(build.week_ahead(today, now)) == 1 and len(asked) == 2
    assert len(build.week_ahead(today, now)) == 1 and len(asked) == 2


def test_site_builds_as_before_when_the_new_files_are_only_half_there(tmp_path, monkeypatch):
    build, run, calls, games = _hub_world(tmp_path, monkeypatch)
    docs = tmp_path / "docs"
    # build.py without teamdata.py: no rankings, no team pages, and no page points at them
    monkeypatch.setattr(build, "teamdata", None)
    assert run("2026-11-09 04:23") == 0
    assert not (docs / "rankings.html").exists() and not (docs / "model.html").exists() and not (docs / "teams").exists()
    for page in ("index.html", "results.html", "bets.html", "live.html", "about.html", "privacy.html", "games/2026-11-09/wofford-vs-tennessee.html"):
        html = (docs / page).read_text()
        assert "rankings.html" not in html and "model.html" not in html and "teams/" not in html, page
    assert "About the model" in (docs / "index.html").read_text()
    sm = (docs / "sitemap.xml").read_text()
    assert "rankings.html" not in sm and "model.html" not in sm and "/teams/" not in sm
    assert ("2026-11-10", "2026-11-16") not in calls                    # and no data call spent on a page that is not made
    # a team page that cannot be drawn costs the build nothing: the day's picks and pages still go out
    monkeypatch.undo()
    build, run, calls, games = _hub_world(tmp_path, monkeypatch)

    def broken(*a, **k):
        raise KeyError("factors")
    monkeypatch.setattr(site, "team_page", broken)
    assert run("2026-11-09 05:23") == 0
    assert not (docs / "rankings.html").exists()                        # nothing half-written: all the new pages or none
    home = (docs / "index.html").read_text()
    assert "Tennessee" in home and "rankings.html" not in home and "model.html" not in home


def test_new_pages_are_handed_to_the_commit_step(tmp_path, monkeypatch):
    """The workflow commits a fixed list of files plus whatever is already staged, so on a GitHub
    runner the build stages the pages that list has never heard of."""
    import shutil
    import subprocess
    import build
    if shutil.which("git") is None:
        pytest.skip("git is not installed here")
    docs = tmp_path / "site"
    (docs / "teams").mkdir(parents=True)
    for f in ("index.html", "rankings.html", "model.html", "teams/duke.html"):
        (docs / f).write_text("x")
    monkeypatch.setattr(site, "DOCS", docs)

    def git(*args):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args], cwd=docs,
                              capture_output=True, text=True, check=True).stdout.split()
    git("init", "-q")
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    assert build.stage_hub_pages() == [] and git("diff", "--cached", "--name-only") == []      # your own computer: nothing is touched
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert build.stage_hub_pages() == ["rankings.html", "model.html", "teams"]
    assert git("diff", "--cached", "--name-only") == ["model.html", "rankings.html", "teams/duke.html"]   # index.html is the workflow's to add
    git("commit", "-q", "-m", "one")
    # a team page the next build removed is staged as a removal, a new one as an addition
    (docs / "teams" / "duke.html").unlink()
    (docs / "teams" / "unc.html").write_text("y")
    build.stage_hub_pages()
    assert git("diff", "--cached", "--name-status") == ["D", "teams/duke.html", "A", "teams/unc.html"]
    # outside a repository it reports and carries on
    monkeypatch.setattr(site, "DOCS", tmp_path / "nowhere")
    assert build.stage_hub_pages() == []
