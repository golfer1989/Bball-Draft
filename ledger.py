"""data/ledger.csv: every pick is written once (locked) in the morning and graded
the next day from RealGM final scores. Re-running a day never changes a locked pick."""
import csv
from pathlib import Path

LEDGER = Path(__file__).resolve().parent / "data" / "ledger.csv"
FIELDS = ["game_key", "date", "when", "away_id", "away", "home_id", "home",
          "away_rating", "home_rating", "pick", "differential", "strong_pick", "total",
          "fh_pick", "fh_margin", "stats_season", "locked_at",
          "away_pts", "home_pts", "pick_correct", "strong_correct", "total_error", "fh_correct", "neutral"]


def key(date, away_id, home_id):
    return f"{date}|{away_id}|{home_id}"


def load(path=LEDGER):
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save(rows, path=LEDGER):
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(rows, key=lambda r: (r["date"], r["game_key"]))
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _fmt(v, nd=4):
    if v is None or v == "":
        return ""
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def lock(rows, date, preds, season, stamp):
    """Add today's predictions that are not already in the ledger. Returns number added."""
    have = {r["game_key"] for r in rows}
    added = 0
    for p in preds:
        if p.get("pick") is None:
            continue
        k = key(date, p["away_id"], p["home_id"])
        if k in have:
            continue
        rows.append({
            "game_key": k, "date": date, "when": p["when"],
            "away_id": p["away_id"], "away": p["away"], "home_id": p["home_id"], "home": p["home"],
            "away_rating": _fmt(p["away_rating"]), "home_rating": _fmt(p["home_rating"]),
            "pick": p["pick"], "differential": _fmt(p["differential"]),
            "strong_pick": p["strong_pick"], "total": _fmt(p["total"], 1),
            "fh_pick": p.get("fh_pick") or "", "fh_margin": _fmt(p.get("fh_margin"), 1),
            "stats_season": season, "locked_at": stamp,
            "away_pts": "", "home_pts": "", "pick_correct": "", "strong_correct": "", "total_error": "",
            "fh_correct": "", "neutral": "1" if p.get("neutral") else "",
        })
        have.add(k)
        added += 1
    return added


def ungraded_dates(rows, before):
    return sorted({r["date"] for r in rows if r["away_pts"] == "" and r["date"] < before})


def grade(rows, date, results):
    """results = parsed games for that date. Returns number graded."""
    by = {key(date, g["away_id"], g["home_id"]): g for g in results if g["away_pts"] is not None}
    n = 0
    for r in rows:
        if r["date"] != date or r["away_pts"] != "":
            continue
        g = by.get(r["game_key"])
        if not g:
            continue
        ap, hp = g["away_pts"], g["home_pts"]
        winner = r["home"] if hp > ap else r["away"]
        r["away_pts"], r["home_pts"] = str(ap), str(hp)
        r["pick_correct"] = "1" if r["pick"] == winner else "0"
        r["strong_correct"] = ("1" if r["strong_pick"] == winner else "0") if r["strong_pick"] else ""
        r["total_error"] = f"{ap + hp - float(r['total']):.1f}" if r["total"] else ""
        ah, hh = g.get("away_h1"), g.get("home_h1")
        if r["fh_pick"] and ah is not None and hh is not None and ah != hh:   # halftime tie = no result
            r["fh_correct"] = "1" if r["fh_pick"] == (r["home"] if hh > ah else r["away"]) else "0"
        n += 1
    return n
