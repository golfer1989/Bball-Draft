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
    assert html.count("Away U +4.5") >= 1 and "The bet" in html and 'betpill strong' in html
    none = site.today_page([r], "x", "now", "note", {}, "2026-11-04", gotd=r)
    assert "Nothing here" in none and "line already prices it in" in none


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
    assert "data-ea" not in past and '<span class="res L big">L</span><small class="fin">Final 61-70</small>' in past
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
    assert "Wofford" in (docs / "results.html").read_text() and 'data-date="2026-11-09"' in (docs / "index.html").read_text()
    assert "1 finished game now on Results" in (docs / "index.html").read_text()
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
    assert calls["games"][n1:] == [("2026-11-09", "2026-11-09")]
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
    assert len(calls["games"]) == n2 + 1 and rows()["2026-11-09|5|6"]["away_pts"] == "80"

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
    run()
    assert not [k for k in rows() if k.startswith("2026-11-10")] and (tmp_path / "last_build.txt").read_text().strip() == "2026-11-09"

    # --- the overnight build (3:23 AM Central): the new day starts, last night's grades stand
    at("2026-11-10 04:23")
    run()
    got = rows()
    assert [k for k in got if k.startswith("2026-11-10")] == ["2026-11-10|7|8"]
    assert (tmp_path / "last_build.txt").read_text().strip() == "2026-11-10"
    assert (got["2026-11-09|600|500"]["home_pts"], got["2026-11-09|3|4"]["away_pts"], got["2026-11-09|5|6"]["home_pts"]) == ("75", "71", "70")
    assert 'data-date="2026-11-10"' in (docs / "index.html").read_text()


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
