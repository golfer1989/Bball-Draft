"""Plain-English game write-ups built from the model's own numbers.

Each write-up is a few short lines: how the two teams rank, what drives the gap (offense,
defense, schedule, home court), how the model's margin compares to the betting line, and
where the total sits against the over/under. Nothing is invented: every sentence comes from a
number the model already produced, so a reader can see exactly why a pick is what it is."""
import config


def ranks(rat):
    """{team_id: {"rank", "off", "def", "sos", "n"}} - national ranks among rated D-I teams."""
    ids = list(rat)
    out = {t: {"n": len(ids)} for t in ids}
    for key, label in (("rating", "rank"), ("offense", "off"), ("defense", "def"), ("sos", "sos")):
        order = sorted(ids, key=lambda t: -rat[t].get(key, 0.0))
        for i, t in enumerate(order, 1):
            out[t][label] = i
    return out


def _ord(n):
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _tier(rank, n):
    if rank <= 25:
        return "a top-25 team"
    if rank <= 75:
        return "a top-75 team"
    if rank <= n // 2:
        return "an upper-half team"
    if rank <= n - 75:
        return "a lower-half team"
    return "one of the weakest teams in Division I"


def game_writeup(row, rat, rk, line=None, scale=1.0):
    """row = ledger row / prediction with away_id, home_id, pick, differential, total, neutral.
    rat = ratings, rk = ranks(rat), line = {"fav", "spread", "total"} or None.
    Returns {"headline", "lines": [...], "away_rank", "home_rank"} or None if a team is unrated."""
    a, h = rat.get(_id(row["away_id"])), rat.get(_id(row["home_id"]))
    if not a or not h:
        return None
    ra, rh = rk[_id(row["away_id"])], rk[_id(row["home_id"])]
    n = ra["n"]
    away, home, pick = row["away"], row["home"], row["pick"]
    home_pick = pick == home
    winner, loser = (home, away) if home_pick else (away, home)
    w, l = (h, a) if home_pick else (a, h)
    wr, lr = (rh, ra) if home_pick else (ra, rh)
    try:
        margin = float(row["differential"]) * config.POINTS_PER_RATING
    except (TypeError, ValueError):
        return None
    neutral = str(row.get("neutral") or "") in ("1", "True", "true")
    lines = []

    # 1. the matchup in one line
    if margin < 3:
        head = f"{pick} in a coin flip, by about {margin:.0f}"
    elif margin < 8:
        head = f"{pick} by {margin:.0f} in a close one"
    elif margin < 15:
        head = f"{pick} by {margin:.0f}"
    else:
        head = f"{pick} comfortably, by {margin:.0f}"
    lines.append(f"{winner} rates {_ord(wr['rank'])} of {n} teams, {loser} {_ord(lr['rank'])}: "
                 f"{_tier(wr['rank'], n)} against {_tier(lr['rank'], n)}.")

    # 2. what drives the gap: offense vs defense
    off_gap = (w["offense"] - l["offense"]) * config.POINTS_PER_RATING
    def_gap = (w["defense"] - l["defense"]) * config.POINTS_PER_RATING
    if abs(off_gap) >= abs(def_gap) and off_gap > 1:
        lines.append(f"The edge is mostly {winner}’s offense ({_ord(wr['off'])} nationally) against "
                     f"{loser}’s defense ({_ord(lr['def'])}).")
    elif def_gap > 1:
        lines.append(f"The edge is mostly {winner}’s defense ({_ord(wr['def'])} nationally) against "
                     f"{loser}’s offense ({_ord(lr['off'])}).")
    else:
        lines.append(f"The two are close on both ends: offense {_ord(wr['off'])} vs {_ord(lr['off'])}, "
                     f"defense {_ord(wr['def'])} vs {_ord(lr['def'])}.")

    # 3. schedule strength, when it says something
    for team, r in ((winner, wr), (loser, lr)):
        if r["sos"] <= 40:
            lines.append(f"{team} has played the {_ord(r['sos'])}-toughest schedule, so its numbers are earned.")
        elif r["sos"] >= n - 40:
            lines.append(f"{team}’s numbers came against the {_ord(n - r['sos'] + 1)}-easiest schedule, "
                         f"so they are discounted.")

    # 4. home court
    if neutral:
        lines.append("Neutral site: no home-court edge either way.")
    elif home_pick:
        lines.append(f"Home court adds {config.HOME_COURT_POINTS:g} points for {home}.")
    else:
        lines.append(f"{away} is picked on the road despite {home}’s {config.HOME_COURT_POINTS:g}-point home-court edge.")

    # 5. the betting line
    if line and line.get("spread") is not None:
        sp, fav = float(line["spread"]), line.get("fav") or ""
        if sp == 0 or not fav:
            lines.append(f"The betting line is a pick’em; the model leans {pick}.")
        else:
            fav_home = fav == home
            line_margin = sp if fav_home == home_pick else -sp     # the line's margin for the model's pick
            gap = margin * scale - line_margin                     # judged on the calibrated margin (see bets.calibrate)
            dog = away if fav_home else home
            if fav != pick:
                lines.append(f"The books favor {fav} by {sp:g}. The model disagrees and takes {pick} outright, "
                             f"which also means {pick} +{sp:g} on the spread.")
            elif gap >= 4:
                lines.append(f"The books have {fav} by {sp:g}; the model likes {fav} by more than that, "
                             f"so the spread value is on {fav} \u2212{sp:g}.")
            elif gap <= -4:
                lines.append(f"The books have {fav} by {sp:g}, more than the model\u2019s gap supports, "
                             f"so the spread value is on {dog} +{sp:g}.")
            else:
                lines.append(f"The books have {fav} by {sp:g}, right about where the model is. No spread edge.")
    # 6. the total
    try:
        total = float(row["total"])
    except (TypeError, ValueError):
        total = None
    if total is not None and line and line.get("total") is not None:
        ou = float(line["total"])
        d = total - ou
        if abs(d) >= config.OU_EDGE_POINTS:
            lines.append(f"Projected total {total:.0f} vs an over/under of {ou:g}: a {abs(d):.0f}-point gap, "
                         f"the {'Over' if d > 0 else 'Under'} is the play.")
        elif abs(d) >= 4:
            lines.append(f"Projected total {total:.0f} vs {ou:g}: leans {'Over' if d > 0 else 'Under'}.")
        else:
            lines.append(f"Projected total {total:.0f}, in line with the {ou:g} over/under.")
    elif total is not None:
        lines.append(f"Projected total: {total:.0f} points.")

    # 7. early-season caveat
    blend = min(w.get("blend", 1.0), l.get("blend", 1.0))
    if blend <= 0:
        lines.append("Early-season note: these numbers are still entirely last season\u2019s; this season\u2019s games "
                     "take over as they are played.")
    elif blend < 1:
        lines.append(f"Early-season note: about {round((1 - blend) * 100)}% of these numbers are still last season\u2019s.")
    return {"headline": head, "lines": lines, "away_rank": ra["rank"], "home_rank": rh["rank"], "n": n}


def _id(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return v
