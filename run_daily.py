"""Daily build: grade yesterday, pull fresh stats + today's schedule, lock picks,
rebuild the website. Run by GitHub Actions each morning (also runnable by hand:
python run_daily.py   or   python run_daily.py --date 2026-11-15)."""
import argparse
import csv
import json
import statistics
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from cbb import config, fetch, ledger, model, site

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
        if not val:
            raise fetch.FetchError("empty result")
        p.write_text(json.dumps(val, indent=0, sort_keys=True), encoding="utf-8")
        return val, False
    except Exception as e:  # noqa: BLE001 - any failure -> fall back to cache
        log(f"  ! {name}: {e}")
        if p.exists():
            log(f"  using saved copy of {name}")
            return json.loads(p.read_text(encoding="utf-8")), True
        return None, True


def _intkeys(d):
    return {int(k): v for k, v in d.items()} if d else d


def load_stats(today):
    """Current season if teams have played enough games, else last season."""
    season = config.season_for(today)
    for s in (season, season - 1):
        team, stale_t = _cache(f"team_{s}", lambda s=s: fetch.realgm_stats(s, "team"))
        opp, stale_o = _cache(f"opp_{s}", lambda s=s: fetch.realgm_stats(s, "opp"))
        team, opp = _intkeys(team), _intkeys(opp)
        if not team or not opp or len(team) < 300:
            log(f"  season {s}: no usable stats")
            continue
        med_gp = statistics.median(t["GP"] or 0 for t in team.values())
        if s == season and med_gp < config.MIN_MEDIAN_GP:
            log(f"  season {s}: median GP {med_gp} < {config.MIN_MEDIAN_GP}, using last season")
            continue
        label = f"{s - 1}-{str(s)[2:]} stats, median {med_gp:g} GP" + (" (cached)" if stale_t or stale_o else "")
        return s, team, opp, label
    raise SystemExit("No team stats available from RealGM or cache.")


def load_name_map():
    with open(DATA / "teamrankings_names.csv", newline="", encoding="utf-8") as f:
        return {r["teamrankings_name"]: int(r["realgm_id"]) for r in csv.DictReader(f)}


def first_half(today_str):
    vals, _ = _cache("first_half", lambda: fetch.tr_first_half(today_str))
    if not vals:
        return {}
    names = load_name_map()
    unknown = sorted(n for n in vals if n not in names)
    if unknown:
        log(f"  ! TeamRankings names not in data/teamrankings_names.csv: {unknown}")
    return {names[n]: v for n, v in vals.items() if n in names and v is not None}


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

    # 1) grade any finished days from the last week
    for d in ledger.ungraded_dates(rows, today_str):
        if d < (today - timedelta(days=7)).isoformat():
            continue
        try:
            n = ledger.grade(rows, d, fetch.realgm_schedule(d))
            log(f"  graded {n} games for {d}")
        except fetch.FetchError as e:
            log(f"  ! could not grade {d}: {e}")

    # 2) stats + 1H + today's schedule
    season, team, opp, stats_note = load_stats(today)
    log(f"  {stats_note}")
    rat = model.ratings(team, opp)
    fh = first_half(today_str)
    try:
        games = fetch.realgm_schedule(today_str)
    except fetch.FetchError as e:
        log(f"  ! schedule: {e}")
        games = []
    preds = [model.predict(g, rat, fh) for g in games]
    skipped = [f'{p["away"]} @ {p["home"]}' for p in preds if p["pick"] is None]
    if skipped:
        log(f"  skipped (non-D1 / unrated team): {skipped}")

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
