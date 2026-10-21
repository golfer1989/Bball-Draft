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
  Pick = higher rating (no home-court adjustment, same as the sheet)
  Total = away ppg + home ppg
  1H pick = higher TeamRankings 1st-half PPG (Last 3), margin = the gap
"""
from . import config


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


def predict(game, rat, first_half):
    """game has away_id/home_id/away/home. first_half = {realgm_id: 1H ppg}."""
    a, h = rat.get(game["away_id"]), rat.get(game["home_id"])
    row = dict(game)
    if not a or not h:
        row.update(away_rating=None, home_rating=None, pick=None, differential=None,
                   strong_pick="", total=None)
    else:
        diff = h["rating"] - a["rating"]
        pick = game["home"] if diff > 0 else game["away"]
        row.update(
            away_rating=a["rating"], home_rating=h["rating"], pick=pick,
            differential=abs(diff),
            strong_pick=pick if abs(diff) > config.STRONG_PICK_GAP else "",
            total=a["ppg"] + h["ppg"],
        )
    fa, fh = first_half.get(game["away_id"]), first_half.get(game["home_id"])
    if fa is None or fh is None:
        row.update(fh_pick=None, fh_margin=None)
    else:
        row.update(fh_pick=game["away"] if fa > fh else game["home"], fh_margin=abs(fa - fh))
    return row
