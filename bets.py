"""Best Bets: single bets and 3/6/8-leg parlays from the model's projections vs the current lines.

The model is great at ranking teams but its margins run smaller than real margins (about half the
size of the betting spreads in mismatches), so its raw numbers can't be compared to a spread
directly: a 30-point underdog would look like a lock. Before scoring bets, each day:
  1. the model's margins are rescaled to the size of that day's spreads (one factor for the whole
     slate, fit across every game with a line), and its totals are shifted by the slate's
     average gap to the posted totals;
  2. the estimate for a game = the line, moved MODEL_WEIGHT of the way toward the rescaled model
     (betting lines are very sharp, so the model nudges rather than replaces them);
  3. chance of winning a bet = normal curve around that estimate (game-to-game spread of
     results: MARGIN_SD points for margins, TOTAL_SD for totals).
A bet qualifies with at least MIN_CHANCE, an edge of MIN_EDGE over what its odds imply, and
(for moneylines) a price no shorter than MAX_FAV_ML. Each game
contributes only its best bet, ranked by edge = model chance - implied chance.
Spread and total bets are priced at -110 (the line source has no juice for them)."""
import csv
from math import erf, prod, sqrt
from pathlib import Path

import config

MARGIN_SD = 11.0
TOTAL_SD = 16.0
MODEL_WEIGHT = 0.35
STD_ODDS = -110
MIN_CHANCE = 0.55        # model chance a bet needs
MIN_EDGE = 0.03          # ...and it must beat the price by at least 3 points of win chance
MAX_FAV_ML = -250        # moneylines shorter than this are skipped (take the spread instead)
PARLAY_SIZES = (3, 6, 8)
SINGLES = 6


def chance(x, sd):
    """Chance a normal result with mean x lands above 0."""
    return 0.5 * (1 + erf(x / (sd * sqrt(2))))


def decimal(american):
    a = float(american)
    return 1 + (a / 100 if a > 0 else 100 / -a)


def american(dec):
    return round((dec - 1) * 100) if dec >= 2 else round(-100 / (dec - 1))


def fmt_odds(a):
    return f"+{a}" if a > 0 else f"−{-a}"


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def model_home_margin(r):
    diff = _num(r.get("differential"))
    if diff is None:
        return None
    return config.POINTS_PER_RATING * diff * (1 if r["pick"] == r["home"] else -1)


def line_home_margin(ln):
    s, fav = ln.get("spread"), ln.get("fav")
    if s is None:
        return None
    if s == 0:
        return 0.0
    if fav == ln.get("_home"):
        return s
    return -s if fav == ln.get("_away") else None


def _with_home(r, ln):
    return dict(ln, _home=r["home"], _away=r["away"]) if ln else None


def calibrate(rows, line_map):
    """{"scale": multiply model margins by this, "total_shift": add to model totals}, fit on the slate."""
    mm = lm = 0.0
    gaps = []
    n = 0
    for r in rows:
        ln = _with_home(r, _lookup(line_map, r))
        if not ln:
            continue
        m, v = model_home_margin(r), line_home_margin(ln)
        if m is not None and v is not None:
            mm += m * v
            lm += m * m
            n += 1
        if _num(r.get("total")) is not None and ln.get("total") is not None:
            gaps.append(ln["total"] - float(r["total"]))
    scale = min(max(mm / lm, 1.0), 3.0) if n >= 15 and lm > 0 else 1.6     # 1.6 when the slate is too small
    shift = sum(gaps) / len(gaps) if len(gaps) >= 15 else 0.0
    return {"scale": scale, "total_shift": shift}


def _lookup(line_map, r):
    try:
        return line_map.get((int(r["away_id"]), int(r["home_id"])))
    except (TypeError, ValueError):
        return None


def game_bets(r, ln, cal=None):
    """Every bet on one game with the model's chance of winning it."""
    cal = cal or {"scale": 1.0, "total_shift": 0.0}
    m_model = model_home_margin(r)
    if m_model is None or not ln:
        return []
    ln = _with_home(r, ln)
    away, home = r["away"], r["home"]
    m_cal = m_model * cal["scale"]
    v = line_home_margin(ln)
    m_home = m_cal if v is None else v + MODEL_WEIGHT * (m_cal - v)       # estimated home margin
    total = _num(r.get("total"))
    if total is not None:
        total += cal["total_shift"]
        if ln.get("total") is not None:
            total = ln["total"] + MODEL_WEIGHT * (total - ln["total"])
    base = {"game": f"{away} @ {home}", "when": r["when"], "away": away, "home": home,
            "away_id": r["away_id"], "home_id": r["home_id"]}
    out = []

    def add(kind, side, label, odds, p, num=None):
        out.append(dict(base, kind=kind, side=side, label=label, odds=int(odds), chance=p,
                        edge=p - 1 / decimal(odds), num=num))

    for side, team, ml, m in (("home", home, ln.get("hml"), m_home), ("away", away, ln.get("aml"), -m_home)):
        if ml is not None:
            add("ML", side, f"{team} ML", ml, chance(m, MARGIN_SD))
    if v is not None:
        home_line = -v                                   # points added to the home score
        p_home = chance(m_home + home_line, MARGIN_SD)
        for side, team, hl, p in (("home", home, home_line, p_home), ("away", away, -home_line, 1 - p_home)):
            num = "PK" if hl == 0 else (f"+{hl:g}" if hl > 0 else "\u2212" + f"{-hl:g}")
            add("Spread", side, f"{team} {num}", STD_ODDS, p, hl)
    t = ln.get("total")
    if t is not None and total is not None:
        p_over = chance(total - t, TOTAL_SD)
        add("Total", "over", f"Over {t:g}", STD_ODDS, p_over, t)
        add("Total", "under", f"Under {t:g}", STD_ODDS, 1 - p_over, t)
    return out


