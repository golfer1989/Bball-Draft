"""Settings for the CBB model. Edit the numbers here; nothing else needs touching."""
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")   # RealGM lists tip times in Eastern
CT = ZoneInfo("America/Chicago")    # site timestamps

# --- data sources (same pages the spreadsheet's Power Query pulled) ---
REALGM_TEAM = "https://basketball.realgm.com/ncaa/team-stats/{season}/Averages/Team_Totals/0?pace_adjustment="
REALGM_OPP = "https://basketball.realgm.com/ncaa/team-stats/{season}/Averages/Opponent_Totals/0?pace_adjustment="
REALGM_SCHEDULE = "https://basketball.realgm.com/ncaa/schedules/{date}"          # date = YYYY-MM-DD
TR_FIRST_HALF = "https://www.teamrankings.com/ncaa-basketball/stat/1st-half-points-per-game?date={date}"

# --- model knobs ---
# Four-factor weights (Dean Oliver). Same as the spreadsheet, with the offense
# rebounding weight fixed from 2 to 0.2 so it matches defense.
W_SHOOT, W_TOV, W_REB, W_FT = 0.40, 0.25, 0.20, 0.15

# "Strong Pick" when the projected edge (rating gap incl. home court, in rating units) is
# bigger than this. 0.06 ~= a 10-point projected margin and flags ~12% of games
# (2026 backtest with schedule + home court: 85% straight-up on those picks).
STRONG_PICK_GAP = 0.06

# First-half pick uses TeamRankings' "Last 3" column, like the spreadsheet did.
FIRST_HALF_COLUMN = "Last 3"

# Use the new season's stats once the median team has played this many games;
# before that, fall back to last season's final numbers.
MIN_MEDIAN_GP = 3


def season_for(d):
    """RealGM labels a season by the year it ends: Nov 2026 - Apr 2027 -> 2027."""
    return d.year + 1 if d.month >= 7 else d.year


def now_et():
    return datetime.now(ET)

# Predicted margin (points) = POINTS_PER_RATING x rating gap + HOME_COURT_POINTS for the
# home team (none at neutral sites). Both fit on 2,415 games played after Jan 21, 2026.
# Each team's predicted score = total/2 +/- margin/2.
POINTS_PER_RATING = 170
HOME_COURT_POINTS = 2.7

# Strength of schedule: rating += SOS_WEIGHT x (average results-based strength of the
# opponents played, in points / POINTS_PER_RATING). 1.0 = full adjustment, 0 = off.
SOS_WEIGHT = 1.0
