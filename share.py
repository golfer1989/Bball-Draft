"""Game of the Day + the share image.

game_of_day(): the marquee matchup on the slate - the two best-rated teams facing each other,
with a close projected game breaking ties (what a sports site would put at the top).
share_image(): og.png (1200x630), the picture that shows up when someone posts the site's link
on X, iMessage, Reddit or Discord. Rebuilt every day with the game of the day on it.
Uses Pillow; the DejaVu fonts that ship with the GitHub runner, or Pillow's built-in font."""
from pathlib import Path

import config

ROOT = Path(__file__).resolve().parent
LOGO_DIR = ROOT / "data" / "raw" / "logos"


def game_of_day(rows, writeups):
    """Pick one of today's rows: lowest combined national rank, then the closest projected margin."""
    best, best_key = None, None
    for r in rows:
        wu = writeups.get(r.get("game_key"))
        if not wu:
            continue
        try:
            margin = float(r["differential"]) * config.POINTS_PER_RATING
        except (TypeError, ValueError):
            margin = 99.0
        key = (wu["away_rank"] + wu["home_rank"], margin)
        if best_key is None or key < best_key:
            best, best_key = r, key
    return best


def _font(size, bold=True):
    from PIL import ImageFont
    for name in (["DejaVuSans-Bold.ttf"] if bold else ["DejaVuSans.ttf"]):
        for d in ("/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/dejavu", "C:/Windows/Fonts"):
            p = Path(d) / name
            if p.exists():
                return ImageFont.truetype(str(p), size)
    try:
        return ImageFont.load_default(size=size)
    except TypeError:                                   # very old Pillow
        return ImageFont.load_default()


def _logo(url, size):
    """Team logo as an RGBA image, downloaded once into data/raw/logos. None if unavailable."""
    if not url:
        return None
    try:
        import requests
        from PIL import Image
        LOGO_DIR.mkdir(parents=True, exist_ok=True)
        p = LOGO_DIR / (url.rsplit("/", 1)[-1] or "x.png")
        if not p.exists() or p.stat().st_size == 0:
            r = requests.get(url, timeout=20)
            r.raise_for_status()
            p.write_bytes(r.content)
        im = Image.open(p).convert("RGBA")
        im.thumbnail((size, size))
        return im
    except Exception:                                   # noqa: BLE001 - cosmetic: fall back to initials
        return None


def share_image(path, date_label, game=None, wu=None, teams=None, pred=None, record=None):
    """Write the 1200x630 share image. game = ledger row or None (off day), wu = its write-up,
    pred = (away_pts, home_pts) projected, record = (wins, losses) to show, or None."""
    from PIL import Image, ImageDraw
    teams = teams or {}
    W, H = 1200, 630
    im = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(im)
    # thin orange rule across the top, like the site's accent
    d.rectangle((0, 0, W, 6), fill=(224, 112, 29))
    # brand
    d.ellipse((60, 52, 96, 88), fill=(224, 112, 29), outline=(0, 0, 0), width=2)
    d.text((112, 48), config.SITE_NAME.upper(), font=_font(40), fill=(243, 243, 241))
    d.text((W - 60, 60), date_label, font=_font(26, bold=False), fill=(141, 143, 151), anchor="ra")
    if not game:
        d.text((60, 250), "College basketball picks,", font=_font(64), fill=(243, 243, 241))
        d.text((60, 330), "locked before tip-off.", font=_font(64), fill=(242, 165, 65))
        d.text((60, 440), "Every pick graded. Nothing deleted.", font=_font(30, bold=False), fill=(141, 143, 151))
    else:
        d.text((60, 130), "GAME OF THE DAY", font=_font(22), fill=(242, 165, 65))
        away, home = game["away"], game["home"]
        ta, th = teams.get(str(game["away_id"])) or {}, teams.get(str(game["home_id"])) or {}
        ranks = (wu or {}).get("away_rank"), (wu or {}).get("home_rank")
        cy = 300                                          # logo centre line
        for x, name, t, rk, align in ((130, away, ta, ranks[0], "l"), (W - 130, home, th, ranks[1], "r")):
            logo = _logo(t.get("logo"), 150)
            lx = x if align == "l" else x - 150
            if logo:
                im.paste(logo, (lx + (150 - logo.width) // 2, cy - 75 + (150 - logo.height) // 2), logo)
            else:
                d.ellipse((lx, cy - 75, lx + 150, cy + 75), fill=(58, 63, 74))
                d.text((lx + 75, cy), (t.get("abbr") or name[:3]).upper()[:4], font=_font(44), fill="white", anchor="mm")
            label = f"#{rk} {name}" if rk else name
            f = _font(32)
            while d.textlength(label, font=f) > 330 and f.size > 18:
                f = _font(f.size - 2)
            cx = lx + 75                                     # centred under the logo, clear of the middle column
            d.text((cx, cy + 92), label, font=f, fill=(243, 243, 241), anchor="ma")
            d.text((cx, cy + 134), t.get("mascot") or "", font=_font(22, bold=False), fill=(141, 143, 151), anchor="ma")
        # projected score in the middle
        if pred:
            pa, ph = pred
            d.text((W // 2, cy - 20), f"{pa} - {ph}", font=_font(84), fill=(243, 243, 241), anchor="mm")
            d.text((W // 2, cy + 48), "projected final", font=_font(22, bold=False), fill=(141, 143, 151), anchor="mm")
        else:
            d.text((W // 2, cy - 20), "vs", font=_font(60), fill=(92, 94, 102), anchor="mm")
        pick = f"Model pick: {game['pick']}"
        d.text((W // 2, cy + 108), pick, font=_font(30), fill=(242, 165, 65), anchor="mm")
        line = (wu or {}).get("headline") or ""
        if line:
            d.text((W // 2, 530), line, font=_font(28, bold=False), fill=(201, 201, 196), anchor="mm")
    foot = "tipoffedge.com"
    if record and sum(record):
        foot = f"Season {record[0]}-{record[1]}  \u00b7  " + foot
    d.text((W - 60, H - 48), foot, font=_font(24, bold=False), fill=(141, 143, 151), anchor="ra")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    im.save(path, "PNG", optimize=True)
    return path
