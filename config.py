"""Settings for the CBB model. Edit the numbers here; nothing else needs touching."""
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")   # the game day and the tip times in the ledger are Eastern
CT = ZoneInfo("America/Chicago")    # site timestamps

# --- model knobs ---
# Four-factor weights: shooting (effective field goal %), turnovers, offensive rebounding and
# free throws (made per shot attempt), the same on offense and defense. See model.py.
# Until Nov 22, 2026 these were the 40/25/20/15 rule of thumb on plain field goal % and free
# throw %. Fitted on the 5,752 games between Division I teams in 2025-26 they come out
# 42/37/14/7: turnovers count for more than the rule of thumb says, rebounding and free throws
# for less (five different slices of that season gave the same weights within 3 points).
# Replay of every game of Nov 2-22, 2026 from that morning's data: 728-202 (78.3%) and an average
# miss of 10.37 points on the margin, against 715-215 and 10.53 for the old inputs and weights.
W_SHOOT, W_TOV, W_REB, W_FT = 0.42, 0.37, 0.14, 0.07
# The ratings changed scale with the formula above. Anything saved from an older formula that
# compares ratings across days (the Rankings page's "moved up / down") starts over when this
# number changes.
MODEL_VERSION = 2

# "Strong Pick" when the projected edge (rating gap incl. home court, in rating units) is
# bigger than this. 0.10 = a 17-point projected margin (17 / POINTS_PER_RATING).
# Replay of Nov 2-22, 2026 with the formula above: 303-7 (97.7%) on those picks, a third of all
# games. (The line was 15 points, 0.088, with the old formula: 336-8 in the same replay. At 15
# points the new formula goes 339-15, so the line moved to keep a Strong Pick as safe as it was.)
STRONG_PICK_GAP = 0.10

# Over/under play: flagged when the model's projected total is at least this many points
# above (Over) or below (Under) the betting line's over/under.
OU_EDGE_POINTS = 10

# Season record totals: the tiles at the top of the Results page, the record on the share image
# and the record table on the "How the model works" page. They were hidden for the first weeks of
# the season while the sample was small; back on from Nov 21, 2026 with 850+ graded games.
# Set to False to hide them again (the per-game results always show).
SHOW_RESULTS_STATS = True

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
# Nov 22, 2026 audit (replay of 930 games with the four-factor formula above): the average miss
# is the same to a tenth of a point for any scale from 150 to 190, and home court fits 3.4 to 3.9,
# so both stay where they are.
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
# Nov 22, 2026 audit: 2.0 is still the best value (average miss 10.35 points, against 10.57 at
# 1.5 and 10.49 at 2.5). This season's own weight (SOS_WEIGHT) makes no measurable difference
# yet, with six games a team; test both again in January.
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

# ---- About page: who runs the site and how to reach it ----
# Whatever is typed between these quotes is published on the site, so use a name and an address
# you are happy to make public. Left empty, nothing is shown.
OWNER_NAME = ""          # e.g. "Cory" or a full name: "built and run by ..."
CONTACT_EMAIL = "contact@tipoffedge.com"   # shown on the About and Privacy pages; forwards to your inbox (Cloudflare Email Routing)
# Accounts the About page links to. Remove a line to drop the link, add one in the same shape.
SOCIAL_LINKS = {
    "TikTok": "https://www.tiktok.com/@tipoffedge",
}

# A game's own page is listed for search engines for this many days after the game. Older game
# pages stay on the site (Results and the team pages link to them) but are marked "noindex":
# hundreds of one-game pages are not what the site should be judged by. The rankings, the team
# pages and the current games are.
GAME_PAGE_DAYS = 7
