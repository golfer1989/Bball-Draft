"""The daily clip: a 12-second vertical video (1080x1920) of the Game of the Day for TikTok,
Instagram Reels and YouTube Shorts, rebuilt by every overnight build as daily.mp4.

Scenes: brand + date -> the two teams slide in -> the projected score counts up -> the model's
reasons appear one by one -> "tipoffedge.com" end card. Frames are drawn with Pillow and piped
into ffmpeg (installed on the GitHub runner). The soundtrack is an original beat synthesised
here with numpy, so the clip is never silent and never contains anyone else's music; swap in a
trending sound inside the app when posting, which is also what gets the clip shown."""
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

import config
from share import _font, _logo

W, H, FPS = 1080, 1920, 30
BPM = 124
BLACK, INK, MUTE, AMBER, DIM = (0, 0, 0), (243, 243, 241), (141, 143, 151), (242, 165, 65), (92, 94, 102)


def ease(t):
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def _fit(d, text, size, max_w, bold=True):
    f = _font(size, bold)
    while d.textlength(text, font=f) > max_w and size > 18:
        size -= 2
        f = _font(size, bold)
    return f


def _wrap(d, text, font, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if d.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def frame(t, game, wu, teams, pred, date_label, logos):
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (W, H), BLACK)
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, W, 10), fill=(224, 112, 29))
    # header
    d.ellipse((70, 70, 126, 126), fill=(224, 112, 29), outline=BLACK, width=3)
    d.text((150, 68), config.SITE_NAME.upper(), font=_font(52), fill=INK)
    d.text((W - 70, 84), date_label, font=_font(32, bold=False), fill=MUTE, anchor="ra")
    away, home = game["away"], game["home"]
    ta, th = teams.get(str(game["away_id"])) or {}, teams.get(str(game["home_id"])) or {}
    ra, rh = (wu or {}).get("away_rank"), (wu or {}).get("home_rank")
    # scene 1: kicker
    k = ease((t - 0.2) / 0.5)
    if k > 0:
        d.text((W // 2, 300), "GAME OF THE DAY", font=_font(40), fill=tuple(int(c * k) for c in AMBER), anchor="mm")
    # scene 2: teams slide in from the sides
    s = ease((t - 0.6) / 0.7)
    cy = 640
    for side, name, tt, rk, logo in (("l", away, ta, ra, logos[0]), ("r", home, th, rh, logos[1])):
        off = int((1 - s) * 500)
        cx = (W // 4) - off if side == "l" else (3 * W // 4) + off
        if logo:
            im.paste(logo, (cx - logo.width // 2, cy - logo.height // 2), logo)
        else:
            d.ellipse((cx - 130, cy - 130, cx + 130, cy + 130), fill=(58, 63, 74))
            d.text((cx, cy), (tt.get("abbr") or name[:3]).upper()[:4], font=_font(64), fill="white", anchor="mm")
        f = _fit(d, name, 44, 440)
        d.text((cx, cy + 190), name, font=f, fill=INK, anchor="ma")
        sub = (f"#{rk} " if rk else "") + (tt.get("mascot") or "")
        d.text((cx, cy + 250), sub.strip(), font=_font(30, bold=False), fill=MUTE, anchor="ma")
    if s > 0.9:
        d.text((W // 2, cy), "vs", font=_font(56), fill=DIM, anchor="mm")
    # scene 3: projected score counts up
    c = ease((t - 1.8) / 1.2)
    if c > 0 and pred:
        pa, ph = pred
        va, vh = int(round(pa * c)), int(round(ph * c))
        home_pick = game["pick"] == home
        d.text((W // 2 - 40, 1060), str(va), font=_font(170), fill=DIM if home_pick else INK, anchor="rm")
        d.text((W // 2, 1060), "-", font=_font(100), fill=DIM, anchor="mm")
        d.text((W // 2 + 40, 1060), str(vh), font=_font(170), fill=INK if home_pick else DIM, anchor="lm")
        d.text((W // 2, 1180), "PROJECTED FINAL", font=_font(30), fill=MUTE, anchor="mm")
    p = ease((t - 3.0) / 0.5)
    if p > 0:
        d.text((W // 2, 1270), f"Model pick: {game['pick']}", font=_font(56), fill=tuple(int(x * p) for x in AMBER), anchor="mm")
    # scene 4: reasons, one every 1.6 s
    y = 1400
    for i, line in enumerate((wu or {}).get("lines", [])[:4]):
        a = ease((t - 3.8 - i * 1.6) / 0.5)
        if a <= 0:
            continue
        f = _font(34, bold=False)
        col = tuple(int(x * a) for x in (201, 201, 196))
        d.ellipse((80, y + 14, 94, y + 28), fill=tuple(int(x * a) for x in AMBER))
        for j, wl in enumerate(_wrap(d, line, f, W - 200)[:2]):
            d.text((120, y + j * 42), wl, font=f, fill=col)
        y += 42 * min(2, len(_wrap(d, line, f, W - 200))) + 22
    # end card
    e = ease((t - 10.4) / 0.6)
    if e > 0:
        ov = Image.new("RGB", (W, H), BLACK)
        im = Image.blend(im, ov, e * 0.92)
        d = ImageDraw.Draw(im)
        d.text((W // 2, H // 2 - 60), "Every pick locked before tip-off.", font=_font(44, bold=False),
               fill=tuple(int(x * e) for x in INK), anchor="mm")
        d.text((W // 2, H // 2 + 30), "tipoffedge.com", font=_font(84), fill=tuple(int(x * e) for x in AMBER), anchor="mm")
    else:
        d.text((W // 2, H - 90), "tipoffedge.com", font=_font(34, bold=False), fill=MUTE, anchor="mm")
    return im


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


def daily_video(path, date_label, game, wu, teams, pred, seconds=12.0):
    """Render daily.mp4. Returns the path, or None when ffmpeg is missing or there is no game."""
    if not game or not shutil.which("ffmpeg"):
        return None
    teams = teams or {}
    logos = [_logo((teams.get(str(game[k])) or {}).get("logo"), 260) for k in ("away_id", "home_id")]
    tmp = Path(tempfile.mkdtemp())
    wav = beat(seconds, tmp / "beat.wav")
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(FPS), "-vcodec", "png", "-i", "-",
           "-i", str(wav), "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for i in range(int(seconds * FPS)):
            im = frame(i / FPS, game, wu, teams, pred, date_label, logos)
            im.save(proc.stdin, "PNG", compress_level=1)
    finally:
        proc.stdin.close()
        proc.wait()
    shutil.rmtree(tmp, ignore_errors=True)
    return out if proc.returncode == 0 and out.exists() else None


def caption(game, wu, pred):
    """Ready-to-paste caption with hashtags for the post."""
    pa, ph = pred or ("", "")
    head = (wu or {}).get("headline", "")
    return (f"{game['away']} vs {game['home']} — model pick: {game['pick']}. Projected {pa}-{ph}. {head}.\n"
            "Every pick locked before tip-off, graded after. Full breakdown at tipoffedge.com\n"
            "#collegebasketball #cbb #ncaab #collegehoops #sportsbetting #bettingpicks #freepicks #marchmadness")

