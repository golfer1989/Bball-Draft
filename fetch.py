"""Data from CollegeBasketballData (api.collegebasketballdata.com).

Replaces the spreadsheet's web pulls (RealGM blocks GitHub's servers):
  RealGM Team / Opponent Totals  -> team_stats()   (team + opponent season stats)
  RealGM schedule + scores       -> games()        (schedule, finals, halftime scores)
  TeamRankings 1H PPG "Last 3"   -> first_half_last3()  (computed from halftime scores)

Needs the API key in the CBBD_API_KEY environment variable (a GitHub secret).
About 3-4 API calls per daily build.
"""
import os
import time
from datetime import datetime, timedelta, timezone

import requests

import config

BASE = "https://api.collegebasketballdata.com"


class FetchError(Exception):
    pass


def _get(path, params, tries=4, pause=5):
    key = os.environ.get("CBBD_API_KEY", "").strip()
    if not key:
        raise FetchError("CBBD_API_KEY is not set (add it under Settings > Secrets and variables > Actions)")
    last = None
    for i in range(tries):
        try:
            r = requests.get(BASE + path, params=params, timeout=60,
                             headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
            if r.status_code == 200:
                return r.json()
            if r.status_code in (401, 403):
                raise FetchError(f"{path}: HTTP {r.status_code} - API key rejected")
            last = f"HTTP {r.status_code}: {r.text[:200]}"
        except requests.RequestException as e:
            last = str(e)
        time.sleep(pause * (i + 1))
    raise FetchError(f"{path}: {last}")


# ---------------- team + opponent season stats ----------------
def _per_game(u, games, name):
    fg, ft, reb, tov, pts = u["fieldGoals"], u["freeThrows"], u["rebounds"], u["turnovers"], u["points"]
    g = float(games)
    return {
        "name": name, "GP": games,
        "PPG": pts["total"] / g,
        "FGA": fg["attempted"] / g, "FG%": fg["made"] / fg["attempted"],
        "FTA": ft["attempted"] / g, "FT%": (ft["made"] / ft["attempted"]) if ft["attempted"] else 0.0,
        "ORB": reb["offensive"] / g, "DRB": reb["defensive"] / g,
        "TOV": tov["total"] / g,
    }


def parse_team_stats(rows):
    """CBBD /stats/team/season rows -> (team, opp, season_label) keyed by teamId.
    Division I only (non-D1 schools come back with no conference), like the spreadsheet."""
    team, opp, label = {}, {}, ""
    for r in rows:
        try:
            if not r.get("games") or not r.get("conference"):
                continue
            team[r["teamId"]] = _per_game(r["teamStats"], r["games"], r["team"])
            opp[r["teamId"]] = _per_game(r["opponentStats"], r["games"], r["team"])
            label = r.get("seasonLabel") or label
        except (KeyError, TypeError, ZeroDivisionError):
            continue
    if len(label) == 8 and label.isdigit():          # "20252026" -> "2025-26"
        label = f"{label[:4]}-{label[6:]}"
    return team, opp, label


def team_stats(season):
    return _get("/stats/team/season", {"season": season})


# ---------------- team info: logos, colors, mascots (for the website) ----------------
def teams():
    return _get("/teams", {})


def parse_teams(rows):
    """{team_id (str): {mascot, color, logo, abbr}}. Prefers the logo variant made for dark
    backgrounds, since the site shows logos on a disc of the team's own color."""
    out = {}
    for t in rows or []:
        logos = [u for u in (t.get("logos") or []) if u]
        dark = [u for u in logos if "dark" in u.lower()]
        out[str(t.get("id"))] = {
            "mascot": t.get("mascot") or "",
            "color": t.get("primaryColor") or t.get("secondaryColor") or "",
            "logo": (dark or logos or [""])[0],
            "abbr": t.get("abbreviation") or "",
        }
    return out


# ---------------- games: schedule, finals, halftime ----------------
def _et(iso):
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(config.ET)


def parse_games(rows):
    out = []
    for g in rows:
        try:
            start = _et(g["startDate"])
        except (KeyError, ValueError, TypeError):
            continue
        final = g.get("status") == "final" and g.get("homePoints") is not None
        hp, ap = g.get("homePeriodPoints") or [], g.get("awayPeriodPoints") or []
        out.append({
            "date": start.date().isoformat(),
            "when": "TBD" if g.get("startTimeTbd") else start.strftime("%b %-d, %Y %-I:%M %p ET"),
            "start": start.isoformat(),
            "away_id": g.get("awayTeamId"), "away": g.get("awayTeam") or "",
            "home_id": g.get("homeTeamId"), "home": g.get("homeTeam") or "",
            "neutral": bool(g.get("neutralSite")),
            "status": g.get("status") or "",
            "away_pts": g.get("awayPoints") if final else None,
            "home_pts": g.get("homePoints") if final else None,
            "away_h1": ap[0] if final and ap else None,
            "home_h1": hp[0] if final and hp else None,
        })
    return out


def games(start_date, end_date):
    """All games tipping between two ET dates (inclusive). Max 3,000 per call."""
    s = datetime.combine(start_date, datetime.min.time(), config.ET).astimezone(timezone.utc)
    e = datetime.combine(end_date + timedelta(days=1), datetime.min.time(), config.ET).astimezone(timezone.utc)
    return _get("/games", {"startDateRange": s.strftime("%Y-%m-%dT%H:%M:%SZ"),
                           "endDateRange": e.strftime("%Y-%m-%dT%H:%M:%SZ")})


def first_half_last3(game_list, before_date):
    """1st-half points per game over each team's last 3 finished games before before_date
    (same idea as TeamRankings' 'Last 3' column the spreadsheet used)."""
    hist = {}
    for g in sorted(game_list, key=lambda g: g["start"]):
        if g["date"] >= before_date or g["away_h1"] is None:
            continue
        hist.setdefault(g["away_id"], []).append(g["away_h1"])
        hist.setdefault(g["home_id"], []).append(g["home_h1"])
    return {t: sum(v[-3:]) / len(v[-3:]) for t, v in hist.items() if t is not None and v}
