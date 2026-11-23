"""Team-by-team data behind the Rankings page and the team pages.

Nothing here predicts anything new: it lays out what the model already has. For every team that
is where it stands (rank, rating in points, offense, defense, schedule), the eight numbers the
rating is built from with their national ranks, every game it has played with the model's pick
next to the result, and the games coming up. The pages themselves are drawn in webpage.py."""
import re
import unicodedata
from datetime import date, datetime, timedelta

import config
import model

# The model's eight inputs, in the order of their weight (config.W_SHOOT, W_TOV, W_REB, W_FT).
# (key, what it is, weight setting, which way is good for the team: +1 higher, -1 lower)
# The DEFENSE numbers are the opponents' (what teams manage against this one).
OFFENSE = (("fg", "Field goal %", "W_SHOOT", 1), ("tov", "Turnover rate", "W_TOV", -1),
           ("orb", "Offensive rebound rate", "W_REB", 1), ("ft", "Free throw %", "W_FT", 1))
DEFENSE = (("opp_fg", "Field goal %", "W_SHOOT", -1), ("opp_tov", "Turnover rate", "W_TOV", 1),
           ("opp_orb", "Offensive rebound rate", "W_REB", -1), ("opp_ft", "Free throw %", "W_FT", -1))
MOVE_DAYS = 7          # the Rankings page shows how far a team has moved over this many days


def slug(name):
    """The team page's file name, the way the school is usually written in a web address:
    'San José State' -> 'san-jose-state', 'Texas A&M' -> 'texas-am', "Saint Mary's" -> 'saint-marys',
    'William & Mary' -> 'william-mary', 'Miami (OH)' -> 'miami-oh'."""
    plain = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    plain = re.sub(r"(?<=[a-z0-9])&(?=[a-z0-9])", "", plain.replace("'", ""))       # A&M -> am, Hawai'i -> hawaii
    return re.sub(r"[^a-z0-9]+", "-", plain).strip("-") or "team"


def team_path(name):
    return f"teams/{slug(name)}.html"


def points(rat):
    """{team_id: rating in points} - how many points better (or worse) than the average rated team
    on a neutral floor. The model's margin for a game is the difference of two of these numbers,
    plus home court."""
    if not rat:
        return {}
    mean = sum(r["rating"] for r in rat.values()) / len(rat)
    return {t: config.POINTS_PER_RATING * (r["rating"] - mean) for t, r in rat.items()}


def factors(team, opp):
    """This season's eight inputs for every team, each with its national rank (1 = best for the
    team, so a low opponent shooting % ranks high).
    team/opp = fetch.parse_team_stats output. Returns {team_id: {key: (value, rank)}, ...}, n teams."""
    vals = {}
    for tid, t in team.items():
        o = opp.get(tid)
        if not o:
            continue
        try:
            r = model.team_rating(t, o)
        except (TypeError, ZeroDivisionError, KeyError):
            continue
        vals[tid] = {"fg": t["FG%"], "tov": r["tov_pct"], "orb": r["reb_pct"], "ft": t["FT%"],
                     "opp_fg": o["FG%"], "opp_tov": r["opp_tov_pct"], "opp_orb": r["opp_reb_pct"], "opp_ft": o["FT%"],
                     "ppg": t["PPG"], "opp_ppg": o["PPG"]}
    out = {t: {} for t in vals}
    for key, _, _, good in OFFENSE + DEFENSE + (("ppg", "", "", 1), ("opp_ppg", "", "", -1)):
        order = sorted(vals, key=lambda t: -good * vals[t][key])
        for i, t in enumerate(order, 1):
            out[t][key] = (vals[t][key], i)
    return out, len(vals)


def averages(fac):
    """Division I average of each input (plain mean over the teams)."""
    if not fac:
        return {}
    keys = next(iter(fac.values())).keys()
    return {k: sum(f[k][0] for f in fac.values()) / len(fac) for k in keys}


