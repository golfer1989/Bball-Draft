"""The daily clip: a 12-second vertical video (1080x1920) of the Game of the Day for TikTok,
Instagram Reels and YouTube Shorts, rebuilt by every overnight build as daily.mp4.

Five beats, cut on zoom-punches:
  1. the matchup    - the two teams' colors split the screen, badges and names slam in
  2. the question   - "WHO WINS?" while the numbers scramble
  3. the reveal     - the projected score rolls in, "<TEAM> WINS" stamps down, sparks fly
  4. the reasons    - three stat cards: model ranks, the best matchup on the floor, home court
  5. the end card   - tipoffedge.com

Everything is drawn with Pillow and piped straight into ffmpeg; nothing is downloaded except
the two team logos (cached in data/raw/logos). The lettering uses two open-source fonts that
sit beside this file (see fonts-license.txt); without them it falls back to the runner's
DejaVu and still renders.

The clip ships silent so the trending sound added in the app plays on its own.

What the clip and its caption may say is fenced in by flagged() below: TikTok and Instagram take
down content that markets gambling, so no bet, odds, line, spread or sportsbook word, and no
+/- number that reads like a price or a point spread, can reach the screen or the caption."""
import colorsys
import math
import random
import re
import shutil
import subprocess
import wave
from datetime import datetime
from pathlib import Path

import config
from share import _font, _logo

ROOT = Path(__file__).resolve().parent
W, H, FPS = 1080, 1920, 30
SECONDS = 12.0
BPM = 124
BLACK, INK, MUTE, AMBER, ORANGE = (0, 0, 0), (246, 246, 244), (156, 158, 166), (242, 165, 65), (224, 112, 29)
FONT_FILES = {"display": "big-shoulders-display-900.ttf", "label": "barlow-700.ttf"}
# scene starts, in seconds
T_ASK, T_REVEAL, T_WHY, T_END = 2.0, 3.4, 6.8, 9.9
T_STAMP = 4.9                                  # the moment "<TEAM> WINS" lands
POSTER = 2 / FPS                               # the clip opens on two frames of the finished matchup
SEAM_Y, SEAM_RISE = 830, 210                   # the diagonal where the two colors meet


# ---------------- what the clip and caption may never say ----------------
_BANNED = (
    r"bets?", r"betting", r"bettors?", r"wagers?", r"wagering", r"gambl\w*", r"casinos?", r"sports ?books?",
    r"bookies?", r"bookmakers?", r"the books?", r"odds", r"spreads?", r"money ?lines?", r"ml", r"parlays?",
    r"teasers?", r"props?", r"futures", r"over/under", r"o/u", r"the over", r"the under", r"cover(?:s|ed|ing)?",
    r"ats", r"pick'?em", r"picks?", r"locks?", r"units?", r"juice", r"vig", r"payouts?", r"winnings",
    r"cash(?:ed|ing)?(?: out)?", r"bankroll", r"stakes?", r"free money", r"guarantee[ds]?", r"can'?t lose",
    r"sure thing", r"vegas", r"draftkings", r"fanduel", r"betmgm", r"caesars", r"prizepicks", r"kalshi",
    r"polymarket", r"bovada", r"(?:betting|opening|closing|the) lines?", r"plus money",
)
_BANNED_RE = re.compile(r"(?<![a-z0-9])(?:" + "|".join(_BANNED) + r")(?![a-z0-9])", re.I)
_SIGNED_RE = re.compile(r"(?<![\w.])[+\-−–]\d")          # +7.5, -110, −3.5: prices and point spreads


def flagged(text):
    """Betting words (and +/- numbers that read like a price or spread) found in text, as a sorted
    list; empty means the text is safe to post. "Tipoff Edge" and scores like 78-73 are fine."""
    text = str(text or "").replace("’", "'")
    found = {m.group(0).lower() for m in _BANNED_RE.finditer(text)}
    found |= {m.group(0) for m in _SIGNED_RE.finditer(text)}
    return sorted(found)


# ---------------- small helpers ----------------
def clamp(x):
    return max(0.0, min(1.0, x))


def ease(t):
    return 1 - (1 - clamp(t)) ** 3


def ease_in(t):
    return clamp(t) ** 3


def back(t, s=1.9):
    """Ease out with a little overshoot, for things that slam into place."""
    t = clamp(t) - 1
    return 1 + t * t * ((s + 1) * t + s)


def rgb(hexstr, default=(92, 98, 112)):
    s = (hexstr or "").lstrip("#")
    try:
        return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4)) if len(s) == 6 else default
    except ValueError:
        return default


def tone(c):
    """A team color made fit for a dark screen: navies and blacks are lifted, greys stay grey."""
    h, s, v = colorsys.rgb_to_hsv(*(x / 255 for x in c))
    if s < 0.18:
        s, v = 0.05, (0.90 if v > 0.6 else 0.66)
    else:
        s, v = min(1.0, max(s, 0.62)), min(0.98, max(v, 0.72))
    return tuple(int(round(x * 255)) for x in colorsys.hsv_to_rgb(h, s, v))


def mix(a, b, k):
    return tuple(int(round(a[i] + (b[i] - a[i]) * k)) for i in range(3))


def far_apart(a, b):
    return math.dist(a, b) >= 120


_faces = {}


def face(kind, size):
    """The display or label font at a pixel size; DejaVu if the font file is not in the repo."""
    key = (kind, max(8, int(size)))
    if key not in _faces:
        from PIL import ImageFont
        try:
            _faces[key] = ImageFont.truetype(str(ROOT / FONT_FILES[kind]), key[1])
        except OSError:
            _faces[key] = _font(key[1], True)
    return _faces[key]


def fit(text, kind, max_w, size, floor=40):
    """Largest size <= size at which text is no wider than max_w."""
    while size > floor and face(kind, size).getlength(text) > max_w:
        size -= 4
    return size


_sprites = {}


