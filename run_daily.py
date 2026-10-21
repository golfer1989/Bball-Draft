"""Daily build: grade recent games, pull fresh stats + today's schedule, lock picks,
rebuild the website. Run by GitHub Actions each morning.
By hand:  set CBBD_API_KEY=...  then  python run_daily.py  [--date 2026-11-15]"""
import argparse
import json
import statistics
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import config, fetch, ledger, model, webpage as site

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
RAW = DATA / "raw"


def log(*a):
    print(*a, flush=True)


def _cache(name, loader):
    """Fetch with loader(); save to data/raw/<name>.json; on failure reuse the saved copy."""
    RAW.mkdir(parents=True, exist_ok=True)
    p = RAW / f"{name}.json"
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


def load_stats(today):
    """Newest season whose median team has played enough games (pre-season -> last season).
    Tries three season numbers so it works whichever year the API uses to label a season."""
    s0 = config.season_for(today)
    for s in (s0, s0 - 1, s0 - 2):
        rows, stale = _cache(f"stats_{s}", lambda s=s: fetch.team_stats(s))
        if not rows:
            log(f"  season {s}: no stats")
            continue
        team, opp, label = fetch.parse_team_stats(rows)
        if len(team) < 300:
            log(f"  season {s}: only {len(team)} teams")
            continue
        med = statistics.median(t["GP"] for t in team.values())
        if med < config.MIN_MEDIAN_GP:
            log(f"  season {s} ({label}): median {med:g} GP < {config.MIN_MEDIAN_GP}, trying older")
            continue
        note = f"{label or s} stats, median {med:g} GP" + (" (cached)" if stale else "")
        return label or str(s), team, opp, note
    raise SystemExit("No team stats available from CollegeBasketballData or cache.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="build for this ET date (YYYY-MM-DD) instead of today")
    args = ap.parse_args()
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
    season, team, opp, stats_note = load_stats(today)
    log(f"  {stats_note}")
    rat = model.ratings(team, opp)
    fh = fetch.first_half_last3(all_games, today_str)
    todays_games = [g for g in all_games if g["date"] == today_str]
    preds = [model.predict(g, rat, fh) for g in todays_games]
    skipped = [f'{p["away"]} @ {p["home"]}' for p in preds if p["pick"] is None]
    if skipped:
        log(f"  skipped (non-D1 / no stats): {len(skipped)} games")

    # 3) lock + save
    added = ledger.lock(rows, today_str, preds, season, now.isoformat(timespec="minutes"))
    log(f"  locked {added} new picks")
    ledger.save(rows)

    # 4) website
    def tip(r):
        try:
            return datetime.strptime(r["when"].replace(" ET", ""), "%b %d, %Y %I:%M %p")
        except ValueError:
            return datetime.max
    todays = sorted((r for r in rows if r["date"] == today_str), key=tip)
    label = today.strftime("%A, %b %d, %Y")
    site.write(site.today_page(todays, label, stamp, stats_note), site.results_page(rows, stamp))
    (DATA / "last_build.txt").write_text(today_str + "\n", encoding="utf-8")
    log("done")


if __name__ == "__main__":
    sys.exit(main())
