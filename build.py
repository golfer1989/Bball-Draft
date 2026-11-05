"""Daily build: grade recent games, pull fresh stats + today's schedule, lock picks,
rebuild the website. Run by GitHub Actions each morning.
By hand:  set CBBD_API_KEY=...  then  python build.py  [--date 2026-11-15]"""
import argparse
import json
import statistics
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import bets, config, fetch, ledger, model, share, webpage as site, writeup

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
RAW = DATA / "raw"


def log(*a):
    print(*a, flush=True)


REFRESH = False          # set by --refresh: only today's schedule + lines are downloaded
LIVE_FEEDS = ("games_today", "lines_today")


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


def season_ratings(season, today):
    """Schedule-adjusted ratings from one season's stats and results, or None."""
    got = load_stats(season)
    if not got:
        return None
    label, team, opp = got
    rat = model.ratings(team, opp)
    played = season_games(season, today)
    model.schedule_adjust(rat, played)
    gp = {tid: t["GP"] for tid, t in team.items()}
    log(f"  {label}: {len(rat)} teams, median {statistics.median(gp.values()):g} GP, "
        f"schedule from {len(played)} games")
    return label, rat, gp


def current_ratings(today):
    """This season's ratings blended with last season's (see config.BLEND_GAMES).
    Returns (ratings, season label for the ledger, note for the website)."""
    s0 = config.season_for(today)
    cur, prev = season_ratings(s0, today), season_ratings(s0 - 1, today)
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
    args = ap.parse_args()
    global REFRESH
    REFRESH = args.refresh
    now = config.now_et()
    today = date.fromisoformat(args.date) if args.date else now.date()
    today_str = today.isoformat()
    stamp = now.astimezone(config.CT).strftime("%b %d, %Y %I:%M %p CT")
    log(f"Build for {today_str}")

    rows = ledger.load()

    # two games calls (API max is 3,000 per call, oldest first): today's slate on its own,
    # and the last 14 days for grading + 1H "last 3" history
    raw_today, _ = _cache("games_today", lambda: fetch.games(today, today))
    raw_hist, _ = _cache("games_recent", lambda: fetch.games(today - timedelta(days=14), today - timedelta(days=1)))
    all_games = fetch.parse_games((raw_hist or []) + (raw_today or []))
    log(f"  {len(raw_today or [])} games today, {len(raw_hist or [])} in the last 14 days")

    # 1) grade finished days from the last week
    week_ago = (today - timedelta(days=7)).isoformat()
    for d in ledger.ungraded_dates(rows, today_str):
        if d >= week_ago:
            n = ledger.grade(rows, d, [g for g in all_games if g["date"] == d])
            log(f"  graded {n} games for {d}")

    # 2) stats, 1H, today's picks
    rat, season, stats_note = current_ratings(today)
    log(f"  {stats_note}")
    stats_note += ", adjusted for schedule + home court"
    fh = fetch.first_half_last3(all_games, today_str)
    todays_games = [g for g in all_games if g["date"] == today_str]
    preds = [model.predict(g, rat, fh) for g in todays_games]
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
    if late:
        log(f"  {len(late)} games already started: not adding new picks for them")
    added = ledger.lock(rows, today_str, preds, season, now.isoformat(timespec="minutes"))
    log(f"  locked {added} new picks")
    # games already final today move to the Results page at the next refresh (the rest grade overnight)
    n_final = ledger.grade(rows, today_str, todays_games)
    if n_final:
        log(f"  graded {n_final} finished games from today")
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
    if day_rows and with_line / len(day_rows) >= bets.LOCK_COVERAGE:
        n_locked = bets.lock_day(book, today_str, best["singles"], stamp)
        if n_locked:
            log(f"  locked today's top {n_locked} single bets")
    n_bets_graded = bets.grade_book(book, rows)
    if n_bets_graded:
        log(f"  graded {n_bets_graded} single bets")
    bets.save_book(book)
    rk = writeup.ranks(rat)
    writeups = {r["game_key"]: writeup.game_writeup(r, rat, rk, all_lines.get((int(r["away_id"]), int(r["home_id"]))),
                                                    best["cal"]["scale"])
                for r in todays}
    yday = (today - timedelta(days=1)).isoformat()
    yesterday = (sum(1 for r in rows if r["date"] == yday and r["pick_correct"] == "1"),
                 sum(1 for r in rows if r["date"] == yday and r["pick_correct"] == "0"))
    gotd = share.game_of_day(todays, writeups)
    season_rec = (sum(1 for r in rows if r["pick_correct"] == "1"), sum(1 for r in rows if r["pick_correct"] == "0"))
    try:
        share.share_image(site.DOCS / "og.png", label, gotd, writeups.get(gotd["game_key"]) if gotd else None, teams,
                          site.predicted_score(gotd) if gotd else None, season_rec if config.SHOW_RESULTS_STATS else None)
    except Exception as e:                              # noqa: BLE001 - the share image is cosmetic
        log(f"  ! share image: {e}")
    site.write(site.today_page(todays, label, stamp, stats_note, teams, today_str, done_today, writeups, yesterday, gotd),
               site.results_page(rows, stamp, teams), site.bets_page(best, label, stamp, teams, book, today_str),
               stamp=stamp)
    (DATA / "last_build.txt").write_text(today_str + "\n", encoding="utf-8")
    log("done")


if __name__ == "__main__":
    sys.exit(main())