# ---------------- the daily book: top single bets locked in and graded ----------------
BOOK = Path(__file__).resolve().parent / "data" / "bets.csv"
BOOK_FIELDS = ["date", "rank", "kind", "side", "label", "odds", "chance", "edge", "num",
               "away_id", "home_id", "away", "home", "when", "locked_at", "result"]
LOCK_COVERAGE = 0.6      # lock the day's top bets once this share of the day's games has a line


def load_book(path=BOOK):
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_book(book, path=BOOK):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=BOOK_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(book, key=lambda b: (b["date"], int(b["rank"]))))


def lock_day(book, date, singles, stamp):
    """Write the day's top single bets once (first build where they exist). Returns number added.
    Bets locked under older rules that no longer qualify are dropped as long as none of the day's
    bets has been graded yet, so a rule change re-locks the day instead of keeping stale bets."""
    today = [b for b in book if b["date"] == date]
    if today and not any(b["result"] for b in today):
        stale = [b for b in today if not qualifies(b)]
        if stale:
            book[:] = [b for b in book if b["date"] != date]
            today = []
    if today or not singles:
        return 0
    for i, b in enumerate(singles, 1):
        book.append({"date": date, "rank": str(i), "kind": b["kind"], "side": b["side"], "label": b["label"],
                     "odds": str(b["odds"]), "chance": f"{b['chance']:.3f}", "edge": f"{b['edge']:.3f}",
                     "num": "" if b["num"] is None else f"{b['num']:g}",
                     "away_id": str(b["away_id"]), "home_id": str(b["home_id"]), "away": b["away"], "home": b["home"],
                     "when": b["when"], "locked_at": stamp, "result": ""})
    return len(singles)


def grade_bet(b, away_pts, home_pts):
    """'W', 'L' or 'P' (push) for a locked bet given the final score."""
    team_margin = (home_pts - away_pts) if b["side"] == "home" else (away_pts - home_pts)
    if b["kind"] == "ML":
        v = team_margin
    elif b["kind"] == "Spread":
        v = team_margin + float(b["num"])
    else:
        v = (away_pts + home_pts - float(b["num"])) * (1 if b["side"] == "over" else -1)
    return "W" if v > 0 else "L" if v < 0 else "P"


def grade_book(book, ledger_rows):
    """Fill results from graded ledger rows (same game, same date). Returns number graded."""
    finals = {(r["date"], r["away_id"], r["home_id"]): r for r in ledger_rows if r["away_pts"] != ""}
    n = 0
    for b in book:
        if b["result"]:
            continue
        r = finals.get((b["date"], b["away_id"], b["home_id"]))
        if r:
            b["result"] = grade_bet(b, int(r["away_pts"]), int(r["home_pts"]))
            n += 1
    return n


def record(book, date=None):
    """(wins, losses, pushes) over the whole book, or one date."""
    rows = [b for b in book if b["result"] and (date is None or b["date"] == date)]
    return tuple(sum(1 for b in rows if b["result"] == k) for k in "WLP")


def qualifies(b):
    """b may be a live bet dict or a bets.csv row."""
    chance, edge, odds = float(b["chance"]), float(b["edge"]), int(b["odds"])
    return chance >= MIN_CHANCE and edge >= MIN_EDGE and (b["kind"] != "ML" or odds >= MAX_FAV_ML)


def ranked(rows, line_map, cal=None):
    """Each game's best qualifying bet, best edge first."""
    picks = []
    for r in rows:
        ok = [b for b in game_bets(r, _lookup(line_map, r), cal) if qualifies(b)]
        if ok:
            picks.append(max(ok, key=lambda b: b["edge"]))
    return sorted(picks, key=lambda b: (-b["edge"], -b["chance"]))


def parlay(legs):
    dec = prod(decimal(b["odds"]) for b in legs)
    return {"legs": legs, "chance": prod(b["chance"] for b in legs), "decimal": dec, "odds": american(dec)}


def best(rows, line_map, cal_rows=None):
    """{"singles": [...], "parlays": {3: parlay or None, 6: ..., 8: ...}, "pool": n qualifying}.
    rows = games still open for betting; cal_rows = the whole day's slate (for calibrate)."""
    cal = calibrate(cal_rows if cal_rows is not None else rows, line_map)
    pool = ranked(rows, line_map, cal)
    return {"singles": pool[:SINGLES], "pool": len(pool), "cal": cal,
            "parlays": {n: parlay(pool[:n]) if len(pool) >= n else None for n in PARLAY_SIZES}}
