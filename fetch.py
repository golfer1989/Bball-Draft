"""Data from CollegeBasketballData (api.collegebasketballdata.com).

Replaces the spreadsheet's web pulls (RealGM blocks GitHub's servers):
  RealGM Team / Opponent Totals  -> team_stats()   (team + opponent season stats)
  RealGM schedule + scores       -> games()        (schedule, finals, halftime scores)
  TeamRankings 1H PPG "Last 3"   -> first_half_last3()  (computed from halftime scores)

Needs the API key in the CBBD_API_KEY environment variable (a GitHub secret).
API calls: about 7 for the overnight build, 2 for each daytime refresh, 1 for a night score
update (about 17 a day before the night updates; see CALLS_LEFT below for the monthly allowance).
"""
import os
import time
from datetime import datetime, timedelta, timezone

import requests

import config

BASE = "https://api.collegebasketballdata.com"

# The data plan has a monthly allowance of calls (1,000 on the free plan, and one key covers
# college football as well, so a football site on the same key draws from the same 1,000).
# Every counted response says how many are left in its X-CallLimit-Remaining header. The last
# value seen is kept here; build.py saves it to data/api_calls_left.txt and the night score
# updates stand down when it runs low. None = no response has reported it yet.
CALLS_LEFT = None


class FetchError(Exception):
    pass


def _note_allowance(headers):
    global CALLS_LEFT
    try:
        CALLS_LEFT = int(float(headers.get("X-CallLimit-Remaining")))
    except (TypeError, ValueError):
        pass


def _get(path, params, tries=4, pause=5):
    global CALLS_LEFT
    key = os.environ.get("CBBD_API_KEY", "").strip()
    if not key:
        raise FetchError("CBBD_API_KEY is not set (add it under Settings > Secrets and variables > Actions)")
    last = None
    for i in range(tries):
        try:
            r = requests.get(BASE + path, params=params, timeout=60,
                             headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
            if r.status_code == 200:
                _note_allowance(r.headers)
                return r.json()
            if r.status_code in (401, 403):
                raise FetchError(f"{path}: HTTP {r.status_code} - API key rejected")
            if r.status_code == 429 and "quota" in r.text.lower():       # "Monthly call quota exceeded."
                CALLS_LEFT = 0                                            # retrying cannot help until the 1st
                raise FetchError(f"{path}: this month's data-call allowance is used up (it resets on the 1st)")
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
            "espn": str(t.get("sourceId") or ""),          # ESPN team id, used for live scores
            "conf": t.get("conference") or "",
        }
    return out


# ---------------- betting lines (spread, over/under) ----------------
PROVIDER_ORDER = ["consensus", "ESPN Bet", "DraftKings", "Draft Kings", "FanDuel", "Bovada", "William Hill (New Jersey)"]


def lines(start_date, end_date):
    s = datetime.combine(start_date, datetime.min.time(), config.ET).astimezone(timezone.utc)
    e = datetime.combine(end_date + timedelta(days=1), datetime.min.time(), config.ET).astimezone(timezone.utc)
    return _get("/lines", {"startDateRange": s.strftime("%Y-%m-%dT%H:%M:%SZ"),
                           "endDateRange": e.strftime("%Y-%m-%dT%H:%M:%SZ")})


def _num_or_none(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def parse_lines(rows):
    """{(away_id, home_id): {"fav": team name or "", "spread": points (>=0), "total": points, "book": name}}
    One sportsbook per game (consensus first). The favorite comes from the moneylines when the
    book has them (lower moneyline = favorite), otherwise from the spread's sign, which the
    API gives from the home team's side (-6.5 = home favored by 6.5)."""
    out = {}
    for g in rows or []:
        books = [b for b in (g.get("lines") or []) if _num_or_none(b.get("spread")) is not None
                 or _num_or_none(b.get("overUnder")) is not None]
        if not books:
            continue
        rank = {p.lower(): i for i, p in enumerate(PROVIDER_ORDER)}
        full = lambda x: sum(_num_or_none(x.get(k)) is not None                      # noqa: E731
                             for k in ("spread", "overUnder", "homeMoneyline", "awayMoneyline"))
        b = sorted(books, key=lambda x: (-full(x), rank.get((x.get("provider") or "").lower(), 99)))[0]
        spread, total = _num_or_none(b.get("spread")), _num_or_none(b.get("overUnder"))
        hml, aml = _num_or_none(b.get("homeMoneyline")), _num_or_none(b.get("awayMoneyline"))
        fav = ""
        if spread is not None and abs(spread) < 0.25:
            fav, spread = "", 0.0                                     # pick'em
        elif hml is not None and aml is not None and hml != aml:
            fav = g.get("homeTeam") if hml < aml else g.get("awayTeam")
        elif spread is not None:
            fav = g.get("homeTeam") if spread < 0 else g.get("awayTeam")
        out[(g.get("awayTeamId"), g.get("homeTeamId"))] = {
            "fav": fav or "", "spread": abs(spread) if spread is not None else None,
            "total": total, "book": b.get("provider") or "", "aml": aml, "hml": hml}
    return out


# ---------------- ESPN's schedule (for games the data feed lists against "TBD") ----------------
ESPN_BOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"


def espn_matchups(day):
    """{ESPN game id: (away ESPN team id, home ESPN team id)} for one day, from ESPN's public
    scoreboard (the same one the site's pages read for live scores). One request, no key, and not
    counted against the data plan. Raises FetchError when ESPN can't be reached or answers oddly;
    the caller treats that as "no help today", never as a reason to stop the build."""
    try:
        r = requests.get(ESPN_BOARD, params={"groups": 50, "limit": 500, "dates": day.strftime("%Y%m%d")}, timeout=20,
                         headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0 (tipoffedge.com schedule check)"})
        if r.status_code != 200:
            raise FetchError(f"ESPN scoreboard: HTTP {r.status_code}")
        out = {}
        for e in r.json().get("events") or []:
            comp = (e.get("competitions") or [{}])[0]
            sides = {c.get("homeAway"): str((c.get("team") or {}).get("id") or "") for c in comp.get("competitors") or []}
            if e.get("id") and sides.get("away") and sides.get("home"):
                out[str(e["id"])] = (sides["away"], sides["home"])
        return out
    except (requests.RequestException, ValueError, AttributeError, TypeError) as exc:
        raise FetchError(f"ESPN scoreboard: {exc}") from exc


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
        # A real final has a winner. The API sometimes lists a game that was never played (an event
        # bracket's placeholder matchup, a canceled game) as "final" 0-0; that is not a result.
        final = (g.get("status") == "final" and g.get("homePoints") is not None and g.get("awayPoints") is not None
                 and g.get("homePoints") != g.get("awayPoints"))
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
