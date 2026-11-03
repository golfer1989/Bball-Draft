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
A bet qualifies with at least MIN_CHANCE and a chance above what its odds imply. Each game
contributes only its best bet, ranked by edge = model chance - implied chance.
Spread and total bets are priced at -110 (the line source has no juice for them)."""
from math import erf, prod, sqrt

import config

MARGIN_SD = 11.0
TOTAL_SD = 16.0
MODEL_WEIGHT = 0.35
STD_ODDS = -110
MIN_CHANCE = 0.60
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

    def add(kind, side, label, odds, p):
        out.append(dict(base, kind=kind, side=side, label=label, odds=int(odds), chance=p,
                        edge=p - 1 / decimal(odds)))

    for side, team, ml, m in (("home", home, ln.get("hml"), m_home), ("away", away, ln.get("aml"), -m_home)):
        if ml is not None:
            add("ML", side, f"{team} ML", ml, chance(m, MARGIN_SD))
    if v is not None:
        home_line = -v                                   # points added to the home score
        p_home = chance(m_home + home_line, MARGIN_SD)
        for side, team, hl, p in (("home", home, home_line, p_home), ("away", away, -home_line, 1 - p_home)):
            num = "PK" if hl == 0 else (f"+{hl:g}" if hl > 0 else "\u2212" + f"{-hl:g}")
            add("Spread", side, f"{team} {num}", STD_ODDS, p)
    t = ln.get("total")
    if t is not None and total is not None:
        p_over = chance(total - t, TOTAL_SD)
        add("Total", "over", f"Over {t:g}", STD_ODDS, p_over)
        add("Total", "under", f"Under {t:g}", STD_ODDS, 1 - p_over)
    return out


def ranked(rows, line_map, cal=None):
    """Each game's best qualifying bet, best edge first."""
    picks = []
    for r in rows:
        ok = [b for b in game_bets(r, _lookup(line_map, r), cal) if b["chance"] >= MIN_CHANCE and b["edge"] > 0]
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