def _game_rows(season_games, today_rows, week_games, names):
    """One list of every game there is to show, oldest first:
    {"date", "when", "away_id", "home_id", "away", "home", "away_pts", "home_pts", "neutral", "state"}
    state: "final", "today" (on today's slate, not final yet) or "ahead".
    season_games = [[date, away_id, home_id, away_pts, home_pts, neutral], ...] (through yesterday),
    today_rows = today's ledger rows, week_games = fetch.parse_games rows for the coming days."""
    out, seen = [], set()

    def add(g):
        key = (g["date"], frozenset((g["away_id"], g["home_id"])))
        if key not in seen and g["away_id"] != g["home_id"]:
            seen.add(key)
            out.append(g)
    for r in today_rows:                                   # the ledger knows today's finals first
        final = r["away_pts"] != ""
        add({"date": r["date"], "when": r["when"], "away_id": int(r["away_id"]), "home_id": int(r["home_id"]),
             "away": r["away"], "home": r["home"], "neutral": r.get("neutral") == "1",
             "away_pts": int(r["away_pts"]) if final else None, "home_pts": int(r["home_pts"]) if final else None,
             "state": "final" if final else "today"})
    for d, a, h, ap, hp, neutral in season_games:
        add({"date": d, "when": "", "away_id": a, "home_id": h, "away": names.get(a, ""), "home": names.get(h, ""),
             "away_pts": ap, "home_pts": hp, "neutral": bool(neutral), "state": "final"})
    for g in week_games:
        if g.get("away_id") is None or g.get("home_id") is None:
            continue
        final = g.get("away_pts") is not None and g.get("home_pts") is not None and g["away_pts"] != g["home_pts"]
        add({"date": g["date"], "when": g.get("when", ""), "away_id": g["away_id"], "home_id": g["home_id"],
             "away": g.get("away") or names.get(g["away_id"], ""), "home": g.get("home") or names.get(g["home_id"], ""),
             "neutral": bool(g.get("neutral")), "away_pts": g["away_pts"] if final else None,
             "home_pts": g["home_pts"] if final else None, "state": "final" if final else "ahead"})
    out.sort(key=lambda g: (g["date"], _tip_sort(g["when"])))
    return out


def _tbd(name):
    """A side of a bracket game that is not decided yet (the feed's "TBD")."""
    return (name or "").strip().upper() in ("", "TBD", "TBA")


def _tip_sort(when):
    try:
        return datetime.strptime((when or "").replace(" ET", ""), "%b %d, %Y %I:%M %p")
    except ValueError:
        return datetime.max


def schedules(rat, season_games, ledger_rows, today_str, week_games=(), names=None):
    """{team_id: [game, ...]} for every rated team, oldest game first. Each game, seen from that team:
      date, when, opp_id, opp (name), where ("home", "away" or "neutral"), state ("final", "today",
      "ahead"), pts / opp_pts and won (finals), and what the model said:
      pick = {"own": the model had this team, "pf", "pa": projected score, "hit": True/False/None,
              "official": locked pick (False = an early projection for a game still ahead), "path": game page}
    A game against a team the model does not rate (not Division I) carries no pick."""
    names = names or {}
    picks = {}
    for r in ledger_rows:
        picks[(r["date"], int(r["away_id"]), int(r["home_id"]))] = r
    todays = [r for r in ledger_rows if r["date"] == today_str]
    games = _game_rows(season_games, todays, week_games, names)
    out = {t: [] for t in rat}
    for g in games:
        row = picks.get((g["date"], g["away_id"], g["home_id"]))
        flipped = False
        if row is None:
            row = picks.get((g["date"], g["home_id"], g["away_id"]))        # the feed lists it the other way round
            flipped = row is not None
        if row is not None and g["state"] == "final" and row.get("away_pts") not in ("", None):
            # the score the pick was graded on, the one the Results page and the game's own page show
            # (now and then the feed corrects a final by a point or two a day later)
            la, lh = int(row["away_pts"]), int(row["home_pts"])
            g = dict(g, away_pts=lh if flipped else la, home_pts=la if flipped else lh)
        proj = None                                                          # (away pts, home pts, pick name, official, hit, path)
        if row is not None and row.get("pick"):
            pa, ph = _score(row["total"], row["differential"], row["pick"] == row["home"])
            if flipped:
                pa, ph = ph, pa
            hit = {"1": True, "0": False}.get(row.get("pick_correct"))
            proj = (pa, ph, row["pick"], True, hit, f'games/{row["date"]}/{_old_slug(row["away"])}-vs-{_old_slug(row["home"])}.html')
        elif g["state"] == "ahead" and g["away_id"] in rat and g["home_id"] in rat:
            p = model.predict({"away_id": g["away_id"], "home_id": g["home_id"], "away": g["away"], "home": g["home"],
                               "neutral": g["neutral"]}, rat, {})
            if p.get("pick"):
                pa, ph = _score(p["total"], p["differential"], p["pick"] == g["home"])
                proj = (pa, ph, p["pick"], False, None, "")
        for me, other, mine, theirs, where in ((g["away_id"], g["home_id"], "away", "home", "away"),
                                               (g["home_id"], g["away_id"], "home", "away", "home")):
            if me not in out:
                continue
            opp = g[theirs] or names.get(other, "")
            item = {"date": g["date"], "when": g["when"], "opp_id": other, "opp": "TBD" if _tbd(opp) else opp,
                    "where": "neutral" if g["neutral"] else where, "state": g["state"], "rated": other in rat}
            if g["state"] == "final":
                item.update(pts=g[mine + "_pts"], opp_pts=g[theirs + "_pts"], won=g[mine + "_pts"] > g[theirs + "_pts"])
            if proj:
                pa, ph, pick, official, hit, path = proj
                item["pick"] = {"own": pick == g[mine], "pf": ph if mine == "home" else pa, "pa": pa if mine == "home" else ph,
                                "official": official, "hit": hit, "path": path}
            out[me].append(item)
    return out


