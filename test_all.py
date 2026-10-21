"""Run with:  python -m pytest -q tests"""
import json
from pathlib import Path

import pytest

from cbb import config, fetch, ledger, model, site

FX = Path(__file__).parent / "fixtures"


def fx(name):
    return (FX / name).read_text(encoding="utf-8")


# ---------------- parsers (fixtures are trimmed copies of the real pages) ----------------
def test_realgm_stats_parser():
    s = fetch.parse_realgm_stats(fx("realgm_stats.html"))
    assert list(s) == [254, 253, 257, 256]
    a = s[254]
    assert a["name"] == "Arkansas" and a["GP"] == 37 and a["PPG"] == 88.3
    assert a["FG%"] == 0.501 and a["FTA"] == 22.7 and a["ORB"] == 9.6 and a["DRB"] == 23.3
    assert a["TOV"] == 8.7 and a["PF"] == 16.3 and a["FT%"] == 0.751


def test_schedule_parser_finals():
    g = fetch.parse_realgm_schedule(fx("realgm_schedule_final.html"))
    assert len(g) == 3
    assert (g[0]["away"], g[0]["away_id"], g[0]["home"], g[0]["home_id"]) == ("La Salle", 20, "Davidson", 269)
    assert (g[0]["away_pts"], g[0]["home_pts"]) == (64, 71)   # box score: LASAL 64, DAV 71
    assert g[0]["when"] == "Mar 1, 2026 12:00 PM ET"


def test_schedule_parser_preview_and_non_d1():
    g = fetch.parse_realgm_schedule(fx("realgm_schedule_preview.html"))
    assert len(g) == 3
    assert g[0]["away_id"] is None and g[0]["away"] == "Bethesda University"
    assert g[1]["away_id"] == 276 and g[1]["home_id"] == 263 and g[1]["away_pts"] is None


def test_teamrankings_parser():
    v = fetch.parse_tr_first_half(fx("tr_first_half.html"), "Last 3")
    assert v == {"Michigan": 34.3, "Alabama": 44.7, "Miami OH": 42.7}
    with pytest.raises(fetch.FetchError):
        fetch.parse_tr_first_half(fx("tr_first_half.html"), "Nope")


# ---------------- model math ----------------
T = {"name": "A", "PPG": 80.0, "FGA": 60.0, "FTA": 20.0, "TOV": 10.0, "FG%": 0.48, "FT%": 0.75,
     "ORB": 10.0, "DRB": 25.0}
O = {"name": "A", "PPG": 70.0, "FGA": 58.0, "FTA": 18.0, "TOV": 12.0, "FG%": 0.42, "FT%": 0.70,
     "ORB": 9.0, "DRB": 24.0}


def test_rating_by_hand():
    r = model.team_rating(T, O)
    tov = 10 / (60 + 0.44 * 20 + 10)
    otov = 12 / (58 + 0.44 * 18 + 12)
    orb = 10 / (10 + 24)
    oorb = 9 / (9 + 25)
    off = 0.4 * 0.48 + 0.25 * (1 - tov) + 0.2 * orb + 0.15 * 0.75
    de = 0.4 * (1 - 0.42) + 0.25 * otov + 0.2 * (1 - oorb) + 0.15 * (1 - 0.70)
    assert r["tov_pct"] == pytest.approx(tov)
    assert r["rating"] == pytest.approx(off + de)
    assert r["ppg"] == pytest.approx(75.0)


def test_predict_rules():
    rat = {1: {"rating": 1.10, "ppg": 75.0}, 2: {"rating": 1.20, "ppg": 70.0}}
    g = {"away_id": 1, "away": "Away U", "home_id": 2, "home": "Home St", "when": "x"}
    p = model.predict(g, rat, {1: 40.0, 2: 35.0})
    assert p["pick"] == "Home St" and p["differential"] == pytest.approx(0.10)
    assert p["strong_pick"] == "Home St"          # 0.10 > 0.055
    assert p["total"] == pytest.approx(145.0)
    assert p["fh_pick"] == "Away U" and p["fh_margin"] == pytest.approx(5.0)
    # tie -> away (sheet: IF(H-G>0,home,away)); 1H tie -> home (sheet: IF(N>O,away,home))
    rat[2]["rating"] = 1.10
    p = model.predict(g, rat, {1: 30.0, 2: 30.0})
    assert p["pick"] == "Away U" and p["strong_pick"] == "" and p["fh_pick"] == "Home St"
    # unrated team -> no pick
    assert model.predict({**g, "away_id": None}, rat, {})["pick"] is None


def test_season_label():
    from datetime import date
    assert config.season_for(date(2026, 11, 5)) == 2027
    assert config.season_for(date(2027, 3, 15)) == 2027


