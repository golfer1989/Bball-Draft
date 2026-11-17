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
# bigger than this. 0.088 = a 15-point projected margin (15 / POINTS_PER_RATING).
# Replay of Nov 2-16, 2026 with the settings below: 269-7 on those picks, 42% of games
# (the old 0.06 line, about 10 points, went 251-16 as the site ran).
STRONG_PICK_GAP = 0.088

# Over/under play: flagged when the model's projected total is at least this many points
# above (Over) or below (Under) the betting line's over/under.
OU_EDGE_POINTS = 10

# Season record totals at the top of the Results page. Hidden early in the season while the
# sample is small; set to True to show them again (the per-game results always show).
SHOW_RESULTS_STATS = False

# First-half pick = the full-game pick, and the projected halftime lead = this share of the
# projected final margin. (The old method, each team's first-half scoring over its last three
# games, went 316-177; replayed with today's settings, the full-game pick led at the half in
# 363 of those same 493 games, and gives a first-half pick for every game.)
FIRST_HALF_SHARE = 0.55

# Early season: last season's rating fades into this season's as each team plays games.
# A team's weight on this season = games played / BLEND_GAMES (100% from that game on), so
# rosters that changed over the summer take over gradually instead of a 3-game sample
# of mismatches replacing a full season at once.
BLEND_GAMES = 20
# A team new to Division I has no last season to fade from. It starts from the numbers of the
# team at this percentile of last season's ratings (10 = near the bottom) and earns its way
# up over BLEND_GAMES like everyone else.
NEW_TEAM_PERCENTILE = 10


def season_for(d):
    """RealGM labels a season by the year it ends: Nov 2026 - Apr 2027 -> 2027."""
    return d.year + 1 if d.month >= 7 else d.year


def now_et():
    return datetime.now(ET)

# Predicted margin (points) = POINTS_PER_RATING x rating gap + HOME_COURT_POINTS for the
# home team (none at neutral sites). Each team's predicted score = total/2 +/- margin/2.
# POINTS_PER_RATING was fit on 2,415 games played after Jan 21, 2026.
# HOME_COURT_POINTS was 2.7 until Nov 17, 2026. Replaying every game of Nov 2-16, 2026 with
# only the data available each morning, home teams did about 4 points better than their
# ratings. Worth re-checking once conference play starts.
POINTS_PER_RATING = 170
HOME_COURT_POINTS = 4.0

# Strength of schedule: rating += SOS_WEIGHT x (average results-based strength of the
# opponents played, in points / POINTS_PER_RATING). 1.0 = full adjustment, 0 = off.
SOS_WEIGHT = 1.0
# The same adjustment for LAST season's ratings, the ones that carry over into the early
# season (see BLEND_GAMES). The league a team plays in says more about next year's team than
# its own four-factor numbers do, so the carried-over rating leans on schedule twice as hard.
# In the Nov 2-16, 2026 replay this took the average miss on the margin from 11.9 points to
# 10.5 and stopped mismatches from being projected too close (a "12-point" pick was winning
# by 19). It fades out by itself as this season's games replace last season's.
SOS_WEIGHT_PREV = 2.0

# ---------------- website ----------------
SITE_NAME = "Tipoff Edge"
SITE_URL = "https://tipoffedge.com"
# Google AdSense publisher id, e.g. "ca-pub-1234567890123456". Empty = no ad code on the pages.
# Fill it in after AdSense approves the site; the ad slots are already laid out.
ADSENSE_CLIENT = "ca-pub-3574726017237257"

# Visitor counts: Cloudflare Web Analytics (free, no cookies). Paste the token from the
# Cloudflare dashboard (Web Analytics > your site > Manage site) between the quotes.
# Empty = no tracking code on the pages.
CF_ANALYTICS_TOKEN = "4eb81b5e8fd14715934e936b8fccbc87"

# Your private posting page (download the daily clip, copy the caption). Not linked from the
# site, not in the sitemap, marked no-index. Change the name to anything you like.
STUDIO_PAGE = "studio-95ea9e.html"
