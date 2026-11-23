"""The rating model from the spreadsheet's Combined Stats / WINNERS sheets,
with the formula mistakes fixed:

  1. Turnover %  = TOV / (FGA + 0.44*FTA + TOV)
     (sheet computed TOV / (FGA + FTA + APG/100) because of a misplaced parenthesis)
  2. Offense rebounding weight 0.2 (sheet had 2, ten times defense's 0.2)
  3. Team ppg = (points scored + points allowed) / 2
     (sheet's average got folded into the VLOOKUP's match argument, so it used points scored only)
  4. Teams are matched exactly by RealGM team id
     (sheet's lookup ranges stopped at row 362 of 366)

Everything else is the spreadsheet's logic, a four-factor rating:
  Offense = shooting + ball security + offensive rebounding + free throws
  Defense = the same four things, as the opponents managed them against this team
  Rating  = Offense + Defense

Nov 2026 audit: the four factors are now measured the way they are defined, and weighted by a
fit to results instead of the 40/25/20/15 rule of thumb:
  Shooting    = effective field goal % (a made three counts as 1.5 makes); was plain FG%
  Free throws = free throws made per field goal attempt (how often a team gets to the line and
                converts, and how often a defense sends opponents there); was FT%, which on
                defense rewarded a team for its opponents missing free throws (luck, not skill)
  Weights     = 42 / 37 / 14 / 7 (config.W_SHOOT, W_TOV, W_REB, W_FT), fitted on the 5,752 games
                between Division I teams in 2025-26
  Offense = .42*eFG% + .37*(1-TOV%) + .14*ORB% + .07*FTR
  Defense = .42*(1-opp eFG%) + .37*opp TOV% + .14*(1-opp ORB%) + .07*(1-opp FTR)
Replayed on every game of Nov 2-22, 2026 with only that morning's data: 728-202 (78.3%) against
715-215 for the old inputs, and the average miss on the margin fell from 10.53 to 10.37 points.

Added on top of the spreadsheet (Oct 2026):
  Strength of schedule: the rating is credited (or docked) for how strong the opponents
    each team actually played were, measured from game results (schedule_adjust below).
    Last season's ratings, which carry over into the early season, lean on it twice as hard
    (config.SOS_WEIGHT_PREV).
  Home court: the home team gets HOME_COURT_POINTS (none at neutral sites).
  Pick = whoever the projected margin favors.
  Total = away ppg + home ppg
  1H pick = the full-game pick, projected halftime lead = FIRST_HALF_SHARE x the margin
    (Nov 2026: replaced "higher first-half scoring over the last 3 games", which was right
    64% of the time against 73% for the full-game pick on the same games)
"""
import numpy as np

import config


def tov_pct(s):
    return s["TOV"] / (s["FGA"] + 0.44 * s["FTA"] + s["TOV"])


def team_rating(team, opp):
    """team = the team's own per-game stats, opp = what its opponents averaged against it."""
    orb = team["ORB"] / (team["ORB"] + opp["DRB"])          # Rebound %
    opp_orb = opp["ORB"] / (opp["ORB"] + team["DRB"])       # Opp Rebound %
    tov, opp_tov = tov_pct(team), tov_pct(opp)
    offense = (config.W_SHOOT * team["eFG%"] + config.W_TOV * (1 - tov)
               + config.W_REB * orb + config.W_FT * team["FTR"])
    defense = (config.W_SHOOT * (1 - opp["eFG%"]) + config.W_TOV * opp_tov
               + config.W_REB * (1 - opp_orb) + config.W_FT * (1 - opp["FTR"]))
    return {
        "reb_pct": orb, "tov_pct": tov, "opp_reb_pct": opp_orb, "opp_tov_pct": opp_tov,
        "efg": team["eFG%"], "opp_efg": opp["eFG%"], "ftr": team["FTR"], "opp_ftr": opp["FTR"],
        "ppg": (team["PPG"] + opp["PPG"]) / 2,
        "offense": offense, "defense": defense, "rating": offense + defense,
    }


def ratings(team_stats, opp_stats):
    out = {}
    for tid, t in team_stats.items():
        o = opp_stats.get(tid)
        if not o:
            continue
        try:
            r = team_rating(t, o)
        except (TypeError, ZeroDivisionError):
            continue
        r["name"] = t["name"]
        out[tid] = r
    return out


def results_ratings(games, cap=25, ridge=1.0, iters=400):
    """Results-based team strength in points (Massey-style, like the ratings sites use):
    home margin = r_home - r_away + home court (none at neutral sites).
    games = [(away_id, home_id, away_pts, home_pts, neutral), ...]; blowouts capped at `cap`
    points so running up the score doesn't count; a small `ridge` keeps teams with few games
    near average. Returns {team_id: rating}, centered on 0.

    Each round re-estimates home court from the current ratings, then every team's rating from its
    games (its capped margins plus its opponents' ratings), then re-centers. The rounds run on
    arrays: the same arithmetic as the game-by-game loop this replaced, about 50 times faster
    (a season of 6,300 games took 2.3 seconds of every build; it now takes 0.04)."""
    index = {}
    for a, h, *_ in games:
        index.setdefault(a, len(index))
        index.setdefault(h, len(index))
    if not index:
        return {}
    n = len(index)
    away = np.fromiter((index[g[0]] for g in games), dtype=np.int64, count=len(games))
    home = np.fromiter((index[g[1]] for g in games), dtype=np.int64, count=len(games))
    margin = np.clip(np.fromiter((g[3] - g[2] for g in games), dtype=float, count=len(games)), -cap, cap)
    at_home = np.fromiter((not g[4] for g in games), dtype=bool, count=len(games))
    played = np.bincount(home, minlength=n) + np.bincount(away, minlength=n) + ridge
    n_home = int(at_home.sum())
    r = np.zeros(n)
    for _ in range(iters):
        hca = float((margin[at_home] - (r[home[at_home]] - r[away[at_home]])).sum() / n_home) if n_home else 0.0
        m = margin - hca * at_home
        total = (np.bincount(home, weights=m + r[away], minlength=n)
                 + np.bincount(away, weights=r[home] - m, minlength=n))
        r = total / played
        r = r - r.mean()
    return {t: float(r[i]) for t, i in index.items()}


