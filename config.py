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

# "Strong Pick" when the rating gap is bigger than this. The spreadsheet used
# 0.2 on its (buggy) scale; 0.055 flags the same ~12% of games on the corrected
# scale (2026 backtest: 84.5% straight-up vs 70.6% for the old flag).
STRONG_PICK_GAP = 0.055

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

# Predicted score: points of margin per 1.00 of rating gap (fit on the 2026 backtest,
# 2,319 games: margin ~= 164 x rating gap). Each team's score = total/2 +/- margin/2.
POINTS_PER_RATING = 164
