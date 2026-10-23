"""The rating model from the spreadsheet's Combined Stats / WINNERS sheets,
with the formula mistakes fixed:

  1. Turnover %  = TOV / (FGA + 0.44*FTA + TOV)
     (sheet computed TOV / (FGA + FTA + APG/100) because of a misplaced parenthesis)
  2. Offense rebounding weight 0.2 (sheet had 2, ten times defense's 0.2)
  3. Team ppg = (points scored + points allowed) / 2
     (sheet's average got folded into the VLOOKUP's match argument, so it used points scored only)
  4. Teams are matched exactly by RealGM team id
     (sheet's lookup ranges stopped at row 362 of 366)

Everything else is the spreadsheet's logic:
  Offense = .4*FG% + .25*(1-TOV%) + .2*ORB% + .15*FT%
  Defense = .4*(1-oppFG%) + .25*oppTOV% + .2*(1-oppORB%) + .15*(1-oppFT%)
  Rating  = Offense + Defense

Added on top of the spreadsheet (Oct 2026):
  Strength of schedule: the rating is credited (or docked) for how strong the opponents
    each team actually played were, measured from game results (schedule_adjust below).
  Home court: the home team gets HOME_COURT_POINTS (none at neutral sites).
  Pick = whoever the projected margin favors.
  Total = away ppg + home ppg
  1H pick = higher TeamRankings 1st-half PPG (Last 3), margin = the gap
"""
import config


def tov_pct(s):
    return s["TOV"] / (s["FGA"] + 0.44 * s["FTA"] + s["TOV"])


def team_rating(team, opp):
    """team = the team's own per-game stats, opp = what its opponents averaged against it."""
    orb = team["ORB"] / (team["ORB"] + opp["DRB"])          # Rebound %
    opp_orb = opp["ORB"] / (opp["ORB"] + team["DRB"])       # Opp Rebound %
    tov, opp_tov = tov_pct(team), tov_pct(opp)
    offense = (config.W_SHOOT * team["FG%"] + config.W_TOV * (1 - tov)
               + config.W_REB * orb + config.W_FT * team["FT%"])
    defense = (config.W_SHOOT * (1 - opp["FG%"]) + config.W_TOV * opp_tov
               + config.W_REB * (1 - opp_orb) + config.W_FT * (1 - opp["FT%"]))
    return {
        "reb_pct": orb, "tov_pct": tov, "opp_reb_pct": opp_orb, "opp_tov_pct": opp_tov,
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
    near average. Returns {team_id: rating}, centered on 0."""
    r = {}
    for a, h, *_ in games:
        r[a] = r.get(a, 0.0)
        r[h] = r.get(h, 0.0)
    if not r:
        return {}
    clip = lambda m: max(-cap, min(cap, m))  # noqa: E731
    hca = 3.0
    for _ in range(iters):
        num = {t: 0.0 for t in r}
        den = {t: ridge for t in r}
        hs = hn = 0
        for a, h, ap, hp, neutral in games:
            if not neutral:
                hs += clip(hp - ap) - (r[h] - r[a])
                hn += 1
        hca = hs / hn if hn else 0.0
        for a, h, ap, hp, neutral in games:
            m = clip(hp - ap) - (0.0 if neutral else hca)
            num[h] += m + r[a]
            den[h] += 1
            num[a] += -m + r[h]
            den[a] += 1
        r = {t: num[t] / den[t] for t in r}
        mean = sum(r.values()) / len(r)
        r = {t: v - mean for t, v in r.items()}
    return r


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


def predict(game, rat, first_half):
    """game has away_id/home_id/away/home. first_half = {realgm_id: 1H ppg}."""
    a, h = rat.get(game["away_id"]), rat.get(game["home_id"])
    row = dict(game)
    if not a or not h:
        row.update(away_rating=None, home_rating=None, pick=None, differential=None,
                   strong_pick="", total=None)
    else:
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
        )
    fa, fh = first_half.get(game["away_id"]), first_half.get(game["home_id"])
    if fa is None or fh is None:
        row.update(fh_pick=None, fh_margin=None)
    else:
        row.update(fh_pick=game["away"] if fa > fh else game["home"], fh_margin=abs(fa - fh))
    return row