def schedule_adjust(rat, games, weight=None):
    """Strength of schedule for your four-factor rating.
    A team's four-factor numbers are earned against its opponents, so a team that played
    strong opponents is better than its raw numbers say. Opponent strength comes from game
    results (results_ratings), which non-conference games tie together across leagues:
      SOS    = average results-rating of the D-I opponents played (points) / POINTS_PER_RATING
      Rating = Offense + Defense + weight x SOS
    games = [(away_id, home_id, away_pts, home_pts, neutral), ...] played this season."""
    w = config.SOS_WEIGHT if weight is None else weight
    for r in rat.values():
        r["raw_rating"] = r["rating"]
        r["sos"] = 0.0
    if not games or not w:
        return rat
    strength = results_ratings(games)
    d1 = [v for t, v in strength.items() if t in rat]
    center = sum(d1) / len(d1) if d1 else 0.0          # average D-I opponent = 0
    opps = {}
    for a, h, *_ in games:
        if a in rat and h in rat:
            opps.setdefault(a, []).append(strength[h] - center)
            opps.setdefault(h, []).append(strength[a] - center)
    for t, r in rat.items():
        if opps.get(t):
            r["sos"] = sum(opps[t]) / len(opps[t]) / config.POINTS_PER_RATING
            r["rating"] = r["raw_rating"] + w * r["sos"]
    return rat


def new_team_prior(prev, pct=None):
    """Stand-in "last season" for a team that has none because it is new to Division I: the
    numbers of the team sitting at the NEW_TEAM_PERCENTILE of last season's ratings (new programs
    start near the bottom), with a middle-of-the-pack scoring level. None if prev is empty."""
    pct = getattr(config, "NEW_TEAM_PERCENTILE", 10) if pct is None else pct
    rated = sorted((r for r in prev.values() if "rating" in r), key=lambda r: r["rating"])
    if not rated:
        return None
    base = rated[min(len(rated) - 1, int(pct / 100 * len(rated)))]
    prior = {k: base[k] for k in ("rating", "raw_rating", "sos", "offense", "defense") if k in base}
    ppg = sorted(r["ppg"] for r in prev.values() if "ppg" in r)
    if ppg:
        prior["ppg"] = ppg[len(ppg) // 2]
    return prior


def blend(prev, cur, games_played, n_full=None):
    """Early-season ratings: last season's rating (prev) fades into this season's (cur) as a
    team plays games. weight on this season = min(1, GP / BLEND_GAMES). A team that hasn't
    played yet keeps last season's numbers. A team with no last season (new to Division I)
    fades in from new_team_prior() instead, so a handful of games, some of them against
    non-Division I opponents, can't make it look like a top team (West Florida, Nov 2026: picked
    by 47, 23 and 22 points in its first three D-I games and lost all three).
    Returns a new {team_id: rating dict}."""
    n_full = config.BLEND_GAMES if n_full is None else n_full
    stand_in = new_team_prior(prev)
    out = {}
    for tid in set(prev) | set(cur):
        a, b = prev.get(tid), cur.get(tid)
        if not b:
            r = dict(a)
            r["blend"] = 0.0
            out[tid] = r
            continue
        new = not a
        if new and stand_in is None:
            r = dict(b)
            r["blend"] = 1.0
            out[tid] = r
            continue
        a = stand_in if new else a
        w = max(0.0, min(1.0, games_played.get(tid, 0) / n_full)) if n_full else 1.0
        r = dict(b)
        for k in ("rating", "raw_rating", "sos", "offense", "defense", "ppg"):
            if k in a and k in b:
                r[k] = (1 - w) * a[k] + w * b[k]
        r["blend"] = w
        if new:
            r["new_team"] = True
        out[tid] = r
    return out


def predict(game, rat, first_half=None):
    """game has away_id/home_id/away/home. first_half is no longer used (the 1H pick now
    follows the full-game projection); the argument stays so older callers keep working."""
    a, h = rat.get(game["away_id"]), rat.get(game["home_id"])
    row = dict(game)
    if not a or not h:
        row.update(away_rating=None, home_rating=None, pick=None, differential=None,
                   strong_pick="", total=None, fh_pick=None, fh_margin=None)
        return row
    home_edge = 0.0 if game.get("neutral") else config.HOME_COURT_POINTS
    margin = config.POINTS_PER_RATING * (h["rating"] - a["rating"]) + home_edge   # + = home wins
    pick = game["home"] if margin > 0 else game["away"]
    # differential stays in rating units (like the sheet) but now includes home court:
    # |margin| / points-per-rating
    diff = abs(margin) / config.POINTS_PER_RATING
    row.update(
        away_rating=a["rating"], home_rating=h["rating"], pick=pick,
        differential=diff, margin=margin,
        strong_pick=pick if diff > config.STRONG_PICK_GAP else "",
        total=a["ppg"] + h["ppg"],
        # first half: same side as the game pick, leading by its usual share of the final margin
        fh_pick=pick, fh_margin=max(getattr(config, "FIRST_HALF_SHARE", 0.55) * abs(margin), 0.5),
    )
    return row
