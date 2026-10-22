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
  Strength of schedule: Offense and Defense are adjusted for the opponents each team
    actually played (schedule_adjust below), so beating up on weak teams counts for less.
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


def schedule_adjust(rat, games, weight=None):
    """Adjust each team's Offense/Defense for its opponents (KenPom-style, iterated).
    games = [(team_a_id, team_b_id), ...] already played this season.
      Offense_adj = Offense + w * (avg Defense_adj of opponents - league avg Defense)
      Defense_adj = Defense + w * (avg Offense_adj of opponents - league avg Offense)
    Facing good defenses makes raw offense look worse than it is, so it gets credit back."""
    w = config.SOS_WEIGHT if weight is None else weight
    opps = {}
    for a, b in games:
        if a in rat and b in rat:
            opps.setdefault(a, []).append(b)
            opps.setdefault(b, []).append(a)
    if not rat or not opps or not w:
        for r in rat.values():
            r["raw_rating"] = r["rating"]
        return rat
    avg_o = sum(r["offense"] for r in rat.values()) / len(rat)
    avg_d = sum(r["defense"] for r in rat.values()) / len(rat)
    off = {t: r["offense"] for t, r in rat.items()}
    de = {t: r["defense"] for t, r in rat.items()}
    for _ in range(100):
        new_off, new_de = {}, {}
        for t, r in rat.items():
            op = opps.get(t)
            if op:
                new_off[t] = r["offense"] + w * (sum(de[o] for o in op) / len(op) - avg_d)
                new_de[t] = r["defense"] + w * (sum(off[o] for o in op) / len(op) - avg_o)
            else:
                new_off[t], new_de[t] = r["offense"], r["defense"]
        off, de = new_off, new_de
    for t, r in rat.items():
        r["raw_rating"] = r["rating"]
        r["sos"] = (off[t] - r["offense"]) + (de[t] - r["defense"])
        r["offense"], r["defense"], r["rating"] = off[t], de[t], off[t] + de[t]
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