def text_sprite(text, kind, size, fill=INK, stroke=0, stroke_fill=BLACK, shadow=None, skew=0.0):
    """Text as an RGBA image: optional outline, hard drop shadow (dx, dy, color) and italic slant."""
    key = (text, kind, int(size), fill, stroke, stroke_fill, shadow, skew)
    if key in _sprites:
        return _sprites[key]
    from PIL import Image, ImageDraw
    f = face(kind, size)
    pad = stroke + 8 + (max(abs(shadow[0]), abs(shadow[1])) if shadow else 0)
    l, t, r, b = f.getbbox(text, stroke_width=stroke)
    w, h = int(r - l + 2 * pad), int(b - t + 2 * pad)
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    x, y = pad - l, pad - t
    if shadow:
        d.text((x + shadow[0], y + shadow[1]), text, font=f, fill=shadow[2], stroke_width=stroke, stroke_fill=shadow[2])
    d.text((x, y), text, font=f, fill=fill, stroke_width=stroke, stroke_fill=stroke_fill)
    if skew:
        extra = int(abs(skew) * h)
        im = im.transform((w + extra, h), Image.AFFINE, (1, skew, -extra, 0, 1, 0), Image.BICUBIC)
    _sprites[key] = im
    return im


def put(im, sp, cx, cy, scale=1.0, alpha=1.0, anchor="mm"):
    """Paste an RGBA sprite on the frame. anchor: l/m/r then t/m/b."""
    from PIL import Image
    if sp is None or alpha <= 0.004 or scale <= 0.01:
        return
    if abs(scale - 1) > 0.004:
        sp = sp.resize((max(1, int(sp.width * scale)), max(1, int(sp.height * scale))), Image.BILINEAR)
    if alpha < 0.996:
        sp = sp.copy()
        sp.putalpha(sp.getchannel("A").point(lambda v: int(v * alpha)))
    x = cx - (sp.width // 2 if anchor[0] == "m" else sp.width if anchor[0] == "r" else 0)
    y = cy - (sp.height // 2 if anchor[1] == "m" else sp.height if anchor[1] == "b" else 0)
    im.paste(sp, (int(x), int(y)), sp)


def tracked(d, xy, text, font, fill, gap=6, anchor="l"):
    """Letter-spaced caps for the small labels. anchor l / m / r on x; y is the top."""
    widths = [font.getlength(ch) for ch in text]
    total = sum(widths) + gap * (len(text) - 1)
    x = xy[0] - (total / 2 if anchor == "m" else total if anchor == "r" else 0)
    for ch, w in zip(text, widths):
        d.text((x, xy[1]), ch, font=font, fill=fill)
        x += w + gap
    return total


def seam_y(x, mid=SEAM_Y, rise=SEAM_RISE):
    return mid + rise * (1 - 2 * x / W)


# ---------------- backgrounds (built once per clip) ----------------
def split_plate(top, bottom, mid=SEAM_Y, rise=SEAM_RISE, dim=1.0):
    """Two color fields meeting on a diagonal: bright at the seam, dark toward the screen edges
    (where the app's own buttons and caption sit), with a fine diagonal hatch."""
    import numpy as np
    from PIL import Image
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    d = (yy - (mid + rise * (1 - 2 * xx / W))) * 0.93                      # signed distance to the seam
    near = np.exp(-np.abs(d) / 620.0)[..., None]                            # 1 at the seam -> 0 far away
    edge = (1 - 0.62 * np.clip(np.abs(yy - mid) / 1150.0, 0, 1) ** 1.6)[..., None]
    hatch = (1 + 0.045 * np.sign(np.sin((xx + yy) * (2 * np.pi / 26.0))))[..., None]

    def field(c):
        c = np.array(c, np.float32)
        return (c * 0.26 + (c - c * 0.26) * near ** 0.85) * edge * hatch

    k = np.clip((d + 1.5) / 3.0, 0, 1)[..., None]                           # 0 above the seam, 1 below
    out = field(top) * (1 - k) + field(bottom) * k
    return Image.fromarray(np.clip(out * dim, 0, 255).astype(np.uint8), "RGB")


def dark_plate(a, b, strength=0.62):
    """Near-black with a glow of color a from the top-left and color b from the bottom-right."""
    import numpy as np
    from PIL import Image
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    ga = np.exp(-np.hypot(xx - 80, yy - 260) / 760.0)[..., None]
    gb = np.exp(-np.hypot(xx - (W - 80), yy - 1500) / 760.0)[..., None]
    hatch = (1 + 0.05 * np.sign(np.sin((xx + yy) * (2 * np.pi / 26.0))))[..., None]
    out = (np.array((9, 9, 13), np.float32) + np.array(a, np.float32) * ga * strength
           + np.array(b, np.float32) * gb * strength) * hatch
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGB")


def seam_glow(mid=SEAM_Y, rise=SEAM_RISE):
    """The white-hot line where the two colors meet."""
    from PIL import Image, ImageDraw, ImageFilter
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    a, b = (-60, seam_y(-60, mid, rise)), (W + 60, seam_y(W + 60, mid, rise))
    d.line([a, b], fill=(255, 255, 255, 210), width=46)
    im = im.filter(ImageFilter.GaussianBlur(22))
    ImageDraw.Draw(im).line([a, b], fill=(255, 255, 255, 255), width=7)
    return im


def ball_sprite(r):
    """The site's mark: an orange basketball."""
    import numpy as np
    from PIL import Image, ImageChops, ImageDraw
    s = 2 * r + 12
    yy, xx = np.mgrid[0:s, 0:s].astype(np.float32)
    c = s / 2
    dist = np.hypot(xx - c, yy - c)
    light = np.clip(1 - np.hypot(xx - c * 0.72, yy - c * 0.68) / (r * 1.5), 0, 1)[..., None]
    col = np.array((150, 62, 14), np.float32) + (np.array((255, 176, 86), np.float32) - np.array((150, 62, 14), np.float32)) * light
    alpha = np.clip(r - dist + 0.5, 0, 1)[..., None] * 255
    im = Image.fromarray(np.concatenate([np.clip(col, 0, 255), alpha], axis=2).astype(np.uint8), "RGBA")
    seams = Image.new("L", (s, s), 0)                      # the black seams, kept inside the ball's outline
    d = ImageDraw.Draw(seams)
    w = max(4, r // 13)
    d.line([(c, c - r), (c, c + r)], fill=255, width=w)
    d.line([(c - r, c), (c + r, c)], fill=255, width=w)
    d.arc([c - r * 1.62, c - r * 1.1, c - r * 0.42, c + r * 1.1], -70, 70, fill=255, width=w)
    d.arc([c + r * 0.42, c - r * 1.1, c + r * 1.62, c + r * 1.1], 110, 250, fill=255, width=w)
    d.ellipse([c - r, c - r, c + r, c + r], outline=255, width=w)
    inside = Image.fromarray((np.clip(r - dist + 0.5, 0, 1) * 255).astype(np.uint8), "L")
    im.paste((14, 10, 8, 255), (0, 0), ImageChops.multiply(seams, inside))
    return im


def badge(logo, abbr, color, r):
    """A team badge: dark disc, white ring, soft glow, the logo (or the abbreviation) inside."""
    from PIL import Image, ImageDraw, ImageFilter
    s = 2 * r + 80
    c = s // 2
    glow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([c - r - 6, c - r - 6, c + r + 6, c + r + 6], fill=color + (190,))
    im = glow.filter(ImageFilter.GaussianBlur(18))
    d = ImageDraw.Draw(im)
    d.ellipse([c - r, c - r, c + r, c + r], fill=(12, 12, 16, 255), outline=(255, 255, 255, 255), width=max(6, r // 14))
    if logo is not None:
        lg = logo.copy()
        lg.thumbnail((int(r * 1.34), int(r * 1.34)))
        im.paste(lg, (c - lg.width // 2, c - lg.height // 2), lg)
    else:
        f = face("display", fit(abbr, "display", r * 1.45, int(r * 0.95)))
        d.text((c, c), abbr, font=f, fill=(255, 255, 255, 255), anchor="mm")
    return im


def name_lines(name):
    """A school name in caps, split in two near the middle when it is long."""
    name = name.upper()
    if len(name) <= 15 or not re.search(r"[ -]", name):
        return [name]
    cuts = [m.end() for m in re.finditer(r"[ -]", name)]
    cut = min(cuts, key=lambda i: abs(i - len(name) / 2))
    return [name[:cut].strip(), name[cut:].strip()]


def short_name(name, abbr):
    return name.upper() if len(name) <= 14 else (abbr or name[:4]).upper()


def tip_time(when):
    """'Nov 17, 2026 7:00 PM ET' -> '6:00 PM CT' ('' if the time is missing)."""
    try:
        et = datetime.strptime((when or "").replace(" ET", ""), "%b %d, %Y %I:%M %p").replace(tzinfo=config.ET)
    except ValueError:
        return ""
    return et.astimezone(config.CT).strftime("%-I:%M %p CT")


def confidence(margin):
    """(level 1-5, word) from the projected margin in points."""
    for limit, level, word in ((3, 1, "TOSS-UP"), (6, 2, "SLIGHT EDGE"), (10, 3, "SOLID"), (15, 4, "STRONG")):
        if margin < limit:
            return level, word
    return 5, "VERY STRONG"


class Clip:
    """One day's clip: every string and picture is prepared once, then frame(t) draws a moment."""

    def __init__(self, game, wu, teams, pred, date_label, logos=(None, None), render=True):
        """render=False prepares the words only (for the betting-word check), not the pictures."""
        teams, wu = teams or {}, wu or {}
        ta, th = teams.get(str(game["away_id"])) or {}, teams.get(str(game["home_id"])) or {}
        self.away, self.home = game["away"], game["home"]
        self.abbr = [(ta.get("abbr") or self.away[:4]).upper()[:5], (th.get("abbr") or self.home[:4]).upper()[:5]]
        ca, ch = tone(rgb(ta.get("color"))), tone(rgb(th.get("color")))
        if not far_apart(ca, ch):                       # two blue teams: one side goes silver
            ca = (226, 230, 238)
        self.col = [ca, ch]
        self.home_pick = game["pick"] == self.home
        w, l = (1, 0) if self.home_pick else (0, 1)
        self.w, self.l = w, l
        self.names = [self.away, self.home]
        self.short = [short_name(self.away, self.abbr[0]), short_name(self.home, self.abbr[1])]
        pa, ph = pred or (None, None)
        self.score = [pa, ph] if pa is not None and ph is not None else None
        try:
            model_margin = float(game.get("differential") or 0) * config.POINTS_PER_RATING
        except (TypeError, ValueError):
            model_margin = 0.0
        self.margin = abs(pa - ph) if self.score else int(round(model_margin))
        self.level, self.level_word = confidence(model_margin or self.margin)
        self.ranks = [wu.get("away_rank"), wu.get("home_rank")]
        self.neutral = str(game.get("neutral") or "") in ("1", "True", "true")
        self.kicker = "GAME OF THE DAY"
        parts = (date_label or "").replace(",", "").split()
        self.date = " ".join([parts[0][:3]] + parts[1:]).upper() if parts else ""
        tip = tip_time(game.get("when"))
        self.tip = f"TIP-OFF {tip}" if tip else ""
        self.cards = self._cards(wu)
        self.stamp = name_lines(self.names[w]) + ["WINS"]
        self.by = (f"BY {self.margin}" if self.margin >= 2 else "BY A BUCKET")
        self.why = f"WHY {self.short[w]}?"
        self.unsafe = [s for s in self.text() if flagged(s)]
        if not render:
            return
        self._assets(logos)
        self.rnd = random.Random(7)
        self.sparks = [(self.rnd.uniform(0, 2 * math.pi), self.rnd.uniform(500, 1900), self.rnd.uniform(0.5, 1.1),
                        self.rnd.choice((0, 0, 1)), self.rnd.uniform(5, 13)) for _ in range(120)]
        self.streaks = [(self.rnd.uniform(-1100, 1100), self.rnd.uniform(0, 1), self.rnd.uniform(700, 2100),
                         self.rnd.uniform(140, 520), self.rnd.choice((3, 4, 6, 10)), self.rnd.randint(16, 60)) for _ in range(22)]
        self.embers = [(self.rnd.uniform(0, W), self.rnd.uniform(0, H), self.rnd.uniform(90, 260), self.rnd.uniform(2, 6))
                       for _ in range(34)]

    # ----- words -----
    def _cards(self, wu):
        """Three (figure, title, line) stat cards. Nothing here mentions a betting line."""
        w, l = self.w, self.l
        facts = wu.get("facts") or {}
        cards = []
        if self.ranks[w] and self.ranks[l] and self.ranks[w] < self.ranks[l]:
            cards.append((f"#{self.ranks[w]}", f"{self.short[w]} IN THE MODEL",
                          f"{self.short[l]} IS #{self.ranks[l]}" + (f" OF {wu['n']}" if wu.get("n") else "")))
        elif self.ranks[w] and self.ranks[l]:               # the lower-ranked team is the call: say how close it is
            cards.append(("EVEN", "CLOSE IN THE MODEL", f"#{self.ranks[w]} AGAINST #{self.ranks[l]}"))
        unit, ur, vr = facts.get("unit"), facts.get("unit_rank"), facts.get("vs_rank")
        if unit in ("offense", "defense") and ur and vr and ur < vr:
            other = "DEFENSE" if unit == "offense" else "OFFENSE"
            cards.append((f"#{ur}", f"{self.short[w]} {unit.upper()}", f"AGAINST THE #{vr} {other}"))
        elif self.score:
            cards.append((str(self.margin), "POINT WIN PROJECTED", f"{max(self.score)}-{min(self.score)} FINAL"))
        if self.neutral:
            cards.append(("0", "HOME COURT EDGE", "NEUTRAL SITE GAME"))
        elif self.home_pick:
            cards.append((f"{config.HOME_COURT_POINTS:g}", "POINTS FOR HOME COURT", f"{self.short[1]} PLAYS AT HOME"))
        else:
            cards.append(("ROAD", "WINNING AWAY FROM HOME", f"{self.short[1]} HAS HOME COURT"))
        if len(cards) < 3 and self.score and not any(c[1] == "POINT WIN PROJECTED" for c in cards):
            cards.insert(1, (str(self.margin), "POINT WIN PROJECTED", f"{max(self.score)}-{min(self.score)} FINAL"))
        return cards[:3]

    def text(self):
        """Every string the clip puts on screen (the list the betting-word check runs over)."""
        out = [self.kicker, self.date, self.tip, "VS", "WHO", "WINS?", "THE MODEL RAN THE NUMBERS", "SHOOTING", "TURNOVERS",
               "REBOUNDING", "SCHEDULE", "PROJECTED FINAL", self.by, "MODEL CONFIDENCE", self.level_word, self.why,
               "FULL BREAKDOWN AT", "TIPOFFEDGE.COM", "EVERY GAME", "EVERY DAY", "FREE", "FOLLOW FOR TOMORROW'S GAME",
               "TIPOFF EDGE", "IN THE MODEL"] + self.stamp + self.short + self.abbr
        out += [x for n in self.names for x in name_lines(n)]
        out += [f"#{r}" for r in self.ranks if r]
        out += [s for c in self.cards for s in c]
        if self.score:
            out += [str(self.score[0]), str(self.score[1])]
        return [s for s in out if s]

    # ----- pictures -----
    def _assets(self, logos):
        from PIL import Image
        ca, ch = self.col
        wc = self.col[self.w]
        self.plate_split = split_plate(ca, ch)
        self.plate_split_dim = split_plate(ca, ch, dim=0.5)
        self.plate_win = split_plate(wc, mix(wc, BLACK, 0.45), mid=1240, rise=260)
        self.plate_ask = dark_plate(ca, ch)
        self.plate_why = dark_plate(wc, mix(wc, BLACK, 0.5), 0.5)
        self.plate_end = dark_plate(ORANGE, (120, 52, 10), 0.6)
        self.seam = seam_glow()
        self.badges = [badge(logos[i], self.abbr[i], self.col[i], 135) for i in (0, 1)]
        self.badges_small = [b.resize((240, 240), Image.LANCZOS) for b in self.badges]
        self.ball = ball_sprite(150)
        self.ball_small = ball_sprite(26)
        self.ghost = [text_sprite(self.abbr[i], "display", 640, fill=(255, 255, 255, 30), skew=0.16) for i in (0, 1)]

    def _plate(self, t):
        if t < T_ASK:
            return self.plate_split
        if t < T_REVEAL:
            return self.plate_ask
        if t < T_WHY:
            return self.plate_split_dim if t < T_STAMP else self.plate_win
        return self.plate_why if t < T_END else self.plate_end

    def _streaks(self, d, t, alpha=1.0):
        """Speed lines running along the seam."""
        ux, uy = W, -2 * SEAM_RISE
        n = math.hypot(ux, uy)
        ux, uy = ux / n, uy / n
        for off, phase, speed, length, width, a in self.streaks:
            s = ((phase * 2600 + speed * t) % 2600) - 700
            cx, cy = W / 2 + ux * (s - 600) - uy * off, SEAM_Y + uy * (s - 600) + ux * off
            d.line([(cx, cy), (cx + ux * length, cy + uy * length)], fill=(255, 255, 255, int(a * alpha)), width=width)

    def _burst(self, d, origin, tau, colors):
        """Sparks thrown from an impact, tau seconds ago."""
        if tau < 0 or tau > 1.1:
            return
        for ang, speed, life, ci, size in self.sparks:
            if tau > life:
                continue
            vx, vy = math.cos(ang) * speed, math.sin(ang) * speed
            drag = 1 - math.exp(-3.2 * tau)
            x = origin[0] + vx * drag / 3.2
            y = origin[1] + vy * drag / 3.2 + 900 * tau * tau
            k = 1 - tau / life
            tx, ty = x - vx * 0.055 * k, y - vy * 0.055 * k
            d.line([(tx, ty), (x, y)], fill=colors[ci] + (int(255 * min(1.0, k * 1.6)),), width=max(3, int(size * (0.5 + k))))

    def _ring(self, d, origin, tau, color=(255, 255, 255), speed=1500, life=0.45, width=18):
        if 0 <= tau <= life:
            r, k = 40 + speed * tau, 1 - tau / life
            d.ellipse([origin[0] - r, origin[1] - r, origin[0] + r, origin[1] + r], outline=color + (int(230 * k),),
                      width=max(2, int(width * k)))

    # ----- the five scenes -----
    def _matchup(self, im, d, t):
        put(im, self.ghost[0], 40 + 26 * t, 420, anchor="lm")
        put(im, self.ghost[1], W - 40 - 26 * t, 1300, anchor="rm")
        self._streaks(d, t)
        put(im, self.seam, W // 2, H // 2, alpha=0.55 + 0.45 * ease(t / 0.3))
        # away team top-left, home team bottom-right, each on its own color
        for i, (t0, bx, by, side) in enumerate(((0.10, 215, 360, "l"), (0.42, 815, 1300, "r"))):
            k = back((t - t0) / 0.30)
            if t >= t0:
                put(im, self.badges[i], bx, by, scale=2.3 - 1.3 * k, alpha=clamp((t - t0) / 0.12))
            lines = name_lines(self.names[i])
            size = min(fit(x, "display", 860 if len(lines) == 1 else 760, 210 if len(lines) == 1 else 118) for x in lines)
            kn = back((t - t0 - 0.10) / 0.32, 1.4)
            drift = 14 * clamp((t - 0.9) / 1.1)
            if t >= t0 + 0.10:
                step = int(size * 0.86)
                top = 728 - step * len(lines) - 26 if side == "l" else 930      # away name ends above the VS, home starts below
                for j, line in enumerate(lines):
                    sp = text_sprite(line, "display", size, stroke=10, shadow=(9, 11, mix(self.col[i], BLACK, 0.78)), skew=0.12)
                    y = top + j * step
                    if side == "l":
                        put(im, sp, 56 - (1 - kn) * 900 - drift, y, anchor="lt")
                    else:
                        put(im, sp, 930 + (1 - kn) * 900 + drift, y, anchor="rt")
                glint = (t - t0 - 0.75) / 0.4                                   # a light sweeps across the name
                if 0 <= glint <= 1:
                    gx, gy = int(-80 + 1160 * glint), top - 10
                    gh = step * len(lines) + 60
                    d.polygon([(gx, gy), (gx + 110, gy), (gx + 40, gy + gh), (gx - 70, gy + gh)], fill=(255, 255, 255, 60))
            if self.ranks[i] and t >= t0 + 0.24:
                kr = back((t - t0 - 0.24) / 0.25)
                sp = text_sprite(f"#{self.ranks[i]}", "display", 150, stroke=8, shadow=(6, 8, BLACK))
                lab = text_sprite("IN THE MODEL", "label", 34, fill=(255, 255, 255))
                if side == "l":
                    put(im, sp, 390, 328, scale=kr, anchor="lm")
                    put(im, lab, 396, 422, alpha=kr, anchor="lm")
                else:
                    put(im, sp, 640, 1262, scale=kr, anchor="rm")
                    put(im, lab, 634, 1356, alpha=kr, anchor="rm")
        tv = t - 0.85
        if tv >= 0:
            c = (W // 2, int(seam_y(W / 2)))
            self._ring(d, c, tv)
            kv = back(tv / 0.28)
            r = int(94 * kv * (1 + 0.04 * math.sin(t * 9)))
            d.ellipse([c[0] - r, c[1] - r, c[0] + r, c[1] + r], fill=(8, 8, 12, 255), outline=(255, 255, 255, 255), width=9)
            put(im, text_sprite("VS", "display", 110, skew=0.1), c[0] + 4, c[1] - 2, scale=kv)
        tk = t - 1.0
        if tk >= 0:
            k = ease(tk / 0.3)
            room = W - 56 - 44 - (122 + face("display", 50).getlength("TIPOFF EDGE") + 36)
            f = face("display", fit(self.kicker, "display", room, 52, 24))
            wk = int(f.getlength(self.kicker)) + 44
            x0 = int(W - 56 - wk + (1 - k) * 600)
            d.rounded_rectangle([x0, 138, x0 + wk, 206], radius=12, fill=AMBER + (255,))
            d.text((x0 + 22, 172), self.kicker, font=f, fill=(12, 10, 8, 255), anchor="lm")
            when = "  \u00b7  ".join(x for x in (self.date, self.tip) if x)
            if when:
                fw = face("label", fit(when, "label", 500, 38, 20))
                tracked(d, (56, 1408), when, fw, (255, 255, 255, int(235 * k)), gap=3)

    def _ask(self, im, d, t):
        tt = t - T_ASK
        self._streaks(d, t, 0.6)
        for i, x in ((0, W // 2 - 190), (1, W // 2 + 190)):
            put(im, self.badges_small[i], x, 430, scale=0.9 + 0.1 * back(tt / 0.3))
        put(im, text_sprite("VS", "display", 80, fill=MUTE), W // 2, 430)
        for j, (word, y) in enumerate((("WHO", 760), ("WINS?", 1090))):
            k = back((tt - 0.08 - 0.14 * j) / 0.26, 2.4)
            if tt >= 0.08 + 0.14 * j:
                jit = int(10 * max(0.0, 1 - (tt - 0.08 - 0.14 * j) / 0.22) * math.sin(t * 90))
                sp = text_sprite(word, "display", fit(word, "display", 880, 400), fill=INK, stroke=12, shadow=(12, 14, self.col[j]), skew=0.12)
                put(im, sp, W // 2 + jit, y, scale=1.7 - 0.7 * k)
        if tt >= 0.5:
            a = int(255 * ease((tt - 0.5) / 0.25))
            tracked(d, (W // 2, 1300), "THE MODEL RAN THE NUMBERS", face("label", 42), (255, 255, 255, a), gap=5, anchor="m")
            rr = random.Random(int(t * 15))
            for j, lab in enumerate(("SHOOTING", "TURNOVERS", "REBOUNDING", "SCHEDULE")):
                cx = 150 + j * 260
                d.text((cx, 1408), f"{rr.randint(10, 99)}.{rr.randint(0, 9)}", font=face("display", 84), fill=(255, 255, 255, a), anchor="mm")
                d.text((cx, 1470), lab, font=face("label", 26), fill=MUTE + (a,), anchor="mm")
            p = ease_in((tt - 0.5) / 0.8)
            d.rounded_rectangle([90, 1520, W - 90, 1540], radius=10, fill=(255, 255, 255, 40))
            d.rounded_rectangle([90, 1520, 90 + int((W - 180) * p), 1540], radius=10, fill=AMBER + (255,))

    def _reveal(self, im, d, t):
        tt, w, l = t - T_REVEAL, self.w, self.l
        hit = t - T_STAMP
        self._streaks(d, t, 0.8 if hit >= 0 else 0.4)
        if hit >= 0:
            put(im, self.ghost[w], W // 2, 1560, alpha=0.9)
        up = ease((hit + 0.22) / 0.22)                    # 0 while the score rolls, 1 once it has moved up
        sy = int(300 * (1 - up))                           # how far below its final place the scoreboard sits
        tracked(d, (W // 2, 262 + sy), "PROJECTED FINAL", face("label", 46), (255, 255, 255, int(255 * ease(tt / 0.25))), gap=8, anchor="m")
        if self.score:
            rr = random.Random(int(t * 15))
            for i, (cx, bx, lock) in enumerate(((372, 112, 0.75), (708, W - 112, 1.0))):
                done = tt >= lock
                val = self.score[i] if done else max(30, self.score[i] + rr.randint(-28, 28))
                pop = 1 + 0.22 * max(0.0, 1 - (tt - lock) / 0.18) if done else 1.0
                dim = hit >= 0 and i == l
                fill = (255, 255, 255, 105) if dim else INK
                size = fit(str(val), "display", 300, 360)
                sp = text_sprite(str(val), "display", size, fill=fill, stroke=0 if dim else 10, shadow=None if dim else (10, 12, BLACK))
                put(im, sp, cx, 500 + sy, scale=pop * ease(tt / 0.2))
                put(im, self.badges_small[i], bx, 470 + sy, scale=0.7)
                tracked(d, (bx, 572 + sy), self.abbr[i], face("label", 36), (255, 255, 255, 120 if dim else 255), gap=3, anchor="m")
            d.rounded_rectangle([W // 2 - 22, 492 + sy, W // 2 + 22, 508 + sy], radius=8, fill=(255, 255, 255, 150))
            if hit < -0.22:                                 # while it rolls: both names wait underneath
                a = int(200 * ease((tt - 0.25) / 0.3))
                both = f"{self.short[0]}  OR  {self.short[1]}?"
                d.text((W // 2, 1100), both, font=face("display", fit(both, "display", 900, 120)), fill=(255, 255, 255, a), anchor="mm")
        cap = 240 if len(self.stamp) == 2 else 160                         # a two-line school name gets smaller lines
        sizes = [fit(x, "display", 900, cap) for x in self.stamp[:-1]] + [300]
        tall = sum(int(s * 0.84) for s in sizes)
        centre = (W // 2, 660 + tall // 2)
        by_y, meter_y = 660 + tall + 26, min(1400, 660 + tall + 26 + 124 + 62)
        if hit >= -0.16:
            k = ease_in((hit + 0.16) / 0.16)
            y = 660
            wc = self.col[w]
            for line, size in zip(self.stamp, sizes):
                last = line == "WINS"
                sp = text_sprite(line, "display", size, fill=AMBER if last else INK, stroke=12,
                                 shadow=(12, 14, BLACK if last else mix(wc, BLACK, 0.7)), skew=0.14)
                put(im, sp, W // 2, y + int(size * 0.42), scale=3.0 - 2.0 * k, alpha=clamp((hit + 0.16) / 0.08))
                y += int(size * 0.84)
            self._ring(d, centre, hit, speed=2100, life=0.5, width=26)
            self._burst(d, centre, hit, (INK, AMBER))
        tb = hit - 0.42
        if tb >= 0:
            k = back(tb / 0.25)
            f = face("display", 104)
            wb = int(f.getlength(self.by)) + 70
            x0, y0 = W // 2 - int(wb * k) // 2, by_y
            d.rounded_rectangle([x0, y0, x0 + int(wb * k), y0 + 124], radius=20, fill=(255, 255, 255, 255))
            if k > 0.75:
                d.text((W // 2, y0 + 62), self.by, font=f, fill=(10, 10, 12, 255), anchor="mm")
        tm = hit - 0.85
        if tm >= 0:
            a = int(255 * ease(tm / 0.2))
            y0 = meter_y
            d.rounded_rectangle([56, y0 - 26, 56 + 870, y0 + 66], radius=20, fill=(0, 0, 0, int(165 * ease(tm / 0.2))))
            tracked(d, (84, y0), "MODEL CONFIDENCE", face("label", 34), (255, 255, 255, a), gap=3)
            for s in range(5):
                on = tm >= 0.14 * (s + 1) and s < self.level
                x = 478 + s * 40
                d.polygon([(x, y0 - 2), (x + 22, y0 - 2), (x + 36, y0 + 20), (x + 22, y0 + 42), (x, y0 + 42), (x + 14, y0 + 20)],
                          fill=(AMBER + (255,)) if on else (255, 255, 255, 60))
            if tm >= 0.14 * (self.level + 1):
                fw = face("display", fit(self.level_word, "display", 216, 52, 30))
                d.text((694, y0 + 20), self.level_word, font=fw, fill=AMBER + (255,), anchor="lm")

    def _why(self, im, d, t):
        tt, w = t - T_WHY, self.w
        self._streaks(d, t, 0.45)
        wc = self.col[w]
        size = fit(self.why, "display", 770, 230)
        put(im, self.ghost[w], W // 2, 1660, alpha=0.7)
        head = text_sprite(self.why, "display", size, stroke=10, shadow=(10, 12, mix(wc, BLACK, 0.55)), skew=0.12)
        put(im, head, 56 - (1 - back(tt / 0.3, 1.3)) * 900, 470, anchor="lb")
        k = ease((tt - 0.2) / 0.35)
        d.rounded_rectangle([60, 476, 60 + int(520 * k), 488], radius=6, fill=wc + (255,))
        put(im, self.badges_small[w], 948, 345, scale=0.75 * back(tt / 0.3))
        for j, (fig, title, sub) in enumerate(self.cards):
            t0 = 0.30 + 0.72 * j
            if tt < t0:
                continue
            k = back((tt - t0) / 0.34, 1.3)
            x0, y0 = int(56 + (1 - k) * 1100), 540 + j * 300
            d.rounded_rectangle([x0, y0, x0 + 968, y0 + 258], radius=30, fill=(14, 14, 19, 242), outline=(255, 255, 255, 46), width=3)
            d.rounded_rectangle([x0, y0, x0 + 270, y0 + 258], radius=30, fill=wc + (255,))
            d.rectangle([x0 + 240, y0, x0 + 270, y0 + 258], fill=wc + (255,))
            dark = sum(wc) > 420
            f = face("display", fit(fig, "display", 232, 170))
            d.text((x0 + 135, y0 + 126), fig, font=f, fill=(10, 10, 12, 255) if dark else (255, 255, 255, 255), anchor="mm")
            ft = face("display", fit(title, "display", 600, 78))
            d.text((x0 + 306, y0 + 96), title, font=ft, fill=INK + (255,), anchor="lm")
            fs = face("label", fit(sub, "label", 600, 38, 24))
            d.text((x0 + 308, y0 + 176), sub, font=fs, fill=(196, 198, 206, 255), anchor="lm")
            sweep = (tt - t0 - 0.30) / 0.35
            if 0 <= sweep <= 1:
                sx = x0 + int(1100 * sweep) - 80
                d.polygon([(sx, y0), (sx + 70, y0), (sx + 10, y0 + 258), (sx - 60, y0 + 258)], fill=(255, 255, 255, 46))

    def _end(self, im, d, t):
        tt = t - T_END
        for x, y, speed, size in self.embers:
            yy = (y - speed * t) % H
            xx = x + 26 * math.sin(t * 1.7 + y)
            d.ellipse([xx - size, yy - size, xx + size, yy + size], fill=AMBER + (int(150 * (0.4 + 0.6 * (yy / H))),))
        c = (W // 2, 520)
        self._ring(d, c, tt - 0.12, AMBER, speed=1300, life=0.5)
        put(im, self.ball, c[0], c[1], scale=back(tt / 0.36))
        if tt >= 0.3:
            a = int(255 * ease((tt - 0.3) / 0.25))
            tracked(d, (W // 2, 760), "FULL BREAKDOWN AT", face("label", 44), (255, 255, 255, a), gap=7, anchor="m")
        if tt >= 0.42:
            k = back((tt - 0.42) / 0.3, 1.5)
            size = fit("TIPOFFEDGE.COM", "display", 960, 210)
            put(im, text_sprite("TIPOFFEDGE.COM", "display", size, stroke=6, shadow=(8, 10, (120, 52, 10))), W // 2, 920, scale=1.5 - 0.5 * k)
            u = ease((tt - 0.7) / 0.35)
            d.rounded_rectangle([W // 2 - int(430 * u), 1030, W // 2 + int(430 * u), 1044], radius=7, fill=AMBER + (255,))
            sweep = (tt - 0.85) / 0.5
            if 0 <= sweep <= 1:
                sx = int(-100 + (W + 200) * sweep)
                d.polygon([(sx, 820), (sx + 90, 820), (sx + 30, 1020), (sx - 60, 1020)], fill=(255, 255, 255, 70))
        f = face("display", 60)
        chips = ("EVERY GAME", "EVERY DAY", "FREE")
        widths = [int(f.getlength(c)) + 48 for c in chips]
        x = (W - sum(widths) - 24 * 2) // 2
        for j, (chip, wc) in enumerate(zip(chips, widths)):
            k = back((tt - 0.85 - 0.13 * j) / 0.22)
            if tt >= 0.85 + 0.13 * j:
                hh = int(84 * k)
                d.rounded_rectangle([x, 1150 - hh // 2, x + wc, 1150 + hh // 2], radius=14, outline=(255, 255, 255, 255), width=4,
                                    fill=(255, 255, 255, 26))
                if k > 0.8:
                    d.text((x + wc // 2, 1150), chip, font=f, fill=INK + (255,), anchor="mm")
            x += wc + 24
        if tt >= 1.25:
            k = ease((tt - 1.25) / 0.25)
            pulse = 1 + 0.035 * math.sin(t * 8)
            put(im, text_sprite("FOLLOW FOR TOMORROW'S GAME", "display", fit("FOLLOW FOR TOMORROW'S GAME", "display", 900, 88),
                                fill=AMBER, stroke=5), W // 2, 1330, scale=pulse, alpha=k)

    # ----- one frame -----
    def frame(self, t):
        from PIL import Image, ImageChops, ImageDraw
        poster = t < POSTER                                # the first frames are the finished matchup: the cover image
        im = self._plate(t).copy()
        d = ImageDraw.Draw(im, "RGBA")
        if t < T_ASK:
            self._matchup(im, d, 1.9 if poster else t - POSTER)
        elif t < T_REVEAL:
            self._ask(im, d, t)
        elif t < T_WHY:
            self._reveal(im, d, t)
        elif t < T_END:
            self._why(im, d, t)
        else:
            self._end(im, d, t)
        d = ImageDraw.Draw(im, "RGBA")
        # brand strip, top (below the app's own tabs)
        if t < T_END:
            put(im, self.ball_small, 82, 172)
            d.text((122, 172), "TIPOFF EDGE", font=face("display", 50), fill=(255, 255, 255, 240), anchor="lm")
            if self.date and t >= T_ASK:                    # the matchup scene has "GAME OF THE DAY" there instead
                d.text((W - 60, 172), self.date, font=face("label", 34), fill=(255, 255, 255, 220), anchor="rm")
        # progress bar
        d.rectangle([0, 0, W, 12], fill=(0, 0, 0, 150))
        d.rectangle([0, 0, int(W * t / SECONDS), 12], fill=AMBER + (255,))
        # cuts and impacts: zoom punch, flash, shake, color split
        z, flash, shake, split = 1.0, 0.0, 0.0, 0.0
        o = t - POSTER                                      # time since the build started
        if 0 <= o < 0.22:
            z = 1.38 - 0.38 * ease(o / 0.2)
            flash = 0.32 * max(0.0, 1 - o / 0.10)
            shake = 20 * (1 - o / 0.22)
            split = max(0.0, 1 - o / 0.18)
        for cut in (T_ASK, T_REVEAL, T_WHY, T_END):
            if cut - 0.13 <= t < cut:
                z = 1 + 0.32 * ease_in((t - cut + 0.13) / 0.13)
                flash = max(flash, 0.26 * ease_in((t - cut + 0.13) / 0.13))
            elif cut <= t < cut + 0.17:
                z = 1 + 0.16 * (1 - ease((t - cut) / 0.17))
                flash = max(flash, 0.26 * (1 - (t - cut) / 0.10))
                split = max(split, 1 - (t - cut) / 0.14)
        for t0, amp, fl, sp in ((POSTER + 0.85, 14, 0.22, 0.0), (T_REVEAL + 0.75, 7, 0.0, 0.0), (T_REVEAL + 1.0, 9, 0.0, 0.0),
                                (T_STAMP, 34, 0.45, 1.0), (T_STAMP + 0.42, 9, 0.0, 0.0), (T_WHY + 0.55, 7, 0.0, 0.0),
                                (T_WHY + 1.27, 7, 0.0, 0.0), (T_WHY + 1.99, 7, 0.0, 0.0), (T_END + 0.30, 12, 0.2, 0.0)):
            if t0 <= t < t0 + 0.3:
                k = 1 - (t - t0) / 0.3
                shake = max(shake, amp * k)
                flash = max(flash, fl * max(0.0, 1 - (t - t0) / 0.10))
                split = max(split, sp * max(0.0, 1 - (t - t0) / 0.16))
        if z > 1.004:
            w, h = int(W / z), int(H / z)
            im = im.resize((W, H), Image.BILINEAR, box=((W - w) // 2, (H - h) // 2, (W - w) // 2 + w, (H - h) // 2 + h))
        if flash > 0.01:
            im = Image.blend(im, Image.new("RGB", (W, H), (255, 255, 255)), min(0.7, flash))
        if shake > 0.6:
            rr = random.Random(int(t * 1000))
            im = ImageChops.offset(im, int(rr.uniform(-shake, shake)), int(rr.uniform(-shake, shake)))
        if split > 0.03:
            r, g, b = im.split()
            s = int(16 * split)
            im = Image.merge("RGB", (ImageChops.offset(r, s, 0), g, ImageChops.offset(b, -s, 0)))
        return im


def clip_text(game, wu, teams, pred, date_label):
    """Every string the day's clip will show, for the betting-word check and the tests."""
    return Clip(game, wu, teams, pred, date_label, render=False).text()


def beat(seconds, path, bpm=BPM, sr=44100):
    """An original, royalty-free beat: kick, hat, snare, a sub bass line and a soft pad."""
    import numpy as np
    n = int(seconds * sr)
    t = np.arange(n) / sr
    out = np.zeros(n)
    step = 60 / bpm / 4                                   # 16th note
    rng = np.random.default_rng(7)
    notes = [55.0, 55.0, 65.41, 49.0]                     # A1 A1 C2 G1, one bar each
    for i in range(int(seconds / step) + 1):
        s0 = int(i * step * sr)
        if s0 >= n:
            break
        bar, sixteenth = (i // 16) % 4, i % 16
        seg = t[s0:s0 + int(0.5 * sr)] - t[s0]
        if sixteenth in (0, 8) or (sixteenth == 11 and bar % 2 == 1):          # kick
            k = np.sin(2 * np.pi * (60 * np.exp(-seg * 9) + 40) * seg) * np.exp(-seg * 7)
            out[s0:s0 + len(k)] += 0.9 * k
        if sixteenth in (4, 12):                                                # snare
            sn = (rng.standard_normal(len(seg)) * np.exp(-seg * 22) + np.sin(2 * np.pi * 190 * seg) * np.exp(-seg * 30)) * 0.45
            out[s0:s0 + len(sn)] += sn
        if sixteenth % 2 == 0:                                                  # hats
            hh = rng.standard_normal(len(seg)) * np.exp(-seg * (60 if sixteenth % 4 else 30)) * 0.12
            out[s0:s0 + len(hh)] += hh
        if sixteenth in (0, 3, 6, 10, 12):                                      # bass
            f0 = notes[bar]
            bs = np.sin(2 * np.pi * f0 * seg) * np.exp(-seg * 5) * 0.5
            bs += np.sin(2 * np.pi * f0 * 2 * seg) * np.exp(-seg * 9) * 0.12
            out[s0:s0 + len(bs)] += bs
    pad = sum(np.sin(2 * np.pi * f * t) * 0.03 for f in (220.0, 261.6, 329.6))  # soft A minor pad
    out += pad * (0.5 + 0.5 * np.sin(2 * np.pi * t / 8))
    fade = min(n, int(0.8 * sr))
    out[-fade:] *= np.linspace(1, 0, fade)
    out[:int(0.05 * sr)] *= np.linspace(0, 1, int(0.05 * sr))
    out = np.tanh(out * 1.4) * 0.85
    pcm = (out * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return path


def ffmpeg_exe():
    """ffmpeg from PATH, else the copy bundled in the imageio-ffmpeg package (requirements.txt)."""
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:                                     # noqa: BLE001
        return None


def daily_video(path, date_label, game, wu, teams, pred, seconds=SECONDS):
    """Render daily.mp4. Returns the path, or None when ffmpeg is missing, there is no game, or the
    betting-word check finds something on screen it shouldn't (nothing unsafe is ever written)."""
    exe = ffmpeg_exe()
    if not game or not exe:
        return None
    teams = teams or {}
    logos = [None, None]
    if getattr(config, "CLIP_LOGOS", True):
        logos = [_logo((teams.get(str(game[k])) or {}).get("logo"), 320) for k in ("away_id", "home_id")]
    clip = Clip(game, wu, teams, pred, date_label, logos)
    if clip.unsafe:
        print(f"  ! daily clip not rendered: flagged on-screen text {clip.unsafe}", flush=True)
        return None
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.stem + ".part.mp4")           # a stopped render never leaves a short daily.mp4
    # silent on purpose: the sound gets added in TikTok / Instagram, and a baked-in track would
    # play underneath it. beat() is kept for anyone who wants a soundtrack version.
    cmd = [exe, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-c:v", "libx264", "-preset", "slow", "-crf", "30", "-pix_fmt", "yuv420p", "-an", "-movflags", "+faststart", str(tmp)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for i in range(int(seconds * FPS)):
            proc.stdin.write(clip.frame(i / FPS).tobytes())
    finally:
        proc.stdin.close()
        proc.wait()
    if proc.returncode != 0 or not tmp.exists():
        tmp.unlink(missing_ok=True)
        return None
    tmp.replace(out)
    return out


def hashtag(name):
    """'Texas A&M' -> 'texasam': a school name as a hashtag."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower().replace("&", ""))


def hashtags(game):
    """Up to five tags: the two schools (the ones fans follow and search), then the sport.
    Short school names get 'basketball' on the end (#dukebasketball), long ones stand alone."""
    tags = []
    for name in (game["away"], game["home"]):
        tag = hashtag(name)
        if tag:
            tags.append(tag + "basketball" if len(tag) <= 14 else tag)
    return " ".join("#" + t for t in tags + ["collegebasketball", "cbb", "collegehoops"])


def caption(game, wu, pred):
    """Ready-to-paste caption for the post, built for search: the phrase people type
    ("<away> vs <home> prediction") comes first, then the call, a question to answer in the
    comments, where to find the rest, and five specific hashtags.
    It never mentions a bet, a line or a price; if the check ever trips, the team-specific
    sentence is dropped rather than posted."""
    away, home, pick = game["away"], game["home"], game["pick"]
    pa, ph = pred or (None, None)
    lines = [f"{away} vs {home} prediction \U0001F3C0"]
    if pa is not None and ph is not None:
        win, lose = max(pa, ph), min(pa, ph)
        close = " in a toss-up" if win - lose < 3 else ""
        lines.append(f"The model has {pick} winning {win}-{lose}{close}.")
    else:
        lines.append(f"The model has {pick} winning.")
    ra, rh = (wu or {}).get("away_rank"), (wu or {}).get("home_rank")
    if ra and rh:
        lines.append(f"Model ranks: {away} #{ra}, {home} #{rh}.")
    lines.append("Who you got? \U0001F447")
    lines.append("Every game predicted before tip-off and graded after: tipoffedge.com")
    lines.append(hashtags(game))
    safe = [x for x in lines if not flagged(x)]
    return "\n".join(safe)