def _old_slug(name):
    """The slug game pages have always used (webpage.slug): kept so links land on the pages that exist."""
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-") or "team"


def _score(total, differential, home_pick):
    """Projected (away, home) score from a pick's total and rating gap. The same arithmetic, step
    for step, as webpage.predicted_score, so a team page never shows a different score from the
    game's own card."""
    total, m = float(total), max(config.POINTS_PER_RATING * float(differential), 1.0)
    win, lose = round(total / 2 + m / 2), round(total / 2 - m / 2)
    if win <= lose:
        win = lose + 1
    return (lose, win) if home_pick else (win, lose)


def record(games):
    """(wins, losses) over a team's finished games."""
    done = [g for g in games if g["state"] == "final"]
    return sum(1 for g in done if g["won"]), sum(1 for g in done if not g["won"])


def model_record(games):
    """(right, wrong) for the model's locked picks in a team's finished games."""
    graded = [g["pick"]["hit"] for g in games if g.get("pick") and g["pick"]["official"] and g["pick"]["hit"] is not None]
    return sum(1 for h in graded if h), sum(1 for h in graded if not h)


def moves(history, today_str, ranks, days=MOVE_DAYS):
    """How many places each team has moved since the snapshot closest to `days` days ago (positive
    = up). history = {date: {team id as str: rank}}, ranks = {team_id: rank today}.
    Returns ({team_id: places}, the date compared with) - ({}, "") until there is a snapshot from
    an earlier day."""
    earlier = sorted(d for d in history if d < today_str)
    if not earlier:
        return {}, ""
    target = (date.fromisoformat(today_str) - timedelta(days=days)).isoformat()
    base = max((d for d in earlier if d <= target), default=earlier[0])
    then = history[base]
    return {t: then[str(t)] - r for t, r in ranks.items() if str(t) in then}, base


def remember(history, today_str, ranks, keep_days=250):
    """Add today's ranks to the history ({date: {team id: rank}}) and drop anything older than a
    season. Returns the history."""
    history[today_str] = {str(t): r for t, r in ranks.items()}
    floor = (date.fromisoformat(today_str) - timedelta(days=keep_days)).isoformat()
    for d in [d for d in history if d < floor]:
        del history[d]
    return history


def profiles(rat, rk, team, opp, raw_stats, teams, sched, history=None, today_str=""):
    """Everything the two pages show about each team, best team first.
    rat = the ratings the picks use (blended early in the season), rk = writeup.ranks(rat),
    team/opp = this season's parsed stats, raw_stats = the feed's rows for this season (record,
    pace), teams = fetch.parse_teams output, sched = schedules(...)."""
    pts = points(rat)
    fac, n_fac = factors(team, opp)
    raw = {r.get("teamId"): r for r in raw_stats or []}
    mv, since = moves(history or {}, today_str, {t: rk[t]["rank"] for t in rat}) if today_str else ({}, "")
    out = []
    for tid, r in rat.items():
        info = teams.get(str(tid)) or {}
        if not info.get("conf"):
            continue                    # a carried-over rating for a school that is not in Division I this season
        s = raw.get(tid) or {}
        games = sched.get(tid, [])
        w, l = record(games)
        if s.get("wins") is not None and s.get("losses") is not None and (s["wins"] + s["losses"]) >= w + l:
            w, l = s["wins"], s["losses"]           # the feed's own count includes games it lists nowhere else
        out.append({
            "id": tid, "name": r.get("name") or "", "slug": slug(r.get("name") or ""), "conf": info.get("conf") or "",
            "mascot": info.get("mascot") or "", "rank": rk[tid]["rank"], "n": rk[tid]["n"], "points": pts[tid],
            "off_rank": rk[tid]["off"], "def_rank": rk[tid]["def"], "sos_rank": rk[tid]["sos"],
            "blend": r.get("blend", 1.0), "new_team": bool(r.get("new_team")), "gp": (team.get(tid) or {}).get("GP", 0),
            "wins": w, "losses": l, "pace": s.get("pace"), "factors": fac.get(tid), "n_factors": n_fac,
            "move": mv.get(tid), "move_since": since, "games": games, "model_record": model_record(games),
        })
    out.sort(key=lambda p: p["rank"])
    for i, p in enumerate(out, 1):
        p["place"] = i                  # position on the page (the same as rank unless a school was left out)
    return out


def conferences(profs):
    """Conference strength, strongest first: [{"conf", "n", "avg" (points), "best" (profile),
    "top25", "top100"}]."""
    by = {}
    for p in profs:
        by.setdefault(p["conf"], []).append(p)
    out = [{"conf": c, "n": len(ps), "avg": sum(p["points"] for p in ps) / len(ps), "best": min(ps, key=lambda p: p["rank"]),
            "top25": sum(1 for p in ps if p["rank"] <= 25), "top100": sum(1 for p in ps if p["rank"] <= 100)}
           for c, ps in by.items() if c]
    out.sort(key=lambda c: -c["avg"])
    return out
