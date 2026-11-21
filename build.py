"""Daily build: grade recent games, pull fresh stats + today's schedule, lock picks,
rebuild the website. Run by GitHub Actions each morning.
By hand:  set CBBD_API_KEY=...  then  python build.py  [--date 2026-11-15]

Three kinds of run (the workflow picks one):
  python build.py            overnight build: everything, about 7 data calls
  python build.py --refresh  before each tip-time block: today's schedule + lines only, 2 calls
  python build.py --scores   night score update: grades the games on the board that have gone
                             final, adds nothing new, at most 1 call (none when nothing is due)"""
import argparse
import json
import statistics
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import bets, config, fetch, ledger, model, share, video, webpage as site, writeup

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
RAW = DATA / "raw"


def log(*a):
    print(*a, flush=True)


REFRESH = False          # set by --refresh: only today's schedule + lines are downloaded
SCORES = False           # set by --scores: night score update (implies REFRESH; only the schedule is downloaded)
LIVE_FEEDS = ("games_today", "lines_today")

# ---- night score updates (--scores) ----
# How long after tip-off a game can be final. Measured on 70 saved snapshots (Nov 5-18, 2026):
# 4% of games were marked final 105-120 minutes after tip, 78% at 135-150, 99% at 150-180.
SCORES_AFTER_TIP = 135
# ...and a game still not final this many minutes after tip was postponed, not running long.
SCORES_GIVE_UP = 300
# The data plan's monthly allowance (see fetch.CALLS_LEFT) has to last the regular builds until
# it resets on the 1st, so a score update only spends a call while at least this many per
# remaining day are left. The regular builds use about 17 a day; the rest of the margin is for
# runs by hand and for anything else on the same key. 30 a day is the most a 1,000-call plan can
# hold back and still allow score updates on the 1st of a 31-day month.
CALL_RESERVE_PER_DAY = 30


def calls_file():
    return DATA / "api_calls_left.txt"


def save_calls_left(stamp):
    """Write down the API's own count of calls left this month, when a response has reported it."""
    left = getattr(fetch, "CALLS_LEFT", None)          # None too with a fetch.py from before this was added
    if left is not None:
        calls_file().write_text(f"{left}\ndata-API calls left this month, as of {stamp}\n", encoding="utf-8")


def calls_left_saved():
    """The count saved by the last build that made a call, or None if there isn't one."""
    try:
        return int(calls_file().read_text(encoding="utf-8").split()[0])
    except (OSError, ValueError, IndexError):
        return None


def calls_held_back(now):
    """Calls kept for the regular builds from now until the allowance resets on the 1st (UTC)."""
    u = now.astimezone(timezone.utc).date()
    first_next = date(u.year + (u.month == 12), u.month % 12 + 1, 1)
    return CALL_RESERVE_PER_DAY * (first_next - u).days