# ---------------- ledger ----------------
def test_lock_is_idempotent_and_grades():
    rows = []
    preds = [{"when": "Mar 1, 2026 12:00 PM ET", "away_id": 20, "away": "La Salle", "home_id": 269,
              "home": "Davidson", "away_rating": 1.3, "home_rating": 1.4, "pick": "Davidson",
              "differential": 0.1, "strong_pick": "Davidson", "total": 140.0, "fh_pick": "Davidson",
              "fh_margin": 2.0},
             {"when": "Mar 1, 2026 12:00 PM ET", "away_id": 304, "away": "Tulane", "home_id": 74,
              "home": "South Florida", "away_rating": 1.5, "home_rating": 1.45, "pick": "Tulane",
              "differential": 0.05, "strong_pick": "", "total": 150.0, "fh_pick": None, "fh_margin": None}]
    assert ledger.lock(rows, "2026-03-01", preds, 2026, "t") == 2
    preds[0]["pick"] = "La Salle"                       # a re-run must not change a locked pick
    assert ledger.lock(rows, "2026-03-01", preds, 2026, "t2") == 0
    assert rows[0]["pick"] == "Davidson"
    n = ledger.grade(rows, "2026-03-01", fetch.parse_realgm_schedule(fx("realgm_schedule_final.html")))
    assert n == 2
    r0, r1 = rows
    assert (r0["away_pts"], r0["home_pts"], r0["pick_correct"], r0["strong_correct"]) == ("64", "71", "1", "1")
    assert r0["total_error"] == "-5.0"                  # 135 actual - 140 projected
    assert (r1["pick_correct"], r1["strong_correct"]) == ("0", "")   # USF won 90-62


# ---------------- end to end (network mocked with the fixtures) ----------------
def test_end_to_end(tmp_path, monkeypatch):
    import run_daily

    stats = fetch.parse_realgm_stats(fx("realgm_stats.html"))
    # build a 320-team league so the "enough teams" check passes
    team = {i: dict(stats[254], name=f"T{i}") for i in range(1, 321)}
    team[263] = dict(stats[253], name="Tennessee")
    team[276] = dict(stats[257], name="Wofford")
    opp = {i: dict(stats[256], name=v["name"]) for i, v in team.items()}
    for v in team.values():
        v["GP"] = 5

    monkeypatch.setattr(run_daily, "DATA", tmp_path)
    monkeypatch.setattr(run_daily, "RAW", tmp_path / "raw")
    monkeypatch.setattr(ledger, "LEDGER", tmp_path / "ledger.csv")
    monkeypatch.setattr(ledger.load, "__defaults__", (tmp_path / "ledger.csv",))
    monkeypatch.setattr(ledger.save, "__defaults__", (tmp_path / "ledger.csv",))
    monkeypatch.setattr(site.write, "__defaults__", (tmp_path / "docs",))
    (tmp_path / "teamrankings_names.csv").write_text(
        "teamrankings_name,realgm_id,realgm_name\nAlabama,263,Tennessee\nMichigan,276,Wofford\n")
    monkeypatch.setattr(fetch, "realgm_stats", lambda s, w: team if w == "team" else opp)
    monkeypatch.setattr(fetch, "tr_first_half",
                        lambda d: fetch.parse_tr_first_half(fx("tr_first_half.html"), "Last 3"))
    monkeypatch.setattr(fetch, "realgm_schedule",
                        lambda d: fetch.parse_realgm_schedule(fx("realgm_schedule_preview.html")))
    monkeypatch.setattr("sys.argv", ["run_daily.py", "--date", "2026-11-03"])
    run_daily.main()

    rows = ledger.load(tmp_path / "ledger.csv")
    assert len(rows) == 1                                # Bethesda (non-D1) dropped; Fort Wayne/Duquesne not in league
    r = rows[0]
    assert (r["away"], r["home"]) == ("Wofford", "Tennessee")
    exp = model.team_rating(team[263], opp[263])["rating"] - model.team_rating(team[276], opp[276])["rating"]
    assert float(r["differential"]) == pytest.approx(abs(exp), abs=1e-4)
    assert r["fh_pick"] == "Tennessee"                   # Alabama-row 44.7 vs Michigan-row 34.3
    html = (tmp_path / "docs" / "index.html").read_text()
    assert "Wofford" in html and "Tennessee" in html
    assert (tmp_path / "docs" / "results.html").exists()
    assert (tmp_path / "last_build.txt").read_text().strip() == "2026-11-03"
    assert json.loads((tmp_path / "raw" / "team_2027.json").read_text())
