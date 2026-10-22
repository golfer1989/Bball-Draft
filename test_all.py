"""Run with:  python -m pytest -q test_all.py
Sample API payloads follow the official cbbd client's field names (TeamSeasonStats, GameInfo)."""
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
    assert t["150"] == {"mascot": "Blue Devils", "color": "001A57", "logo": "https://x/500-dark/150.png", "abbr": "DUKE"}
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


def test_schedule_adjust():
    # A and B have identical raw numbers, but A played the strong team S and B the weak team W
    base = lambda o, d: {"offense": o, "defense": d, "rating": o + d, "ppg": 70.0, "name": "x"}  # noqa: E731
    rat = {"A": base(.57, .45), "B": base(.57, .45), "S": base(.62, .50), "W": base(.52, .40)}
    games = [("A", "S"), ("A", "S"), ("B", "W"), ("B", "W"), ("S", "W")]
    model.schedule_adjust(rat, games)
    assert rat["A"]["rating"] > rat["B"]["rating"]                       # tougher schedule -> higher rating
    assert rat["A"]["raw_rating"] == pytest.approx(1.02) and rat["A"]["sos"] > 0 > rat["B"]["sos"]
    # weight 0 leaves ratings untouched
    rat2 = {"A": base(.57, .45), "S": base(.62, .50)}
    model.schedule_adjust(rat2, [("A", "S")], weight=0)
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
    import run_daily
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
    monkeypatch.setattr(run_daily, "DATA", tmp_path)
    monkeypatch.setattr(run_daily, "RAW", tmp_path / "raw")
    for fn in (ledger.load, ledger.save):
        monkeypatch.setattr(fn, "__defaults__", (tmp_path / "ledger.csv",))
    monkeypatch.setattr(site.write, "__defaults__", (tmp_path / "docs",))
    monkeypatch.setattr(fetch, "team_stats", lambda s: stats if s == 2027 else [])
    monkeypatch.setattr(fetch, "teams", lambda: [{"id": 500, "mascot": "Volunteers", "primaryColor": "FF8200",
                                                   "abbreviation": "TENN", "logos": ["https://x/500/2633.png"]}])
    monkeypatch.setattr(fetch, "games", lambda a, b: [g for g in games if a.isoformat() <= fetch.parse_games([g])[0]["date"] <= b.isoformat()])
    # day 1: Nov 8 picks get locked for T1@T2 ... (none of interest); run Nov 9
    monkeypatch.setattr("sys.argv", ["run_daily.py", "--date", "2026-11-09"])
    run_daily.main()
    rows = ledger.load(tmp_path / "ledger.csv")
    assert [(r["away"], r["home"]) for r in rows] == [("Wofford", "Tennessee")]   # non-D1 skipped
    r = rows[0]
    assert r["pick"] == "Tennessee" and r["stats_season"] == "2026-27"
    assert r["fh_pick"] == "Tennessee" and float(r["fh_margin"]) == pytest.approx(41 - 33, abs=0.05)
    html = (tmp_path / "docs" / "index.html").read_text()
    assert "7:00" in html and "Tennessee" in html and "Volunteers" in html and "https://x/500/2633.png" in html
    # next day: game is final -> graded, including 1H
    games[0].update(status="final", awayPoints=60, homePoints=75, awayPeriodPoints=[28, 32], homePeriodPoints=[36, 39])
    monkeypatch.setattr("sys.argv", ["run_daily.py", "--date", "2026-11-10"])
    run_daily.main()
    r = ledger.load(tmp_path / "ledger.csv")[0]
    assert (r["pick_correct"], r["fh_correct"], r["total_error"]) == ("1", "1", f"{135 - float(r['total']):.1f}")
    assert "1-0" in (tmp_path / "docs" / "results.html").read_text()


def test_missing_key_is_clear(monkeypatch):
    monkeypatch.delenv("CBBD_API_KEY", raising=False)
    with pytest.raises(fetch.FetchError, match="CBBD_API_KEY"):
        fetch.team_stats(2027)