def slate_date(now):
    """The day whose picks are on the site: the date of the last build, as long as that is today or
    yesterday in Eastern time. (After midnight Eastern the night's late games still belong to
    yesterday's slate; the overnight build is what starts the new day.)"""
    try:
        d = date.fromisoformat((DATA / "last_build.txt").read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    return d if 0 <= (now.date() - d).days <= 1 else None


def due_for_a_final(rows, day, now):
    """Ledger rows of that day that are not graded yet and tipped off long enough ago to be final.
    Games the last saved schedule lists as postponed or canceled are left out."""
    off = set()
    try:
        for g in json.loads((RAW / "games_today.json").read_text(encoding="utf-8")):
            if (g.get("status") or "").lower() in ("postponed", "cancelled", "canceled"):
                off.add((str(g.get("awayTeamId")), str(g.get("homeTeamId"))))
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    due = []
    for r in rows:
        if r["date"] != day or r["away_pts"] != "" or (str(r["away_id"]), str(r["home_id"])) in off:
            continue
        try:
            tip = datetime.strptime(r["when"].replace(" ET", ""), "%b %d, %Y %I:%M %p").replace(tzinfo=config.ET)
        except ValueError:
            continue                                   # tip time still to be announced
        if SCORES_AFTER_TIP <= (now - tip).total_seconds() / 60 <= SCORES_GIVE_UP:
            due.append(r)
    return due


def _is_tbd(name):
    return (name or "").strip().upper() in ("", "TBD", "TBA")


def _read_matchups(path, day=None):
    """{ESPN game id: [away ESPN team id, home ESPN team id]} from a small JSON file, {} if there is
    none. Two shapes are read: {"games": {...}, "date": "2026-11-18"} and the bare {...}. With day
    given, a file saved for another day counts as empty."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or (day and data.get("date") != day):
        return {}
    games = data.get("games", data)
    return {str(k): [str(x) for x in v][:2] for k, v in games.items() if isinstance(v, (list, tuple)) and len(v) >= 2}


def fill_tbd(raw_games, day):
    """Bracket games. When a game's opponent depends on an earlier round, the data feed lists it as
    "Rutgers vs TBD", and it can stay that way for hours after the matchup is set: on Nov 18, 2026 all
    four Players Era games still said TBD at four builds in a row, the model had nobody to rate the
    known team against, and the games got no pick.

    Every schedule row carries ESPN's id for the game, so the missing side is looked up there:
    in matchups.json (a hand-made list, for days ESPN turns GitHub's machines away), in what an
    earlier build today already found, and on ESPN's scoreboard right now. Only the TBD side of a
    row is filled, so the game keeps the order the feed gave it; a row ESPN can't settle either is
    left as it is and skipped like before. Rows are changed in place. Returns the rows it filled."""
    todo = [g for g in raw_games if _is_tbd(g.get("awayTeam")) or _is_tbd(g.get("homeTeam"))]
    if not todo:
        return []
    try:
        teams = json.loads((RAW / "teams.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log(f"  {len(todo)} games list an opponent as TBD, and there is no saved team list to look them up in")
        return []
    by_id = {t.get("id"): t for t in teams}
    by_espn = {str(t.get("sourceId")): t for t in teams if not _is_tbd(t.get("school"))}
    saved_file = RAW / "matchups_today.json"
    known = _read_matchups(ROOT / "matchups.json")
    known.update(_read_matchups(saved_file, day.isoformat()))
    espn_answered = False
    try:
        known.update({k: list(v) for k, v in fetch.espn_matchups(day).items()})
        espn_answered = True
    except AttributeError:
        pass                                             # a fetch.py from before this was added
    except fetch.FetchError as e:
        log(f"  ! {e} (bracket games are filled from matchups.json or an earlier build, if they are there)")
    filled = []
    for g in todo:
        pair = known.get(str(g.get("sourceId") or ""))
        if not pair or pair[0] == pair[1]:
            continue
        away_tbd, home_tbd = _is_tbd(g.get("awayTeam")), _is_tbd(g.get("homeTeam"))
        if away_tbd and home_tbd:
            want = {"away": pair[0], "home": pair[1]}
        else:
            side, other = ("home", "away") if home_tbd else ("away", "home")
            mine = str((by_id.get(g.get(f"{other}TeamId")) or {}).get("sourceId"))
            if mine not in pair:
                continue                                 # ESPN's game with this id is not this team's: leave the row alone
            want = {side: pair[1] if pair[0] == mine else pair[0]}
        found = {s: by_espn.get(e) for s, e in want.items()}
        if not all(found.values()):
            continue                                     # ESPN has no opponent yet either
        for s, t in found.items():
            g[f"{s}TeamId"], g[f"{s}Team"] = t.get("id"), t.get("school")
            g[f"{s}Conference"], g[f"{s}ConferenceId"] = t.get("conference"), t.get("conferenceId")
        filled.append(g)
    if filled:
        keep = {str(g["sourceId"]): known[str(g["sourceId"])] for g in filled}
        # espn_answered: whether ESPN could be reached from this machine in this build (worth knowing,
        # since GitHub's machines are sometimes turned away and then only the saved finds and the list help)
        saved_file.write_text(json.dumps({"date": day.isoformat(), "espn_answered": espn_answered, "games": keep}, indent=1),
                              encoding="utf-8")
        log(f"  filled in {len(filled)} opponents the feed lists as TBD: "
            + ", ".join(f"{g['awayTeam']} vs {g['homeTeam']}" for g in filled))
    if len(filled) < len(todo):
        log(f"  {len(todo) - len(filled)} games still list an opponent as TBD and are skipped")
    return filled


def orient_like_ledger(games, rows):
    """A pick is stored under away|home. When the feed later lists the same game the other way round
    (it happens with neutral-site bracket games), the feed's row is turned to match the pick, so the
    pick is found again for grading and the game does not get a second pick. Returns how many."""
    keys = {r["game_key"] for r in rows}
    n = 0
    for g in games:
        if (ledger.key(g["date"], g["away_id"], g["home_id"]) in keys
                or ledger.key(g["date"], g["home_id"], g["away_id"]) not in keys):
            continue
        for a, h in (("away_id", "home_id"), ("away", "home"), ("away_pts", "home_pts"), ("away_h1", "home_h1")):
            g[a], g[h] = g[h], g[a]
        n += 1
    return n


def ungrade_ties(rows):
    """A final cannot be a tie, so a row graded from one was graded from a game that was never played
    (the API listed an event's placeholder matchup as "final" 0-0; fetch.parse_games no longer
    accepts that). Those rows go back to ungraded. Returns the rows that were cleared."""
    cleared = []
    for r in rows:
        if r["away_pts"] != "" and r["away_pts"] == r["home_pts"]:
            for k in ("away_pts", "home_pts", "pick_correct", "strong_correct", "total_error", "fh_correct"):
                r[k] = ""
            cleared.append(r)
    return cleared


def bet_of_the_day(book, day, singles, day_rows):
    """The bet the site's "Game of the day" is built around, with its game: {"bet", "row", "final"},
    or None on a day with nothing to bet. Once the day's top bets are locked it is the #1 on that
    list, and it stays that game all day: the card shows the live score, then the result. Before the
    lock it is the best bet on the board right now. "final" is "70-75" (away-home) once graded."""
    by_game = {(str(r["away_id"]), str(r["home_id"])): r for r in day_rows}
    locked = sorted((b for b in book if b["date"] == day), key=lambda b: int(b["rank"]))
    for b in locked[:1] or list(singles[:1]):
        r = by_game.get((str(b["away_id"]), str(b["home_id"])))
        if r:
            bet = dict(b, odds=int(b["odds"]), chance=float(b["chance"]), edge=float(b["edge"]))
            return {"bet": bet, "row": r, "final": f'{r["away_pts"]}-{r["home_pts"]}' if r["away_pts"] != "" else ""}
    return None


def clip_mark():
    return DATA / "clip_game.txt"


def clip_game(day_rows, clip_path):
    """The game the daily clip on file was rendered for (today's ledger row), or None when there is
    no clip for today: none rendered yet, or daily.mp4 is still an earlier day's."""
    try:
        key = clip_mark().read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not key or not Path(clip_path).exists():
        return None
    return next((r for r in day_rows if r["game_key"] == key), None)


def clip_target(lead, has_bet, made_for):
    """The game the day's clip should show: the site's Game of the day, so the video and the Today
    page always name the same game. One exception: on a day with no bet the Game of the day is the
    biggest game still to play, which moves on as games tip off, and a clip that exists (and may
    already be posted) stays on the game it was made for."""
    return lead if has_bet or made_for is None else made_for


def _cache(name, loader):
    """Fetch with loader(); save to data/raw/<name>.json; on failure reuse the saved copy.
    In a --refresh run everything except today's schedule and lines comes from the saved copy
    (keeps API use low: ~2 calls per afternoon refresh)."""
    RAW.mkdir(parents=True, exist_ok=True)
    p = RAW / f"{name}.json"
    if REFRESH and name not in LIVE_FEEDS and p.exists():
        return json.loads(p.read_text(encoding="utf-8")), False
    try:
        val = loader()
        p.write_text(json.dumps(val), encoding="utf-8")
        return val, False
    except fetch.FetchError as e:
        log(f"  ! {name}: {e}")
        if p.exists():
            log(f"  using saved copy of {name}")
            return json.loads(p.read_text(encoding="utf-8")), True
        return None, True


def load_stats(season):
    """(label, team, opp) for one season, or None if the API has nothing usable for it."""
    rows, stale = _cache(f"stats_{season}", lambda: fetch.team_stats(season))
    if not rows:
        return None
    team, opp, label = fetch.parse_team_stats(rows)
    if len(team) < 300:
        log(f"  season {season}: only {len(team)} teams, ignored")
        return None
    return (label or str(season)) + (" (cached)" if stale else ""), team, opp


def season_ratings(season, today, sos_weight=None):
    """Schedule-adjusted ratings from one season's stats and results, or None.
    sos_weight = how hard the rating leans on strength of schedule (default config.SOS_WEIGHT)."""
    got = load_stats(season)
    if not got:
        return None
    label, team, opp = got
    rat = model.ratings(team, opp)
    played = season_games(season, today)
    model.schedule_adjust(rat, played, sos_weight)
    gp = {tid: t["GP"] for tid, t in team.items()}
    log(f"  {label}: {len(rat)} teams, median {statistics.median(gp.values()):g} GP, "
        f"schedule from {len(played)} games")
    return label, rat, gp


def current_ratings(today):
    """This season's ratings blended with last season's (see config.BLEND_GAMES).
    Returns (ratings, season label for the ledger, note for the website)."""
    s0 = config.season_for(today)
    # last season's ratings carry over with a heavier schedule adjustment (config.SOS_WEIGHT_PREV)
    prev_weight = getattr(config, "SOS_WEIGHT_PREV", None)      # None = same as this season (older config.py)
    cur, prev = season_ratings(s0, today), season_ratings(s0 - 1, today, prev_weight)
    if cur and prev:
        label, rat, gp = cur
        med = statistics.median(gp.values()) if gp else 0
        blended = model.blend(prev[1], rat, gp)
        done = sum(1 for g in gp.values() if g >= config.BLEND_GAMES)
        note = (f"{prev[0]} stats fading into {label} (median {med:g} game{'s' if med != 1 else ''} played"
                + (f", {done} teams fully on this season" if done else "") + ")")
        return blended, label, note
    if cur or prev:
        label, rat, _ = cur or prev
        return rat, label, f"{label} stats"
    raise SystemExit("No team stats available from CollegeBasketballData or cache.")


def season_games(season, today):
    """Every finished game of a season up to yesterday, as
    (away_id, home_id, away_pts, home_pts, neutral), for the strength-of-schedule adjustment.
    Kept in data/raw/season_games_<season>.json so each morning only the last few days are
    downloaded (the first run of a season pulls it all in 10-day chunks, about 16 API calls)."""
    RAW.mkdir(parents=True, exist_ok=True)
    p = RAW / f"season_games_{season}.json"
    saved = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    if saved.get("format") != 2:                       # older file without scores: rebuild once
        saved = {"format": 2, "through": "", "games": []}
    # A game without a winner was never played: the API listed some placeholder and canceled games
    # as 0-0 finals, and fetch.parse_games used to let them through. As "ties" they bent the
    # results-based strength of schedule, so they are dropped from what was saved as well.
    saved["games"] = [g for g in saved["games"] if g[3] != g[4]]
    start = date(season - 1, 11, 1)
    end = min(today - timedelta(days=1), date(season, 4, 15))

    def as_tuples(rows):
        return [(g[1], g[2], g[3], g[4], bool(g[5])) for g in rows]

    if REFRESH and saved["games"]:
        return as_tuples(saved["games"])
    if saved["through"]:
        through = date.fromisoformat(saved["through"])
        if through >= end and end < today - timedelta(days=3):      # finished season: nothing new
            return as_tuples(saved["games"])
        start = max(start, through - timedelta(days=2))
    games = {(g[0], g[1], g[2]): g for g in saved["games"]}
    d = start
    try:
        while d <= end:
            chunk_end = min(d + timedelta(days=9), end)
            for g in fetch.parse_games(fetch.games(d, chunk_end)):
                if g["away_pts"] is not None and g["away_id"] is not None and g["home_id"] is not None:
                    games[(g["date"], g["away_id"], g["home_id"])] = [
                        g["date"], g["away_id"], g["home_id"], g["away_pts"], g["home_pts"], int(g["neutral"])]
            d = chunk_end + timedelta(days=1)
        if end >= start:
            saved = {"format": 2, "through": end.isoformat(), "games": sorted(games.values())}
            p.write_text(json.dumps(saved), encoding="utf-8")
    except fetch.FetchError as e:
        log(f"  ! season games {season}: {e} (using {len(games)} saved games)")
    return as_tuples(games.values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="build for this ET date (YYYY-MM-DD) instead of today")
    ap.add_argument("--refresh", action="store_true",
                    help="afternoon refresh: re-download only today's schedule and lines")
    ap.add_argument("--scores", action="store_true",
                    help="night score update: grade the games on the board that have gone final; "
                         "no new picks, bets or lines")
    args = ap.parse_args()
    global REFRESH, SCORES, LIVE_FEEDS
    SCORES = args.scores
    REFRESH = args.refresh or SCORES
    LIVE_FEEDS = ("games_today",) if SCORES else ("games_today", "lines_today")
    now = config.now_et()
    # The site's day turns over at 3 AM Eastern (2 AM Central), not at midnight: a run started by hand
    # late at night still belongs to the evening's slate. Starting the next day is the overnight
    # build's job, and the workflow does not let that begin before 2 AM Central.
    today = date.fromisoformat(args.date) if args.date else (now - timedelta(hours=3)).date()
    if SCORES:
        # Stay on the slate that is on the site. After midnight Eastern "today" is already tomorrow,
        # and tomorrow's picks are the overnight build's job (it needs tonight's results first).
        today = slate_date(now)
        if today is None:
            log("Score update: the site's slate is not today's or last night's, nothing to do")
            return 0
    today_str = today.isoformat()
    stamp = now.astimezone(config.CT).strftime("%b %d, %Y %I:%M %p CT")
    log(f"Build for {today_str}" + (" (score update)" if SCORES else ""))

    rows = ledger.load()
    if SCORES:
        due = due_for_a_final(rows, today_str, now)
        if not due:
            log("  no game on the board can be final yet (or all are graded): nothing to do, no data call made")
            return 0
        left, held = calls_left_saved(), calls_held_back(now)
        if left is not None and left < held:
            log(f"  {len(due)} games may be final, but only {left} data calls are left this month and {held} are "
                f"held back for the regular builds: skipped (the overnight build grades them)")
            return 0
        log(f"  {len(due)} games tipped off at least {SCORES_AFTER_TIP} minutes ago and are not graded yet")
    else:
        for r in ungrade_ties(rows):                     # the regular builds always save the ledger further down
            log(f"  un-graded {r['away']} @ {r['home']} on {r['date']}: it was listed as a 0-0 final but never played")
            stale = site.DOCS / site.game_path(r)        # its page reports a result that never happened
            if stale.exists():
                stale.unlink()

    # two games calls (API max is 3,000 per call, oldest first): today's slate on its own,
    # and the last 14 days for grading (finals and halftime scores)
    raw_today, _ = _cache("games_today", lambda: fetch.games(today, today))
    fill_tbd(raw_today or [], today)                    # bracket games the feed still lists against "TBD"
    raw_hist, _ = _cache("games_recent", lambda: fetch.games(today - timedelta(days=14), today - timedelta(days=1)))
    all_games = fetch.parse_games((raw_hist or []) + (raw_today or []))
    turned = orient_like_ledger(all_games, rows)
    if turned:
        log(f"  {turned} games are listed the other way round from their pick: matched to the pick")
    log(f"  {len(raw_today or [])} games today, {len(raw_hist or [])} in the last 14 days")

    # 1) grade finished days from the last week (a score update has nothing new for earlier days)
    week_ago = (today - timedelta(days=7)).isoformat()
    for d in ([] if SCORES else ledger.ungraded_dates(rows, today_str)):
        if d >= week_ago:
            n = ledger.grade(rows, d, [g for g in all_games if g["date"] == d])
            log(f"  graded {n} games for {d}")

    # 2) stats, today's picks (the first-half pick comes from the same projection)
    rat, season, stats_note = current_ratings(today)
    log(f"  {stats_note}")
    stats_note += ", adjusted for schedule + home court"
    todays_games = [g for g in all_games if g["date"] == today_str]
    preds = [model.predict(g, rat, {}) for g in todays_games]
    skipped = [f'{p["away"]} @ {p["home"]}' for p in preds if p["pick"] is None]
    if skipped:
        log(f"  skipped (non-D1 / no stats): {len(skipped)} games")

    # 3) lock + save
    # Never add a pick (or a line) for a game that has already tipped off. A --date run by hand
    # is a re-run of a past/future day, so it skips this check.
    def not_started(g):
        return bool(args.date) or datetime.fromisoformat(g["start"]) > now
    pre_tip = {(g["away_id"], g["home_id"]) for g in todays_games if not_started(g)}
    late = [p for p in preds if (p["away_id"], p["home_id"]) not in pre_tip and p.get("pick")]
    preds = [p for p in preds if (p["away_id"], p["home_id"]) in pre_tip]
    if late and not SCORES:
        log(f"  {len(late)} games already started: not adding new picks for them")
    if not SCORES:                                      # a score update never adds a pick
        added = ledger.lock(rows, today_str, preds, season, now.isoformat(timespec="minutes"))
        log(f"  locked {added} new picks")
    # games already final today move to the Results page at the next refresh or score update
    # (whatever is left grades overnight)
    n_final = ledger.grade(rows, today_str, todays_games)
    if n_final:
        log(f"  graded {n_final} finished games from today")
    if SCORES and not n_final:
        save_calls_left(stamp)
        log("  no new finals yet: site left as it is")
        return 0
    raw_lines, _ = _cache("lines_today", lambda: fetch.lines(today, today))
    all_lines = fetch.parse_lines(raw_lines)
    line_map = {k: v for k, v in all_lines.items() if k in pre_tip}
    n_lines = ledger.attach_lines(rows, today_str, line_map)
    log(f"  betting lines found for {n_lines} games")
    ledger.save(rows)

    # 4) website (team logos/colors are cosmetic: a failed download just means plain badges)
    raw_teams, _ = _cache("teams", fetch.teams)
    teams = fetch.parse_teams(raw_teams)
    def tip(r):
        try:
            return datetime.strptime(r["when"].replace(" ET", ""), "%b %d, %Y %I:%M %p")
        except ValueError:
            return datetime.max
    todays = sorted((r for r in rows if r["date"] == today_str and r["away_pts"] == ""), key=tip)
    done_today = sum(1 for r in rows if r["date"] == today_str and r["away_pts"] != "")
    label = today.strftime("%A, %b %-d")
    # Best Bets: only games that haven't tipped yet, priced with the latest lines
    open_rows = [r for r in todays if (int(r["away_id"]), int(r["home_id"])) in pre_tip]
    day_rows = [r for r in rows if r["date"] == today_str]
    best = bets.best(open_rows, all_lines, cal_rows=day_rows)
    log(f"  best bets: {best['pool']} qualifying bets (margin scale {best['cal']['scale']:.2f}, "
        f"total shift {best['cal']['total_shift']:+.1f})")
    # the day's top single bets are locked in once most games have a line, then graded like picks
    book = bets.load_book()
    with_line = sum(1 for r in day_rows if r["line_spread"] or r["line_total"])
    if not SCORES and day_rows and with_line / len(day_rows) >= bets.LOCK_COVERAGE:      # a score update never adds a bet
        n_locked = bets.lock_day(book, today_str, best["singles"], stamp)
        if n_locked:
            log(f"  locked today's top {n_locked} single bets")
    n_bets_graded = bets.grade_book(book, rows)
    if n_bets_graded:
        log(f"  graded {n_bets_graded} single bets")
    bets.save_book(book)
    rk = writeup.ranks(rat)

    def kept_line(r):
        """The line saved with the pick (the first one seen that day), or None."""
        if not (r.get("line_spread") or r.get("line_total")):
            return None
        return {"fav": r["line_fav"], "spread": float(r["line_spread"]) if r["line_spread"] else None,
                "total": float(r["line_total"]) if r["line_total"] else None}

    def line_of(r):
        return all_lines.get((int(r["away_id"]), int(r["home_id"]))) or kept_line(r)
    writeups = {r["game_key"]: writeup.game_writeup(r, rat, rk, line_of(r), best["cal"]["scale"]) for r in todays}
    # a page of its own for every game of the last three days (today's get the result as it comes in)
    recent = [r for r in rows if (today - timedelta(days=2)).isoformat() <= r["date"] <= today_str]
    n_pages = 0
    for r in recent:
        wu = writeups.get(r["game_key"]) or writeup.game_writeup(r, rat, rk, line_of(r), best["cal"]["scale"])
        out = site.DOCS / site.game_path(r)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(site.game_page(r, teams, wu, stamp), encoding="utf-8")
        n_pages += 1
    log(f"  wrote {n_pages} game pages")
    # one-time: older game pages pointed search engines at the Today/Results tab instead of themselves
    fixed_mark = DATA / "canonical_fixed.txt"
    if not fixed_mark.exists() and hasattr(site, "fix_canonicals"):
        log(f"  repaired the search address on {site.fix_canonicals(site.DOCS)} older game pages")
        fixed_mark.write_text(today_str + "\n", encoding="utf-8")
    # once per tracking token: older game pages (never rebuilt) get the visit counter too
    token = getattr(config, "CF_ANALYTICS_TOKEN", "")
    beacon_mark = DATA / "beacon_added.txt"
    if token and hasattr(site, "add_beacon") and not (beacon_mark.exists() and beacon_mark.read_text(encoding="utf-8").strip() == token):
        log(f"  added the visit counter to {site.add_beacon(site.DOCS)} older game pages")
        beacon_mark.write_text(token + "\n", encoding="utf-8")
    yday = (today - timedelta(days=1)).isoformat()
    yesterday = (sum(1 for r in rows if r["date"] == yday and r["pick_correct"] == "1"),
                 sum(1 for r in rows if r["date"] == yday and r["pick_correct"] == "0"))
    # One game leads the day everywhere: the site's "Game of the day" is the game behind the day's top
    # bet, and the card on the Today page, the share image (the site's link preview), the daily clip,
    # its caption and the posting page all show that game. (The clip never mentions the bet: it gives
    # the projected winner and score.) gotd, the biggest matchup still to play, is only the fallback
    # for a day with nothing to bet.
    gotd = share.game_of_day(todays, writeups)
    feature = bet_of_the_day(book, today_str, best["singles"], day_rows)
    lead = feature["row"] if feature else gotd
    if lead and lead["game_key"] not in writeups:           # the top bet's game is already final: still needs its write-up
        writeups[lead["game_key"]] = writeup.game_writeup(lead, rat, rk, line_of(lead), best["cal"]["scale"])
    if feature:
        # A locked bet was made against the morning's line, the one saved with the pick. Its card explains
        # the game against that same line, so the reasons still match the bet after the line has moved.
        card_wu = writeups[lead["game_key"]]
        if feature["bet"].get("locked_at") and kept_line(lead):
            card_wu = writeup.game_writeup(lead, rat, rk, kept_line(lead), best["cal"]["scale"])
        # The card has room for five reasons: the one behind the bet itself must be one of them.
        if hasattr(writeup, "for_bet"):                     # older writeup.py: the first five, as before
            card_wu = writeup.for_bet(card_wu, feature["bet"]["kind"])
        feature["wu"] = card_wu
        log(f'  game of the day: {lead["away"]} @ {lead["home"]} ({feature["bet"]["label"]})')
    season_rec = (sum(1 for r in rows if r["pick_correct"] == "1"), sum(1 for r in rows if r["pick_correct"] == "0"))
    caption = studio = ""
    # A score update leaves the share image, the clip, its caption and the posting page exactly as the
    # day's builds made them.
    if not SCORES:
        try:
            share.share_image(site.DOCS / "og.png", label, lead, writeups.get(lead["game_key"]) if lead else None, teams,
                              site.predicted_score(lead) if lead else None, season_rec if config.SHOW_RESULTS_STATS else None)
        except Exception as e:                              # noqa: BLE001 - the share image is cosmetic
            log(f"  ! share image: {e}")

        def wu_of(r):                                       # a game that is already final has no write-up yet
            return writeups.get(r["game_key"]) or writeup.game_writeup(r, rat, rk, line_of(r), best["cal"]["scale"])
        # The clip shows the site's Game of the day. The overnight build renders it; a refresh renders
        # it again only when it has to: there is no clip for today yet, or the day's top bet came in
        # (or locked) after the clip was made and belongs to another game.
        clip_path = site.DOCS / "daily.mp4"
        made_for = clip_game(day_rows, clip_path)
        target = clip_target(lead, bool(feature), made_for)
        if target and (not REFRESH or made_for is None or made_for["game_key"] != target["game_key"]):
            try:
                clip = video.daily_video(clip_path, label, target, wu_of(target), teams, site.predicted_score(target))
                if clip:
                    clip_mark().write_text(target["game_key"] + "\n", encoding="utf-8")
                    made_for = target
                log(f"  daily clip: {'ok' if clip else 'skipped'} ({target['away']} @ {target['home']})")
            except Exception as e:                          # noqa: BLE001 - cosmetic
                log(f"  ! daily clip: {e}")
        # the caption and the posting page describe the game the clip on file really shows
        if made_for:
            caption = video.caption(made_for, wu_of(made_for), site.predicted_score(made_for))
            (DATA / "caption.txt").write_text(caption + "\n", encoding="utf-8")
        shown = made_for or lead                            # no clip yet: the game the next one will be made for
        on_site = bool(shown and lead and shown["game_key"] == lead["game_key"])
        shown_wu = (feature["wu"] if feature and on_site else wu_of(shown)) if shown else None     # reads like the site's card
        same = {"matches_site": bool(made_for) and on_site} \
            if "matches_site" in site.studio_page.__code__.co_varnames else {}       # older webpage.py: no such argument
        studio = site.studio_page(stamp, label, shown, teams, shown_wu, caption, yesterday, **same)
    # final scores for the graded bets on the Best Bets page ("83-54", away-home)
    finals = {(r["date"], str(r["away_id"]), str(r["home_id"])): f'{r["away_pts"]}-{r["home_pts"]}'
              for r in rows if r["away_pts"] != "" and r["date"] >= week_ago}
    # the one bet the model likes in each open game (same rules as Best Bets), for the Bet pills
    bets_by_game = {}
    for r in open_rows:
        ok = [b for b in bets.game_bets(r, bets._lookup(all_lines, r), best["cal"]) if bets.qualifies(b)]
        if ok:
            bets_by_game[r["game_key"]] = max(ok, key=lambda b: b["edge"])
    bets_html = (site.bets_page(best, label, stamp, teams, book, today_str, finals)
                 if "finals" in site.bets_page.__code__.co_varnames              # older webpage.py: no final scores
                 else site.bets_page(best, label, stamp, teams, book, today_str))
    extra = {"feature": feature} if "feature" in site.today_page.__code__.co_varnames else {}     # older webpage.py: no such argument
    site.write(site.today_page(todays, label, stamp, stats_note, teams, today_str, done_today, writeups, yesterday, gotd, "", bets_by_game, **extra),
               site.results_page(rows, stamp, teams), bets_html,
               stamp=stamp, studio_html=studio,
               live_html=site.live_page([r for r in rows if r["date"] == today_str], teams, stamp, today_str, label))
    (DATA / "last_build.txt").write_text(today_str + "\n", encoding="utf-8")
    save_calls_left(stamp)
    left = getattr(fetch, "CALLS_LEFT", None)
    log("done" + (f" ({left} data calls left this month)" if left is not None else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
