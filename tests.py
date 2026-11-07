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


def test_first_half_last3():
    gl = fetch.parse_games([
        game(i, f"2026-11-{d:02d}T23:00:00Z", "A", 1, "B", 2, "final", 70, 70, [a1, 35], [b1, 35])
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
    p = model.predict(g, rat, {1: 40.0, 2: 35.0})
    assert p["margin"] == pytest.approx(K * 0.10 + H)                     # rating edge + home court
    assert p["pick"] == "Home St" and p["differential"] == pytest.approx(0.10 + H / K)
    assert p["strong_pick"] == "Home St" and p["total"] == pytest.approx(145.0)
    assert p["fh_pick"] == "Away U" and p["fh_margin"] == pytest.approx(5.0)
    # equal ratings: home court decides at home, nobody gets it at a neutral site (tie -> away, like the sheet)
    rat[2]["rating"] = 1.10
    assert model.predict(g, rat, {})["pick"] == "Home St"
    assert model.predict({**g, "neutral": True}, rat, {})["pick"] == "Away U"
    # away team better by less than home court -> home still picked; by more -> away picked
    rat[1]["rating"] = 1.10 + (H - 1) / K
    assert model.predict(g, rat, {})["pick"] == "Home St"
    rat[1]["rating"] = 1.10 + (H + 1) / K
    assert model.predict(g, rat, {})["pick"] == "Away U"
    assert model.predict({**g, "away_id": 999}, rat, {})["pick"] is None


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
    assert r["fh_pick"] == "Tennessee" and float(r["fh_margin"]) == pytest.approx(41 - 33, abs=0.05)
    html = (tmp_path / "docs" / "index.html").read_text()
    assert "Tennessee \u22129.5" in html and "152.5" in html
    assert "Best Bets" in (tmp_path / "docs" / "bets.html").read_text()
    gp = tmp_path / "docs" / "games" / "2026-11-09" / "wofford-vs-tennessee.html"
    assert gp.exists() and "Wofford vs Tennessee prediction" in gp.read_text() and "SportsEvent" in gp.read_text()
    assert "games/2026-11-09/wofford-vs-tennessee.html" in (tmp_path / "docs" / "sitemap.xml").read_text()
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
    assert out["D"]["rating"] == 1.05 and out["D"]["blend"] == 1.0           # new to D-I: this season only


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
    assert cap.startswith("Away U vs Home St") and "66-69" in cap and "#collegebasketball" in cap
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
