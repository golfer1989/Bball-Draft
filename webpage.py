"""Builds index.html (Today's Picks) and results.html (Season Results).

Look: true black, a scoreboard-style predicted score in condensed numerals as the
centerpiece of every game row, team logos on a disc of each team's own color.
"""
import json
import re
from datetime import datetime, timedelta
from html import escape
from pathlib import Path
from urllib.parse import quote

import config

try:
    import teamdata                 # rankings and team pages (links, the eight inputs of a rating)
except ImportError:                 # that file was not uploaded with this one: the site builds without those pages
    teamdata = None

SLOTS = [("early", "Before 2 PM", 0, 14), ("aft", "2\u20135 PM", 14, 17),
         ("eve", "5\u20138 PM", 17, 20), ("late", "After 8 PM", 20, 24)]   # Central time

DOCS = Path(__file__).resolve().parent   # site pages live at the top of the repo

FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" '
         'href="https://fonts.gstatic.com" crossorigin><link href="https://fonts.googleapis.com/css2?'
         'family=Barlow:wght@400;500;600&family=Big+Shoulders+Display:wght@600;800;900&display=swap" rel="stylesheet">')

# The same two families served from the site itself (fonts/, six small files, 110 KB in all, the
# Latin set Google serves). A page then needs no connection to Google's two font servers before it
# can show text in its own type: the stylesheet above blocks the first paint until it arrives.
# The two files nearly every page opens with are fetched early; the rest load when first used.
FONT_FILES = (("Barlow", 400, "barlow-latin-400-normal"), ("Barlow", 500, "barlow-latin-500-normal"),
              ("Barlow", 600, "barlow-latin-600-normal"),
              ("Big Shoulders Display", 600, "big-shoulders-display-latin-600-normal"),
              ("Big Shoulders Display", 800, "big-shoulders-display-latin-800-normal"),
              ("Big Shoulders Display", 900, "big-shoulders-display-latin-900-normal"))
FONT_PRELOAD = ("barlow-latin-400-normal", "big-shoulders-display-latin-800-normal")


def _fonts(root=""):
    """The <head> lines that load the site's two typefaces: from the site's own fonts/ folder when
    the files are there, from Google Fonts otherwise (a copy of the site without that folder)."""
    if not all((DOCS / "fonts" / f"{name}.woff2").exists() for _, _, name in FONT_FILES):
        return FONTS
    faces = "".join(f"@font-face{{font-family:'{family}';font-style:normal;font-weight:{weight};font-display:swap;"
                    f"src:url({root}fonts/{name}.woff2) format('woff2')}}" for family, weight, name in FONT_FILES)
    preload = "".join(f'<link rel="preload" href="{root}fonts/{name}.woff2" as="font" type="font/woff2" crossorigin>'
                      for name in FONT_PRELOAD)
    return f"{preload}<style>{faces}</style>"

CSS = """
:root{--bg:#000;--panel:#0c0c0e;--panel2:#141418;--line:#222228;--ink:#f3f3f1;--mute:#8d8f97;--dim:#7b7d86;
--amber:#f2a541;--win:#45d48a;--loss:#ff6161;--r:14px}
*{box-sizing:border-box}[hidden]{display:none!important}html{background:var(--bg)}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 Barlow,system-ui,sans-serif;-webkit-font-smoothing:antialiased}
a{color:inherit}
.wrap{max-width:1120px;margin:0 auto;padding:0 16px}
.top{position:sticky;top:0;z-index:5;background:rgba(0,0,0,.86);backdrop-filter:blur(10px);border-bottom:1px solid var(--line)}
.top .wrap{display:flex;align-items:center;gap:28px;height:62px}
.brand{font:900 26px/1 'Big Shoulders Display',sans-serif;letter-spacing:.5px;text-decoration:none;display:flex;align-items:center;gap:10px}
.brand i{width:22px;height:22px;border-radius:50%;background:radial-gradient(circle at 35% 35%,#ffb259,#e0701d 60%,#9c4310);
 box-shadow:inset 0 0 0 1.5px rgba(0,0,0,.55);position:relative;display:inline-block}
.brand i:before,.brand i:after{content:"";position:absolute;inset:0;border-radius:50%;border:1.5px solid rgba(0,0,0,.55);clip-path:inset(0 48% 0 48%)}
.brand i:after{clip-path:inset(48% 0 48% 0)}
nav{display:flex;gap:6px;margin-left:auto}
nav a{text-decoration:none;color:var(--mute);font-weight:600;padding:8px 14px;border-radius:999px}
nav a:hover{color:var(--ink)}nav a.on{color:#000;background:var(--ink)}
nav a:focus-visible,.chip:focus-visible{outline:2px solid var(--amber);outline-offset:2px}
.hero{padding:34px 0 18px;display:flex;align-items:flex-end;justify-content:space-between;gap:20px;flex-wrap:wrap}
.hero h1{margin:0;font:800 clamp(40px,7vw,72px)/.9 'Big Shoulders Display',sans-serif;letter-spacing:.3px}
.hero p{margin:8px 0 0;color:var(--mute)}
.gotd{margin:6px 0 10px;border:1px solid var(--line);border-radius:18px;padding:18px 22px 16px;position:relative;overflow:hidden;
 background:radial-gradient(900px 300px at 15% -40%,color-mix(in srgb,var(--pc) 28%,transparent),transparent 60%),var(--panel)}
.gotd:before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--pc)}
.gh{display:flex;justify-content:space-between;align-items:baseline;gap:12px;margin-bottom:12px}
.kicker{font:800 13px Barlow,sans-serif;letter-spacing:1.6px;text-transform:uppercase;color:var(--amber)}
.gtip{color:var(--mute);font-size:13px;font-weight:600}
.gbody{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:18px}
.gt{display:flex;align-items:center;gap:16px}.gt.h{flex-direction:row-reverse;text-align:right}
.gt .disc{flex-basis:84px;width:84px;height:84px}.gt .disc img{width:62px;height:62px}.gt .disc em{font-size:26px}
.gn small{display:block;color:var(--mute);font:700 13px Barlow,sans-serif}.gn b{display:block;font:800 30px/1 'Big Shoulders Display',sans-serif;letter-spacing:.3px}
.gn span{color:var(--mute);font-size:14px}.gt.lose .gn b{color:#b9b9b4}
.gmid{text-align:center;min-width:300px}.gscore{display:flex;justify-content:center;align-items:baseline;gap:12px;font:900 64px/1 'Big Shoulders Display',sans-serif}
.gscore .l{color:var(--dim)}.gscore .dash{width:14px;height:4px;background:#2a2a32;border-radius:2px;align-self:center}
.gpick{margin:8px 0 10px;color:var(--mute);font-size:14px;display:flex;gap:8px;justify-content:center;align-items:center}.gpick b{color:var(--ink)}
.gmid .line{justify-content:center}
.greasons{margin:14px 0 0;padding:12px 0 0 18px;border-top:1px solid #1a1a20;color:#c9c9c4;font-size:14px;line-height:1.5;columns:2;column-gap:36px}
.greasons li{break-inside:avoid;margin:2px 0}
@media (max-width:760px){.gbody{grid-template-columns:1fr 1fr;grid-template-areas:"a h" "m m";gap:10px}.gt.a{grid-area:a}.gt.h{grid-area:h}.gmid{grid-area:m;min-width:0}
 .gt{flex-direction:column;text-align:center;gap:8px}.gt.h{flex-direction:column}.gn b{font-size:22px}.gt .disc{flex-basis:64px;width:64px;height:64px}.gt .disc img{width:46px;height:46px}
 .gscore{font-size:52px}.greasons{columns:1}}
.clip{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap;margin-top:14px;padding-top:12px;border-top:1px solid #1a1a20}
.clip textarea{width:100%;margin-top:10px;background:var(--panel2);color:var(--ink);border:1px solid var(--line);border-radius:10px;padding:10px;font:14px/1.4 Barlow,sans-serif}
.clip b{display:block;font-size:14px}.clip span{color:var(--mute);font-size:13px}.cb{display:flex;gap:8px}
.btn{display:inline-block;background:var(--amber);color:#1a1000;font:700 14px Barlow,sans-serif;padding:9px 16px;border-radius:999px;text-decoration:none;border:0;cursor:pointer}
.btn.ghost{background:transparent;color:var(--ink);border:1px solid var(--line)}.btn.ghost.done{border-color:var(--win);color:var(--win)}
.crumb{margin:0 0 8px;font-size:13px;color:var(--mute)}.crumb a{color:var(--mute);text-decoration:none}.crumb a:hover{color:var(--ink)}
.games.one{margin-top:4px}.gl{grid-column:1/-1;font-size:13px;color:var(--amber);text-decoration:none;font-weight:700;margin:2px 0 -4px;padding-top:8px;border-top:1px solid #1a1a20}
.why li.more{list-style:none;margin-left:-18px;margin-top:8px}.why li.more a{color:var(--amber);font-weight:700;text-decoration:none}
.verdict{margin:14px 0 4px;padding:12px 16px;border-radius:12px;font-size:15px;color:#c9c9c4}.verdict b{color:var(--ink)}
.verdict.W{background:rgba(69,212,138,.1);border:1px solid rgba(69,212,138,.35)}.verdict.L{background:rgba(255,97,97,.08);border:1px solid rgba(255,97,97,.3)}
.greasons.one{columns:1;border:0;padding-top:0;font-size:15px;max-width:760px}
.confsel{display:flex;align-items:center;gap:10px;margin:14px 0 2px;color:var(--mute);font-size:13px;font-weight:600}
.confsel select{background:var(--panel);color:var(--ink);border:1px solid var(--line);border-radius:999px;padding:7px 34px 7px 14px;font:600 14px Barlow,sans-serif;
 appearance:none;-webkit-appearance:none;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='8'%3E%3Cpath d='M1 1l5 5 5-5' fill='none' stroke='%238d8f97' stroke-width='2'/%3E%3C/svg%3E");
 background-repeat:no-repeat;background-position:right 13px center}
.fav{background:none;border:0;color:var(--dim);font-size:17px;line-height:1;padding:0 4px;margin-left:4px;cursor:pointer;vertical-align:1px}
.fav:hover,.fav.on{color:var(--amber)}.g.is-fav{order:-1;border-color:rgba(242,165,65,.35)}
.favchip.has{color:var(--amber)}.favchip .n{min-width:1.3em}
.betpill{background:rgba(69,212,138,.12);border-color:rgba(69,212,138,.45);color:var(--ink)}.betpill i{color:var(--win)}
.ln.betpill b{background:rgba(69,212,138,.2);color:var(--win)}
.betpill.strong{box-shadow:0 0 14px -4px rgba(69,212,138,.9)}
.gbet{display:flex;align-items:baseline;justify-content:center;gap:10px;flex-wrap:wrap;margin:4px 0 10px;padding:10px 14px;border-radius:12px;
 background:rgba(69,212,138,.1);border:1px solid rgba(69,212,138,.4)}
.gbet>span{font:800 11px Barlow,sans-serif;letter-spacing:1.2px;text-transform:uppercase;color:var(--win)}
.gbet>b{font:800 22px/1 'Big Shoulders Display',sans-serif}.gbet>small{color:var(--mute);font-size:12px;flex-basis:100%;text-align:center}
.gbet.none{background:#111115;border-color:var(--line)}.gbet.none>span{color:var(--mute)}.gbet.none>b{color:var(--mute);font-size:18px}
.gbet.top{padding:14px 16px 12px;box-shadow:0 0 26px -12px rgba(69,212,138,.9)}.gbet.top>b{font-size:30px}
.gbet>b i{font-style:normal;color:var(--mute);font-size:.72em;margin-left:4px}
.gst{flex-basis:100%;display:flex;justify-content:center;align-items:center;gap:8px;margin-top:8px;padding-top:9px;border-top:1px solid rgba(255,255,255,.09);
 color:var(--mute);font:600 13px Barlow,sans-serif}
.gst b{font:800 22px/1 'Big Shoulders Display',sans-serif;color:var(--ink)}.gst em{font-style:normal}
.gbet.L{background:rgba(255,97,97,.07);border-color:rgba(255,97,97,.35);box-shadow:none}.gbet.L>span{color:var(--loss)}
.gbet.P{background:#111115;border-color:var(--line);box-shadow:none}.gbet.P>span{color:var(--mute)}
.gmore{display:inline-block;margin-top:12px;color:var(--amber);font-size:13px;font-weight:700;text-decoration:none}.gmore:hover{text-decoration:underline}
.rk{font:700 12px Barlow,sans-serif;font-style:normal;color:var(--mute);margin-left:6px;vertical-align:2px}
.why{grid-column:1/-1;margin:2px 0 -4px;border-top:1px solid #1a1a20;padding-top:8px}
.why summary{cursor:pointer;list-style:none;display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;color:var(--mute);font-size:13px}
.why summary::-webkit-details-marker{display:none}
.why summary span{font-weight:700;color:var(--amber);display:inline-flex;align-items:center;gap:7px}
.why summary span:before{content:"";width:0;height:0;border:5px solid transparent;border-left:7px solid var(--amber);border-right:0;transition:transform .15s}
.why[open] summary span:before{transform:rotate(90deg)}.why summary em{font-style:normal;color:var(--ink);font-weight:600}
.why ul{margin:10px 0 6px;padding-left:18px;color:#c9c9c4;font-size:14px;line-height:1.5;max-width:760px}.why li{margin:3px 0}
.legend{margin:4px 0 14px;color:var(--mute);font-size:13px}.legend summary{cursor:pointer;font-weight:600}
.lg{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:10px 24px;margin-top:12px;color:#c9c9c4;font-size:13px;line-height:1.45}
.lg b{display:block;color:var(--ink);margin-bottom:2px}.lg .flag{vertical-align:1px}.lg .ln{vertical-align:middle}
.stale{margin:18px 0 -10px;padding:12px 16px;border:1px solid #4a3618;border-radius:12px;background:rgba(242,165,65,.08);color:var(--mute);font-size:14px}
.stale b{color:var(--amber)}
.donelink{color:var(--amber);text-decoration:none;font-weight:600;white-space:nowrap}.donelink:hover{text-decoration:underline}
.stats{display:flex;gap:28px;flex-wrap:wrap}
.stat b{display:block;font:800 34px/1 'Big Shoulders Display',sans-serif}
.stat span{color:var(--mute);font-size:13px}
.stat.am b{color:var(--amber)}.stat.up b{color:#a78bfa}
.bar{display:flex;gap:8px;margin:6px 0 16px;flex-wrap:wrap}
.chip{border:1px solid var(--line);background:var(--panel);color:var(--mute);font:600 14px Barlow,sans-serif;padding:7px 14px;border-radius:999px;cursor:pointer}
.chip.on{color:var(--ink);border-color:#3a3a42;background:var(--panel2)}
.games{display:flex;flex-direction:column;gap:10px;padding-bottom:48px}
.g{position:relative;display:grid;grid-template-columns:70px 1fr 310px 1fr 190px;align-items:center;gap:14px;
 background:var(--panel);border:1px solid var(--line);border-radius:var(--r);padding:14px 18px;overflow:hidden}
.g:before{content:"";position:absolute;inset:0 auto 0 0;width:3px;background:var(--pc)}
.g.strong{border-color:rgba(242,165,65,.45);box-shadow:0 0 0 1px rgba(242,165,65,.15) inset}
.time{color:var(--mute);font-weight:600;font-size:14px;line-height:1.2}
.time small{display:block;margin-top:4px;color:var(--dim);font-size:12px;font-weight:500}
.team{display:flex;align-items:center;gap:12px;min-width:0}
.team.h{flex-direction:row-reverse;text-align:right}
.disc{flex:0 0 52px;width:52px;height:52px;border-radius:50%;display:grid;place-items:center;
 background:radial-gradient(circle at 50% 40%,color-mix(in srgb,var(--c) 70%,#fff 0%),color-mix(in srgb,var(--c) 55%,#000));
 box-shadow:0 0 0 2px color-mix(in srgb,var(--c) 60%,#000),0 6px 22px -8px var(--c)}
.disc img{width:38px;height:38px;object-fit:contain;filter:drop-shadow(0 1px 1px rgba(0,0,0,.6))}
.disc em{font:800 17px/1 'Big Shoulders Display',sans-serif;font-style:normal;color:#fff}
.nm{min-width:0}.nm b{display:block;font-weight:600;font-size:17px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.nm span{color:var(--mute);font-size:13px}
.team.lose .nm b{color:#c9cacd}
.score{display:flex;align-items:center;justify-content:center;gap:10px;font:800 46px/1 'Big Shoulders Display',sans-serif;font-variant-numeric:tabular-nums}
.score .w{color:var(--ink)}.score .l{color:var(--dim)}
.score .dash{width:10px;height:3px;background:var(--dim);border-radius:2px}
.score small{display:block}
.mid{display:flex;flex-direction:column;align-items:center;gap:9px;min-width:0}
.line{display:flex;gap:6px;justify-content:center;flex-wrap:wrap}
.ln{font:600 12.5px/1 Barlow,sans-serif;color:var(--ink);background:var(--panel2);border:1px solid var(--line);
 border-radius:999px;padding:5px 10px;white-space:nowrap;font-variant-numeric:tabular-nums}
.ln i{font-style:normal;color:var(--mute);font-weight:500;margin-right:6px}
.flag.up{background:#a78bfa;color:#0b0820}
.flag.ultra{background:linear-gradient(90deg,#ff5f6d,#f2a541);color:#16070a;box-shadow:0 0 16px -4px rgba(255,95,109,.8)}
.g.upset{border-color:rgba(167,139,250,.45)}
.g.ultra{border-color:rgba(255,95,109,.6);box-shadow:0 0 0 1px rgba(255,95,109,.2) inset,0 0 24px -12px rgba(255,95,109,.7)}
.ln.hot{border-color:rgba(242,165,65,.7);background:rgba(242,165,65,.1);box-shadow:0 0 14px -4px rgba(242,165,65,.55)}
.ln b{margin-left:7px;font-weight:700;color:#000;background:var(--amber);border-radius:999px;padding:2px 7px;font-size:11.5px}
.ln.won b{background:var(--win)}.ln.lost b{background:var(--loss);color:#fff}
.ln.won{border-color:rgba(69,212,138,.6);background:rgba(69,212,138,.08);box-shadow:none}
.ln.lost{border-color:rgba(255,97,97,.5);background:rgba(255,97,97,.07);box-shadow:none}
.side{display:flex;flex-direction:column;gap:6px;align-items:flex-end;text-align:right}
.pick{font-weight:600;font-size:14px;display:flex;gap:8px;align-items:center}
.flag{font:700 12px Barlow,sans-serif;color:#000;background:var(--amber);padding:2px 8px;border-radius:999px}
.meter{width:150px;height:6px;border-radius:6px;background:#1d1d22;overflow:hidden;display:flex}
.meter i{display:block;height:100%;border-radius:6px;background:var(--pc)}
.meter.r{justify-content:flex-end}
.meta{color:var(--mute);font-size:13px}
.meta b{color:var(--ink);font-weight:600}
.res{font:800 13px Barlow,sans-serif;padding:2px 9px;border-radius:999px}
.res.W{background:rgba(69,212,138,.14);color:var(--win)}.res.L{background:rgba(255,97,97,.14);color:var(--loss)}
.final{color:var(--mute);font-size:13px;text-align:center;margin-top:6px;font-weight:600}
.day{display:flex;align-items:baseline;gap:12px;margin:26px 0 10px}
.day h2{margin:0;font:800 26px/1 'Big Shoulders Display',sans-serif}
.day span{color:var(--mute);font-weight:600}
.bar.slots{margin-bottom:6px}
.chip .n{color:var(--dim);margin-left:6px;font-weight:500}
.chip.on .n{color:var(--mute)}
.chip.livechip.has{color:#ff8a8a;border-color:rgba(255,59,59,.45)}
.sc{display:flex;flex-direction:column;align-items:center;gap:6px}
.lv{display:flex;flex-direction:column;align-items:center;gap:6px}
.lstat{display:flex;gap:8px;align-items:center;font:600 13px Barlow,sans-serif;color:var(--mute)}
.livetag{display:inline-flex;align-items:center;gap:5px;background:#ff3b3b;color:#fff;font:800 11px/1 Barlow,sans-serif;
 letter-spacing:.06em;padding:4px 7px 4px 6px;border-radius:5px}
.livetag:before{content:"";width:6px;height:6px;border-radius:50%;background:#fff}
@media (prefers-reduced-motion:no-preference){.livetag:before{animation:pulse 1.4s ease-in-out infinite}@keyframes pulse{50%{opacity:.25}}}
.fintag{background:var(--panel2);border:1px solid var(--line);color:var(--ink);font:700 11px/1 Barlow,sans-serif;padding:4px 7px;border-radius:5px}
.g.is-live{border-color:rgba(255,59,59,.55)}
.g.is-live .pred .score,.g.is-done .pred .score{font-size:17px;gap:6px;color:var(--mute)}
.g.is-live .pred .score span,.g.is-done .pred .score span{color:var(--mute)}
.g.is-live .pred .score .dash,.g.is-done .pred .score .dash{width:6px;height:2px}
.g.is-live .pred:before,.g.is-done .pred:before{content:"Model";font:600 11px Barlow,sans-serif;color:var(--dim);margin-right:6px}
.g.is-live .pred,.g.is-done .pred{display:flex;align-items:center}
.g.is-done{opacity:.82}
.okx{font:800 12px Barlow,sans-serif;padding:3px 8px;border-radius:999px}
.okx.W{background:rgba(69,212,138,.15);color:var(--win)}.okx.L{background:rgba(255,97,97,.15);color:var(--loss)}
.empty{border:1px dashed var(--line);border-radius:var(--r);padding:56px 20px;text-align:center;color:var(--mute)}
/* early look at the next day (Today page, once the day's last game has tipped off) */
.alldone{margin:6px 0 4px;padding:12px 16px;border:1px solid var(--line);border-radius:12px;background:var(--panel);color:var(--mute);font-size:14px}
.alldone b{color:var(--ink)}
.early{margin:26px 0 48px;scroll-margin-top:76px}.games+.early{margin-top:-14px}
.early h2{margin:6px 0 0;font:800 clamp(30px,5vw,44px)/.95 'Big Shoulders Display',sans-serif;letter-spacing:.3px}
.early p{margin:8px 0 14px;color:var(--mute);font-size:14px;max-width:760px}.early p b{color:var(--ink);font-weight:600}
.elist{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:8px}
.eg{position:relative;display:grid;grid-template-columns:68px minmax(0,1fr);align-items:center;gap:10px;background:var(--panel);
 border:1px solid var(--line);border-radius:12px;padding:9px 14px 9px 16px;overflow:hidden}
.eg:before{content:"";position:absolute;inset:0 auto 0 0;width:3px;background:var(--pc)}
.etime{color:var(--mute);font-weight:600;font-size:13px;line-height:1.25}
.etime small{display:block;margin-top:2px;color:var(--dim);font-size:11px;font-weight:500}
.et{display:flex;justify-content:space-between;align-items:baseline;gap:10px;color:#a3a4ab}
.et span{min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-weight:600;font-size:15px}
.et b{font:800 22px/1.2 'Big Shoulders Display',sans-serif;font-variant-numeric:tabular-nums;color:var(--dim)}
.et.w,.et.w b{color:var(--ink)}
.empty b{display:block;color:var(--ink);font:800 28px/1.1 'Big Shoulders Display',sans-serif;margin-bottom:6px}
footer{color:var(--dim);font-size:12px;padding:0 0 30px}
footer .links{display:flex;flex-wrap:wrap;gap:6px 18px;margin-top:8px}footer a{color:var(--mute)}
.ad{margin:28px 0 8px;min-height:90px}
.prose{max-width:720px;line-height:1.6;color:#c9c9c4}.prose h2{font:800 24px/1 'Big Shoulders Display',sans-serif;color:var(--ink);margin:30px 0 8px}
.prose p{margin:0 0 14px}.prose a{color:var(--amber)}
@media (max-width:860px){
 .g{grid-template-columns:1fr auto 1fr;grid-template-areas:"time time time" "a s h" "line line line" "side side side";row-gap:10px;padding:14px}
 .mid{display:contents}.mid .score,.mid>div:first-child{grid-area:s}.line{grid-area:line}
 .time{grid-area:time}.time br{display:none}
 .team.a{grid-area:a;flex-direction:column;text-align:center;gap:6px}.team.h{grid-area:h;flex-direction:column;text-align:center;gap:6px}
 .score{font-size:38px}.side{grid-area:side;flex-direction:row;justify-content:space-between;align-items:center;flex-wrap:wrap}
 .nm b{font-size:15px;white-space:normal}.disc{flex-basis:46px;width:46px;height:46px}.disc img{width:32px;height:32px}
 .meter{width:90px}.stats{gap:18px}
}
/* best bets */
.sect{display:flex;align-items:baseline;gap:12px;margin:26px 0 12px}
.sect h2{margin:0;font:800 28px/1 'Big Shoulders Display',sans-serif;letter-spacing:.3px}
.sect span{color:var(--mute);font-size:14px}
.singles{display:grid;gap:10px}
.bet{display:grid;grid-template-columns:34px 52px 1fr 90px 150px;align-items:center;gap:14px;background:var(--panel);
 border:1px solid var(--line);border-radius:var(--r);padding:14px 18px}
.bet .rk{font:900 30px/1 'Big Shoulders Display',sans-serif;color:var(--dim);text-align:center}
.bet:first-child .rk{color:var(--amber)}
.bl b{display:block;font:700 19px/1.2 Barlow,sans-serif}
.bl small{color:var(--mute);font-size:13px}
.kind{justify-self:start;font:700 11px/1 Barlow,sans-serif;letter-spacing:.8px;text-transform:uppercase;color:var(--mute);
 border:1px solid var(--line);border-radius:999px;padding:6px 9px;background:var(--panel2)}
.kind.ML{color:#7dd3fc;border-color:#1e3a4a}.kind.Spread{color:var(--amber);border-color:#4a3618}.kind.Total{color:#a78bfa;border-color:#352a55}
.pc{text-align:right}.pc b{font:800 26px/1 'Big Shoulders Display',sans-serif}
.pc small{display:block;color:var(--mute);font-size:12px;margin-top:3px}
.pc .bar2{height:5px;border-radius:9px;background:#1c1c22;margin-top:6px;overflow:hidden}
.pc .bar2 i{display:block;height:100%;background:linear-gradient(90deg,#3b82f6,var(--win));border-radius:9px}
.res.big{font:800 20px/1 'Big Shoulders Display',sans-serif;padding:8px 14px;border-radius:10px}
.res.P{background:#2a2a32;color:var(--mute)}
.bet.W{border-color:rgba(69,212,138,.45)}.bet.L{border-color:rgba(255,97,97,.35);opacity:.8}
.bet.is-live{border-color:rgba(255,59,59,.55)}
.pc .lvrow{display:flex;justify-content:flex-end;align-items:center;gap:6px;margin-top:6px}
.pc .res.big+small{margin-top:9px}
.stat.win b{color:var(--win)}.stat.loss b{color:var(--loss)}
.singles.past .bet{padding:10px 18px}.singles.past .rk{font-size:22px}.singles.past .bl b{font-size:16px}
.disc.ou{--c:#26262e}.disc.ou em{font-size:20px}
.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;align-items:start}
.card{background:var(--panel);border:1px solid var(--line);border-radius:var(--r);overflow:hidden}
.card header{padding:18px 18px 14px;border-bottom:1px solid var(--line);
 background:linear-gradient(160deg,rgba(242,165,65,.13),transparent 60%)}
.card h3{margin:0;color:var(--mute);font:700 13px/1 Barlow,sans-serif;letter-spacing:1px;text-transform:uppercase}
.card .od{font:900 46px/1 'Big Shoulders Display',sans-serif;margin:8px 0 6px;color:var(--amber)}
.card .cs{color:var(--mute);font-size:14px}.card .cs b{color:var(--ink)}
.card ol{list-style:none;margin:0;padding:6px 0}
.card li{display:grid;grid-template-columns:34px 1fr auto;gap:10px;align-items:center;padding:9px 18px}
.card li+li{border-top:1px solid #18181d}
.card li .disc{flex-basis:34px;width:34px;height:34px}.card li .disc img{width:24px;height:24px}.card li .disc em{font-size:13px}
.card li b{display:block;font-weight:700;font-size:15px;line-height:1.2}.card li small{color:var(--mute);font-size:12px}
.card li .p{font:800 18px/1 'Big Shoulders Display',sans-serif;color:var(--ink)}
.card.none{padding:26px 18px;color:var(--mute)}.card.none h3{margin-bottom:10px}
.note{color:var(--dim);font-size:13px;margin:22px 0 0;max-width:760px}
@media (max-width:900px){.cards{grid-template-columns:1fr}}
@media (max-width:700px){
 .bet{grid-template-columns:26px 42px 1fr auto;gap:10px;padding:12px 14px}
 .bet .disc{flex-basis:42px;width:42px;height:42px}.bet .disc img{width:30px;height:30px}
 .bet .kind,.pc .mc{display:none}.bet .rk{font-size:24px}.bl b{font-size:16px}.pc b{font-size:22px}.pc{min-width:70px}
 .pc .lvrow{flex-direction:column;align-items:flex-end;gap:4px}
 /* phones: the name on one line, the tabs on the next; scrolling down leaves only the tabs stuck to the top */
 .top{top:-42px}.top .wrap{height:auto;flex-wrap:wrap;gap:0}.brand{font-size:22px;height:42px}.brand i{width:18px;height:18px}
 nav{margin-left:0;width:100%;gap:2px;justify-content:space-between;padding:0 0 8px;overflow-x:auto}
 nav a{padding:7px 9px;font-size:14px;white-space:nowrap}
}
@media (max-width:379px){nav a{padding:7px 6px;font-size:13px}}
/* rankings, team pages, method page */
.prose.wide{max-width:860px}.prose h3{font:700 17px/1.3 Barlow,sans-serif;color:var(--ink);margin:20px 0 6px}
.prose ol{margin:0 0 14px;padding-left:20px}.prose li{margin:4px 0}.prose b{color:var(--ink);font-weight:600}
.rkbar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:16px 0 12px;scroll-margin-top:76px}
.rkbar select,.rkbar input{background:var(--panel);color:var(--ink);border:1px solid var(--line);border-radius:999px;padding:7px 14px;
 font:600 14px Barlow,sans-serif;min-width:0}
.rkbar input{flex:1 1 150px;max-width:240px}.rkbar input::placeholder{color:var(--dim)}
.rkbar select:focus-visible,.rkbar input:focus-visible,.rt th button:focus-visible{outline:2px solid var(--amber);outline-offset:2px}
.rkn{color:var(--dim);font-size:13px;margin-left:auto}
.tw{overflow-x:auto;margin:0 -16px;padding:0 16px}
table.rt{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
.rt th{padding:0;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap;font-weight:400}
.rt th button,.rt.ct th,.rt.ft th,.rt.sched th{background:none;border:0;color:var(--mute);font:700 12px Barlow,sans-serif;letter-spacing:.8px;
 text-transform:uppercase;padding:10px 8px}
.rt th button{cursor:pointer}.rt th i{font-style:normal}
.rt th button:hover,.rt th[aria-sort=ascending] button,.rt th[aria-sort=descending] button{color:var(--ink)}
.rt th[aria-sort=ascending] button:after{content:" ▲";font-size:9px;color:var(--amber)}
.rt th[aria-sort=descending] button:after{content:" ▼";font-size:9px;color:var(--amber)}
.rt td{padding:8px;border-bottom:1px solid #15151a;text-align:right;color:#c9c9c4}
.rt .t{text-align:left}.rt th.n,.rt td.n{text-align:left}
.rt td.n{font:800 20px/1 'Big Shoulders Display',sans-serif;color:var(--mute);width:46px}
.rt td.pts{font:800 20px/1 'Big Shoulders Display',sans-serif;color:var(--ink)}
.rt td.pts small{font:400 12px/1.2 Barlow,sans-serif;margin-top:4px;white-space:nowrap}
.rt tbody tr:hover td{background:var(--panel)}
.rt a{text-decoration:none;font-weight:700;color:var(--ink)}.rt a:hover{color:var(--amber)}
.rt small{display:block;color:var(--mute);font-size:12px;font-weight:400}.rt .rec{display:none}
.tm{display:flex;align-items:center;gap:10px;min-width:0}.tm>div:nth-child(2){min-width:0;flex:1}
.rt .disc{flex-basis:32px;width:32px;height:32px}.rt .disc img{width:23px;height:23px}.rt .disc em{font-size:11px}
.rt .up{color:var(--win)}.rt .dn{color:var(--loss)}
.nm a.tl{color:inherit;text-decoration:none}.nm a.tl:hover{color:var(--amber)}
.rt.narrow{max-width:720px}.rt.ft td b{color:var(--ink)}.rt td.rkc,.rt td.nw{white-space:nowrap}.prose .tw{margin-bottom:18px}
.rkbar2{display:inline-block;vertical-align:middle;width:56px;height:5px;border-radius:3px;background:#1d1d23;margin-right:10px;position:relative;overflow:hidden}
.rkbar2:before{content:"";position:absolute;inset:0 auto 0 0;width:var(--p);background:var(--amber);border-radius:3px}
.two{display:grid;grid-template-columns:1fr 1fr;gap:6px 34px}
.thero{display:flex;align-items:center;gap:18px}.thero h1{font-size:clamp(34px,6.4vw,64px)}
.thero .disc{flex-basis:84px;width:84px;height:84px}.thero .disc img{width:62px;height:62px}.thero .disc em{font-size:26px}
.thero .fav{font-size:20px;margin-left:8px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(132px,1fr));gap:10px;margin:4px 0 18px}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px 16px}
.tile b{display:block;font:800 34px/1 'Big Shoulders Display',sans-serif}.tile.am b{color:var(--amber)}
.tile span{display:block;margin-top:6px;color:var(--mute);font-size:13px}
.rt.sched{max-width:860px}.rt.sched td.d{white-space:nowrap;color:var(--mute);width:112px}
.rt.sched td.rs{white-space:nowrap}.rt.sched td.rs b{font-weight:800}.rt.sched td.m a{font-weight:600}.ml{display:none}
.soon{font:700 11px Barlow,sans-serif;letter-spacing:.8px;text-transform:uppercase;color:var(--amber);margin-right:6px}
.dimx{color:var(--dim)}
.mates{display:flex;flex-wrap:wrap;gap:8px;margin:0}
.mates a{text-decoration:none;border:1px solid var(--line);background:var(--panel);border-radius:999px;padding:6px 12px;font-weight:600;font-size:14px}
.mates a i{font-style:normal;color:var(--mute);font-size:12px;margin-right:4px}.mates a.me{border-color:var(--amber);color:var(--amber)}
.mates a:hover{border-color:#3a3a44}
.ex{margin:18px 0 22px;border:1px solid var(--line);border-left:4px solid var(--amber);border-radius:14px;background:var(--panel);padding:16px 20px 8px}
.ex h3{margin:6px 0 10px;font:800 24px/1.05 'Big Shoulders Display',sans-serif;color:var(--ink)}
.tale td:first-child,.tale th:first-child{text-align:right;width:35%}.tale td:last-child,.tale th:last-child{text-align:left;width:35%}
.tale td.k,.tale th.k{text-align:center;color:var(--mute);font-size:13px;width:30%}.tale td.best{color:var(--ink);font-weight:700}
.tale th{white-space:normal;padding:10px 8px;font:800 20px/1 'Big Shoulders Display',sans-serif;letter-spacing:.3px;color:var(--ink)}
.tale th a{color:inherit;text-decoration:none}.tale th a:hover{color:var(--amber)}
@media (max-width:760px){.two{grid-template-columns:1fr}}
@media (max-width:700px){
 .sect.st{display:block}.sect.st span{display:block;margin-top:5px}
 .rt .c-rec,.rt .c-sos,.rt .c-mv{display:none}.rt .rec{display:inline}.rt th i{display:none}
 .rt td,.rt th button,.rt.ct th,.rt.ft th{padding-left:5px;padding-right:5px}
 .rt td.n{width:26px;font-size:17px}.rt td.pts{font-size:18px}.rt .tm{gap:8px}.rt .tm a{font-size:15px}
 .rt .disc{flex-basis:28px;width:28px;height:28px}.rt .disc img{width:20px;height:20px}.rt .disc em{font-size:10px}
 .rt .fav{padding:0 2px;margin-left:0}
 .rkn{width:100%;margin:0}.rkbar input{max-width:none}.rkbar2{width:30px;margin-right:6px}
 .thero{gap:12px}.thero .disc{flex-basis:60px;width:60px;height:60px}.thero .disc img{width:44px;height:44px}.thero .disc em{font-size:19px}
 .tiles{grid-template-columns:repeat(3,1fr)}.tile{padding:10px 12px}.tile b{font-size:26px}.tile span{font-size:12px}
 /* a team's games: two lines each, the date down the left, the model's call under the opponent */
 .rt.sched,.rt.sched tbody{display:block}.rt.sched thead{display:none}
 .rt.sched tr{display:grid;grid-template-columns:76px 1fr auto;gap:3px 10px;padding:10px 0;border-bottom:1px solid #15151a}
 .rt.sched td{border:0;padding:0;text-align:left}.rt.sched td.d{grid-row:1/3;width:auto;font-size:13px}
 .rt.sched td.rs{text-align:right}.rt.sched td.m{grid-column:2/4;font-size:13px;color:var(--mute)}
 .rt.sched td.m a{color:#c9c9c4}.rt.sched tbody tr:hover td{background:none}.ml{display:inline}
 .tale th{font-size:17px}.tale td.k{font-size:12px}
}
@media (max-width:379px){.rt .tm .fav{display:none}}
/* a meter list: one row per item with its name, a bar for the share and the figure (weeks on Results, margins on the method page) */
.mlist{display:grid;gap:2px;margin:8px 0 6px}
.mrow{display:grid;grid-template-columns:minmax(150px,1fr) 2fr minmax(118px,auto);gap:6px 16px;align-items:center;padding:10px 12px;border-radius:10px;color:var(--ink);text-decoration:none}
a.mrow:hover{background:var(--panel)}a.mrow:focus-visible{outline:2px solid var(--amber);outline-offset:2px}
.mrow.cur{background:var(--panel)}.mrow .mn{font-weight:600}.mrow .mn small{color:var(--mute);font-weight:500;font-size:12px;margin-left:8px}
.mrow .mb{height:8px;border-radius:4px;background:rgba(242,165,65,.16);overflow:hidden}.mrow .mb i{display:block;height:100%;border-radius:4px;background:var(--amber)}
.mrow .mv{font-variant-numeric:tabular-nums;color:var(--mute);font-size:13px;white-space:nowrap;text-align:right}.mrow .mv b{color:var(--ink);font-size:15px;margin-right:8px}
a.mrow .mn:after{content:"\\203A";color:var(--dim);margin-left:8px}
.pager{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;margin:26px 0 4px}
.pager a{color:var(--ink);text-decoration:none;font-weight:600;font-size:14px;padding:9px 16px;border:1px solid var(--line);border-radius:999px}.pager a:hover{border-color:var(--mute)}
@media (max-width:560px){.mrow{grid-template-columns:1fr auto;padding:10px 4px}.mrow .mb{grid-column:1/-1;grid-row:2}}
@media (prefers-reduced-motion:no-preference){.g{animation:in .35s ease-out both}@keyframes in{from{opacity:0;transform:translateY(6px)}}}
"""

JS = """<script>
(()=>{
const games=[...document.querySelectorAll('.g')];
const box=document.querySelector('[data-date]');
const gd=document.querySelector('.gotd[data-ea]'); // Game of the day: the day's top bet, followed live below
// ---- My teams: favorites kept in this browser, no account ----
const KEY='te_favs';let favs=new Set();
try{favs=new Set(JSON.parse(localStorage.getItem(KEY)||'[]'))}catch(e){}
function saveFavs(){try{localStorage.setItem(KEY,JSON.stringify([...favs]))}catch(e){}}
function paintFavs(){
 document.querySelectorAll('.fav').forEach(b=>{const on=favs.has(b.dataset.tid);b.textContent=on?'\u2605':'\u2606';b.classList.toggle('on',on);b.setAttribute('aria-pressed',on)});
 let n=0,w=0,l=0;
 games.forEach(g=>{const mine=(g.dataset.teams||'').split('|').some(t=>favs.has(t));g.classList.toggle('fav',mine);g.classList.toggle('is-fav',mine);
  if(mine){n++;if(g.dataset.res==='W')w++;if(g.dataset.res==='L')l++}});
 const c=document.querySelector('.favchip .n');if(c)c.textContent=(w+l)?`${w}-${l}`:n;
 const fc=document.querySelector('.favchip');if(fc)fc.classList.toggle('has',favs.size>0);
}
document.addEventListener('click',e=>{const b=e.target.closest('.fav');if(!b)return;e.preventDefault();e.stopPropagation();
 favs.has(b.dataset.tid)?favs.delete(b.dataset.tid):favs.add(b.dataset.tid);saveFavs();paintFavs();apply()});
paintFavs();
let F='all',S='all',C='';
function conf(g){return !C||(C==='top25'?g.dataset.top25==='1':(g.dataset.conf||'').split('|').includes(C))}
function apply(){
 games.forEach(g=>{const t=F==='all'||g.classList.contains(F);
  const s=S==='all'||(S==='live'?g.classList.contains('is-live'):g.dataset.slot===S);g.hidden=!(t&&s&&conf(g))});
 document.querySelectorAll('.day').forEach(d=>{const n=d.nextElementSibling;const none=n&&[...n.children].every(g=>g.hidden);d.hidden=none;if(n)n.hidden=none});
 const any=games.some(g=>!g.hidden);
 document.querySelectorAll('[data-empty]').forEach(m=>{const k=m.dataset.empty;
  m.hidden=any||!((k==='conf'&&C)||(!C&&((k===F&&S==='all')||(k==='slot'&&S!=='all'&&S!=='live'&&F==='all')||(k==='live'&&S==='live')||(k==='mix'&&F!=='all'&&S!=='all'))))});
}
function pick(sel,attr,set){document.querySelectorAll(sel).forEach(c=>c.addEventListener('click',()=>{
 document.querySelectorAll(sel).forEach(x=>x.classList.toggle('on',x===c));set(c.dataset[attr]);apply()}))}
pick('.chip[data-f]','f',v=>F=v);pick('.chip[data-s]','s',v=>S=v);
document.querySelectorAll('[data-copy]').forEach(b=>b.addEventListener('click',()=>{
 const ta=b.closest('.clip').querySelector('textarea');const ok=()=>{b.textContent='Copied';b.classList.add('done')};
 const legacy=()=>{ta.hidden=false;ta.readOnly=true;ta.focus();ta.setSelectionRange(0,ta.value.length);
  let d=false;try{d=document.execCommand('copy')}catch(e){}
  if(d){ta.hidden=true;ok()}else{b.textContent='Select and copy the text below';ta.style.height='9em'}};
 if(navigator.clipboard&&window.isSecureContext){navigator.clipboard.writeText(ta.value).then(ok,legacy)}else legacy()}));
const sel=document.getElementById('conf');if(sel)sel.addEventListener('change',()=>{C=sel.value;
 if(C){S='all';document.querySelectorAll('.chip[data-s]').forEach(x=>x.classList.toggle('on',x.dataset.s==='all'))}apply()});
const etDay=(back=0)=>new Date(Date.now()-back*36e5).toLocaleDateString('en-CA',{timeZone:'America/New_York'});
const isToday=box&&box.dataset.date===etDay();
// After midnight Eastern the night's late games are still this page's games: the live scores keep
// running, and the "earlier day" note holds off, until 5 AM Eastern when the next day's page is due.
const lateNight=box&&!isToday&&box.dataset.date===etDay(5);
if(box&&box.dataset.date&&box.dataset.date<etDay(5)){ // last build was an earlier day
 const n=document.createElement('div');n.className='stale';
 const d=new Date(box.dataset.date+'T12:00:00Z').toLocaleDateString('en-US',{weekday:'long',month:'short',day:'numeric',timeZone:'UTC'});
 n.innerHTML='<b>Showing '+d+'.</b> Today\u2019s picks haven\u2019t been built yet \u2014 the site rebuilds overnight and before each tip-off block. Check back shortly.';
 document.querySelector('main').prepend(n)}
if(isToday){ // open on the block that's on now, or the next one with games
 const h=+new Date().toLocaleString('en-US',{timeZone:'America/Chicago',hour:'numeric',hourCycle:'h23'});
 const slots=[...document.querySelectorAll('.chip[data-s]')].filter(c=>c.dataset.hi);
 const cur=slots.find(c=>h<+c.dataset.hi&&games.some(g=>g.dataset.slot===c.dataset.s));
 if(cur){S=cur.dataset.s;document.querySelectorAll('.chip[data-s]').forEach(x=>x.classList.toggle('on',x===cur))}
}
apply();
if(!isToday&&!lateNight)return;
const liveChip=document.querySelector('.chip[data-s=live]');
let busy=false,over=false;
async function poll(){
 // not while the tab is in the background, not while the last request is still out, not once every game is final
 if(busy||over||document.hidden)return;busy=true;
 try{
  const d=box.dataset.date.replace(/-/g,'');
  const j=await fetch('https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard?groups=50&limit=500&dates='+d,{cache:'no-store',...(AbortSignal.timeout?{signal:AbortSignal.timeout(20000)}:{})}).then(r=>r.json());
  const map={};
  for(const e of j.events||[]){const c=(e.competitions||[])[0];if(!c)continue;const sc={};
   c.competitors.forEach(p=>sc[p.team.id]=p.score);const st=(c.status||e.status).type;
   map[c.competitors.map(p=>p.team.id).sort().join('-')]={sc,state:st.state,done:st.completed===true,detail:st.shortDetail||st.detail||''}}
  let live=0,open=0;
  if(gd&&!gd.dataset.res){ // the Game of the day's bet: live score, then Won / Lost / Push by the same rules as the Best Bets page
   const m=map[[gd.dataset.ea,gd.dataset.eh].sort().join('-')],st=gd.querySelector('.gst');
   if(m&&st&&m.state!=='pre'){const a=+m.sc[gd.dataset.ea]||0,h=+m.sc[gd.dataset.eh]||0;st.hidden=false;
    if(m.state==='in'){st.innerHTML='<span class="livetag">LIVE</span><b></b><span class="clock"></span>';
     st.querySelector('b').textContent=a+'-'+h;st.querySelector('.clock').textContent=m.detail}
    else if(m.done){const k=gd.dataset.kind,s=gd.dataset.side,n=parseFloat(gd.dataset.num)||0;
     const v=k==='Total'?(a+h-n)*(s==='over'?1:-1):(s==='home'?h-a:a-h)+(k==='Spread'?n:0),r=v>0?'W':v<0?'L':'P';
     gd.dataset.res=r;gd.querySelector('.gbet').classList.add(r);
     st.innerHTML='<span class="res '+r+'">'+(r==='W'?'Won':r==='L'?'Lost':'Push')+'</span><em></em>';
     st.querySelector('em').textContent='Final '+a+'-'+h}
    else st.textContent=m.detail}}
  games.forEach(g=>{
   const m=map[[g.dataset.ea,g.dataset.eh].sort().join('-')];
   if(!m||m.state==='pre'){open++;return}
   const a=+m.sc[g.dataset.ea]||0,h=+m.sc[g.dataset.eh]||0,lv=g.querySelector('.lv');if(!lv)return;
   if(m.state!=='in'&&!m.done){ // postponed or canceled: there is no score and no result to show
    lv.hidden=false;lv.querySelector('.score').style.display='none';g.classList.remove('is-live');g.classList.add('is-done');g.style.order=1;
    lv.querySelector('.lstat').innerHTML='<span class="fintag"></span>';lv.querySelector('.fintag').textContent=m.detail||'Off';return}
   lv.hidden=false;lv.querySelector('.score').style.display='';lv.querySelector('.la').textContent=a;lv.querySelector('.lh').textContent=h;
   lv.querySelector('.la').className='la '+(a>=h?'w':'l');lv.querySelector('.lh').className='lh '+(h>=a?'w':'l');
   const ls=lv.querySelector('.lstat');
   if(m.state==='in'){live++;open++;g.classList.add('is-live');g.classList.remove('is-done');
    ls.innerHTML='<span class="livetag">LIVE</span><span class="clock"></span>';ls.querySelector('.clock').textContent=m.detail}
   else{g.classList.remove('is-live');g.classList.add('is-done');g.style.order=1;
    const ok=(a>h?'a':'h')===g.dataset.pick;
    ls.innerHTML='<span class="fintag">Final</span><span class="okx '+(ok?'W':'L')+'">'+(ok?'\\u2713 Pick':'\\u2717 Pick')+'</span>'}
  });
  if(liveChip){liveChip.querySelector('.n').textContent=live;liveChip.classList.toggle('has',live>0)}
  apply();
  if(!open){over=true;clearInterval(timer)}
 }catch(e){}finally{busy=false}
}
const timer=setInterval(poll,60000);poll();
document.addEventListener('visibilitychange',()=>{if(!document.hidden)poll()});
})();
</script>"""


# ---------------- helpers ----------------
def _hex(c):
    c = (c or "").strip().lstrip("#")
    return f"#{c}" if len(c) == 6 else "#3a3f4a"


def _lum(h):
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))
    f = lambda v: v / 12.92 if v <= .03928 else ((v + .055) / 1.055) ** 2.4  # noqa: E731
    return .2126 * f(r) + .7152 * f(g) + .0722 * f(b)


def _vivid(h):
    """Team color that still reads on black: brighten very dark colors."""
    h = _hex(h)
    if _lum(h) >= .05:
        return h
    r, g, b = (int(h[i:i + 2], 16) for i in (1, 3, 5))
    mix = lambda v: int(v + (255 - v) * .38)  # noqa: E731
    return f"#{mix(r):02x}{mix(g):02x}{mix(b):02x}"


def _team(teams, tid, name):
    t = teams.get(str(tid)) or teams.get(tid) or {}
    return {"name": name, "mascot": t.get("mascot") or "", "logo": t.get("logo") or "",
            "abbr": (t.get("abbr") or name[:3]).upper()[:4], "color": _hex(t.get("color")), "conf": t.get("conf") or "",
            "vivid": _vivid(t.get("color")), "espn": str(t.get("espn") or "")}


def _disc(t):
    inner = (f'<img src="{escape(t["logo"])}" alt="" loading="lazy" '
             f'onerror="this.replaceWith(Object.assign(document.createElement(\'em\'),{{textContent:\'{escape(t["abbr"])}\'}}))">'
             if t["logo"] else f'<em>{escape(t["abbr"])}</em>')
    return f'<div class="disc" style="--c:{t["color"]}">{inner}</div>'


def predicted_score(r):
    """Split the projected total by the projected margin (rating gap x points per rating unit).
    The picked team always comes out ahead, matching the pick."""
    try:
        total, diff = float(r["total"]), float(r["differential"])
    except (TypeError, ValueError, KeyError):
        return None, None
    m = max(config.POINTS_PER_RATING * diff, 1.0)
    win, lose = round(total / 2 + m / 2), round(total / 2 - m / 2)
    if win <= lose:
        win = lose + 1
    return (lose, win) if r["pick"] == r["home"] else (win, lose)


def tip_ct(when):
    """'Nov 2, 2026 7:30 PM ET' -> aware datetime in Central time, or None."""
    try:
        et = datetime.strptime((when or "").replace(" ET", ""), "%b %d, %Y %I:%M %p").replace(tzinfo=config.ET)
    except ValueError:
        return None
    return et.astimezone(config.CT)


def slot_of(when):
    t = tip_ct(when)
    if not t:
        return "late"
    return next(k for k, _, lo, hi in SLOTS if lo <= t.hour < hi)


def _tip(when):
    t = tip_ct(when)
    if not t:
        return escape(when or "")
    return f'{t.strftime("%-I:%M")}<br> {t.strftime("%p")}'



def _short(teams, tid, name):
    """School name, or its abbreviation when the name is too long for the line pill."""
    if len(name) <= 14:
        return name
    t = teams.get(str(tid)) or {}
    return (t.get("abbr") or name).strip()


def ou_play(r):
    """'Over' / 'Under' when the model's total is OU_EDGE_POINTS+ away from the line, else ''."""
    try:
        edge = float(r["total"]) - float(r["line_total"])
    except (TypeError, ValueError, KeyError):
        return ""
    if edge >= config.OU_EDGE_POINTS:
        return "Over"
    if edge <= -config.OU_EDGE_POINTS:
        return "Under"
    return ""


def upset(r):
    """'ultra' when the model picks the betting underdog AND it's a strong pick, 'upset' when it
    just picks the underdog, '' otherwise (no line, pick'em, or model agrees with the favorite)."""
    fav = r.get("line_fav") or ""
    try:
        spread = float(r.get("line_spread") or 0)
    except ValueError:
        spread = 0
    if not fav or spread <= 0 or not r.get("pick") or r["pick"] == fav:
        return ""
    return "ultra" if r.get("strong_pick") else "upset"


def ou_result(r):
    """For a graded over/under play: '1' win, '0' loss, '' push or no play."""
    play = ou_play(r)
    if not play or r.get("away_pts") in ("", None):
        return ""
    actual, line = int(r["away_pts"]) + int(r["home_pts"]), float(r["line_total"])
    if actual == line:
        return ""
    return "1" if (actual > line) == (play == "Over") else "0"


def bet_pill(bet, teams):
    """The one bet the model likes in this game (from bets.py), as a pill. '' when nothing qualifies."""
    if not bet:
        return ""
    import bets as B
    label = bet["label"]
    if bet["kind"] != "Total" and len(label) > 22:                 # shorten long school names
        tid = bet["home_id"] if bet["side"] == "home" else bet["away_id"]
        team = bet["home"] if bet["side"] == "home" else bet["away"]
        label = label.replace(team, _short(teams, tid, team), 1)
    return (f'<span class="ln betpill{" strong" if bet["chance"] >= 0.62 else ""}" title="{bet["chance"] * 100:.0f}% model chance, '
            f'{bet["edge"] * 100:+.0f} points of edge over the price"><i>Bet</i>{escape(label)}<b>{B.fmt_odds(bet["odds"])}</b></span>')


def _line_pills(r, teams, final=False, bet=None):
    """Market line under the predicted score: favorite and spread, then the over/under, then the
    bet the model likes (if any)."""
    pills = []
    if r.get("line_spread"):
        sp = float(r["line_spread"])
        if sp == 0 or not r.get("line_fav"):
            pills.append('<span class="ln"><i>Line</i>Pick\u2019em</span>')
        else:
            fav = r["line_fav"]
            tid = r["home_id"] if fav == r["home"] else r["away_id"]
            pills.append(f'<span class="ln"><i>Line</i>{escape(_short(teams, tid, fav))} \u2212{sp:g}</span>')
    if r.get("line_total"):
        play = ou_play(r)
        if play:
            tag = play
            if final:
                res = ou_result(r)
                tag += "" if res == "" else (" \u2713" if res == "1" else " \u2717")
            cls = "ln hot" + (" won" if final and ou_result(r) == "1" else " lost" if final and ou_result(r) == "0" else "")
            pills.append(f'<span class="{cls}" title="Model total {float(r["total"]):.1f} vs line">'
                         f'<i>O/U</i>{float(r["line_total"]):g}<b>{tag}</b></span>')
        else:
            pills.append(f'<span class="ln"><i>O/U</i>{float(r["line_total"]):g}</span>')
    if bet:
        pills.append(bet_pill(bet, teams))
    return f'<div class="line">{"".join(pills)}</div>' if pills else ""


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-") or "team"


def game_path(r):
    """Site-relative path of a game's own page: games/2026-11-04/duke-vs-north-carolina.html"""
    return f'games/{r["date"]}/{slug(r["away"])}-vs-{slug(r["home"])}.html'


def _why(wu, pick, link=""):
    """Collapsible write-up under a game row."""
    if not wu:
        return ""
    items = "".join(f"<li>{escape(t)}</li>" for t in wu["lines"])
    more = f'<li class="more"><a href="{escape(link)}">Full breakdown &rarr;</a></li>' if link else ""
    return (f'<details class="why"><summary><span>Why {escape(pick)}?</span><em>{escape(wu["headline"])}</em></summary>'
            f'<ul>{items}{more}</ul></details>')


def _named(t, root=""):
    """A team's name on a game row, linked to the team's own page when it has one."""
    name = escape(t["name"])
    if teamdata is None:
        return name
    path = teamdata.team_path(t["name"])
    return f'<a class="tl" href="{root}{path}">{name}</a>' if _there(path) else name


def _row(r, teams, final=False, wu=None, link=True, bet=None, root=""):
    """root = the way back to the top of the site from the page the row is on (for the team links
    and the link to the game's own page). A finished game links to its page only when that page
    exists: the season's first two games (Nov 1) were played before game pages did."""
    a, h = _team(teams, r["away_id"], r["away"]), _team(teams, r["home_id"], r["home"])
    href = root + game_path(r) if link and r.get("date") else ""
    if wu:
        a["rank"], h["rank"] = wu["away_rank"], wu["home_rank"]
    pa, ph = predicted_score(r)
    home_pick = r["pick"] == r["home"]
    pc = h["vivid"] if home_pick else a["vivid"]
    strong = bool(r["strong_pick"])
    try:
        edge = min(float(r["differential"]) / (2 * config.STRONG_PICK_GAP), 1.0)
    except (TypeError, ValueError):
        edge = 0
    sa, sh = ("w", "l") if not home_pick else ("l", "w")
    up = upset(r)
    flag = ('<span class="flag ultra" title="Model picks the betting underdog with a strong-pick edge">Ultra upset</span>' if up == "ultra"
            else '<span class="flag up" title="Model picks the betting underdog">Upset pick</span>' if up == "upset"
            else '<span class="flag">Strong pick</span>' if strong else "")
    fh = f'1H <b>{escape(r["fh_pick"])}</b> by {float(r["fh_margin"]):.1f}' if r.get("fh_pick") and r.get("fh_margin") else ""
    if final:
        res = f'<span class="res {"W" if r["pick_correct"] == "1" else "L"}">{"W" if r["pick_correct"] == "1" else "L"}</span>'
        fhres = ""
        if r.get("fh_correct") in ("0", "1"):
            fhres = f' <span class="res {"W" if r["fh_correct"] == "1" else "L"}">1H {"W" if r["fh_correct"] == "1" else "L"}</span>'
        side = (f'<div class="pick">{flag}{res}{fhres}</div>'
                f'<div class="meta">Picked <b>{escape(r["pick"])}</b></div>'
                f'<div class="meta">Total {float(r["total"]):.0f} proj, {int(r["away_pts"]) + int(r["home_pts"])} actual</div>')
        center = (f'<div class="mid"><div><div class="score"><span class="{"w" if int(r["away_pts"]) > int(r["home_pts"]) else "l"}">{r["away_pts"]}</span>'
                  f'<span class="dash"></span><span class="{"w" if int(r["home_pts"]) > int(r["away_pts"]) else "l"}">{r["home_pts"]}</span></div>'
                  f'<div class="final">Final, model had {pa}-{ph}</div></div>{_line_pills(r, teams, final=True)}</div>')
        lose_a, lose_h = int(r["away_pts"]) < int(r["home_pts"]), int(r["home_pts"]) < int(r["away_pts"])
    else:
        side = (f'<div class="pick">{flag}<span>{escape(r["pick"])}</span></div>'
                f'<div class="meter{" r" if home_pick else ""}" title="Edge"><i style="width:{max(edge, .06) * 100:.0f}%"></i></div>'
                f'<div class="meta">Total <b>{float(r["total"]):.1f}</b>{"&ensp;" + fh if fh else ""}</div>')
        center = (f'<div class="mid"><div class="sc">'
                  f'<div class="lv" hidden><div class="score"><span class="la">0</span><span class="dash"></span><span class="lh">0</span></div>'
                  f'<div class="lstat"><span class="livetag">LIVE</span><span class="clock"></span></div></div>'
                  f'<div class="pred"><div class="score" aria-label="Predicted score {pa} to {ph}"><span class="{sa}">{pa}</span>'
                  f'<span class="dash"></span><span class="{sh}">{ph}</span></div></div>'
                  f'</div>{_line_pills(r, teams, bet=bet)}</div>')
        lose_a, lose_h = home_pick, not home_pick
    live_attrs = (f' data-res="{"W" if r.get("pick_correct") == "1" else "L"}"' if final else (
        f' data-slot="{slot_of(r["when"])}" data-ea="{escape(a["espn"])}" data-eh="{escape(h["espn"])}"'
        f' data-pick="{"h" if home_pick else "a"}"'))
    live_attrs += f' data-teams="{escape(str(r["away_id"]))}|{escape(str(r["home_id"]))}"'
    confs = {c for c in (a["conf"], h["conf"]) if c}
    top25 = any(0 < (t.get("rank") or 0) <= 25 for t in (a, h))
    live_attrs += f' data-conf="{escape("|".join(sorted(confs)))}"' + (' data-top25="1"' if top25 else "")
    return (f'<article class="g{" strong" if strong else ""}{" ou" if ou_play(r) else ""}'
            f'{" upset" if up else ""}{" ultra" if up == "ultra" else ""}" style="--pc:{pc}"{live_attrs}>'
            f'<div class="time">{_tip(r["when"])}{"<small>Neutral</small>" if r.get("neutral") == "1" else ""}</div>'
            f'<div class="team a{" lose" if lose_a else ""}">{_disc(a)}<div class="nm"><b>{_named(a, root)}{_rk(a)}{_star(r["away_id"], a["name"])}</b><span>{escape(a["mascot"])}</span></div></div>'
            f'{center}'
            f'<div class="team h{" lose" if lose_h else ""}">{_disc(h)}<div class="nm"><b>{_named(h, root)}{_rk(h)}{_star(r["home_id"], h["name"])}</b><span>{escape(h["mascot"])}</span></div></div>'
            f'<div class="side">{side}</div>{_why(wu, r["pick"], href) if wu else (f"<a class=gl href={href}>Breakdown &rarr;</a>" if final and href and _there(game_path(r)) else "")}</article>')


def _star(tid, name):
    return (f'<button class="fav" data-tid="{escape(str(tid))}" aria-pressed="false" '
            f'title="Add {escape(name)} to My teams" aria-label="Favorite {escape(name)}">\u2606</button>')


def _rk(t):
    return f'<i class="rk" title="Model rank of {t.get("rank")} Division I teams">#{t["rank"]}</i>' if t.get("rank") else ""


FAVICON = ("data:image/svg+xml," + "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Cdefs%3E%3CradialGradient id='g' cx='35%25' cy='35%25'%3E"
           "%3Cstop offset='0' stop-color='%23ffb259'/%3E%3Cstop offset='.6' stop-color='%23e0701d'/%3E%3Cstop offset='1' stop-color='%239c4310'/%3E%3C/radialGradient%3E%3C/defs%3E"
           "%3Ccircle cx='16' cy='16' r='15' fill='url(%23g)' stroke='%23000' stroke-width='1.5'/%3E"
           "%3Cpath d='M16 1v30M1 16h30' stroke='%23000' stroke-width='1.5' fill='none'/%3E%3C/svg%3E")


def _v(stamp):
    """Cache-buster for the share image: changes every build."""
    return "".join(ch for ch in (stamp or "") if ch.isalnum())[:14]


def ad_slot(slot="auto"):
    """A responsive display ad unit, or nothing until config.ADSENSE_CLIENT is set."""
    if not config.ADSENSE_CLIENT:
        return ""
    return (f'<div class="ad"><ins class="adsbygoogle" style="display:block" data-ad-client="{escape(config.ADSENSE_CLIENT)}"'
            f' data-ad-format="{escape(slot)}" data-full-width-responsive="true"></ins>'
            '<script>(adsbygoogle=window.adsbygoogle||[]).push({});</script></div>')


def site_url(path=""):
    """Public address of a page. The home page is the bare domain, not /index.html, so search
    engines see one address for it."""
    path = "" if path in ("", "index.html") else path
    return f"{config.SITE_URL}/{path}"


def analytics():
    """Cloudflare Web Analytics beacon (cookie-free visit counts), or nothing until
    config.CF_ANALYTICS_TOKEN is filled in."""
    token = re.sub(r"[^0-9A-Za-z]", "", getattr(config, "CF_ANALYTICS_TOKEN", "") or "")
    if not token:
        return ""
    # character for character the snippet Cloudflare hands out (Manage site > JS snippet)
    return ("<!-- Cloudflare Web Analytics --><script type='module' "
            "src='https://static.cloudflareinsights.com/beacon.min.js' "
            f"data-cf-beacon='{{\"token\": \"{token}\"}}'></script><!-- End Cloudflare Web Analytics -->")


BEACON_RE = re.compile(r"(?:<!-- Cloudflare Web Analytics -->)?<script[^>]*static\.cloudflareinsights\.com/beacon\.min\.js"
                       r"[^>]*></script>(?:<!-- End Cloudflare Web Analytics -->)?")


def add_beacon(docs=None):
    """Put the visit counter on game pages written before tracking was switched on. Pages older
    than three days are never rebuilt, and they are the ones search engines send people to, so
    without this those visits would go uncounted. A page that already has a counter gets the
    current one (so a new token replaces the old). Returns the number of pages changed."""
    tag = analytics()
    if not tag:
        return 0
    n = 0
    for p in ((docs or DOCS) / "games").glob("*/*.html"):
        html = p.read_text(encoding="utf-8")
        if BEACON_RE.search(html):
            new = BEACON_RE.sub(lambda m: tag, html, count=1)
        elif "</body>" in html:
            new = html.replace("</body>", tag + "</body>", 1)
        else:
            continue
        if new != html:
            p.write_text(new, encoding="utf-8")
            n += 1
    return n


COMING = set()      # pages the running build is about to write (build.py fills it), besides the files already there


def _there(path, active=""):
    """Is this page part of the site? path = its address from the top of the site ("rankings.html",
    "teams/duke.html", "games/2026-11-21/a-vs-b.html"). The Rankings, the team pages and the method
    page are written by build.py, not by write() below, so a tab or a link to one of them appears
    only when the page is there, or on its way in this build. A site built by an older build.py
    never links to them, and no page links to a game or a team that has no page."""
    return path == active or path in COMING or (DOCS / path).exists()


def page(title, active, body, stamp, description="", root="", head_extra="", og_image="", canonical=None):
    """active = which tab is lit. root = relative path back to the site root ("../../" for
    games/<date>/x.html). canonical = the page's own site-relative path when it is not one of
    the tabs (every game page has its own; without it search engines are told the page is a
    copy of the tab it sits under and skip it)."""
    tabs = [("index.html", "Today"), ("live.html", "Live"), ("bets.html", "Best Bets"), ("results.html", "Results")]
    if _there("rankings.html", active):
        tabs.append(("rankings.html", "Rankings"))
    method = "model.html" if _there("model.html", active) else ""
    nav = "".join(f'<a href="{root}{h}" class="{"on" if h == active else ""}">{t}</a>' for h, t in tabs)
    og_image = og_image or f"{config.SITE_URL}/og.png?v={_v(stamp)}"
    ads = (f'<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={escape(config.ADSENSE_CLIENT)}"'
           ' crossorigin="anonymous"></script>') if config.ADSENSE_CLIENT else ""
    desc = description or ("College basketball predictions from a statistical model: picks, projected scores, "
                           "betting-line edges and a public, locked-before-tipoff record.")
    url = escape(site_url(active if canonical is None else canonical))
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width,initial-scale=1"><meta name="color-scheme" content="dark">'
            f'<title>{escape(title)}</title><meta name="description" content="{escape(desc)}">'
            f'<link rel="canonical" href="{url}">'
            f'<meta property="og:type" content="website"><meta property="og:site_name" content="{escape(config.SITE_NAME)}">'
            f'<meta property="og:title" content="{escape(title)}"><meta property="og:description" content="{escape(desc)}">'
            f'<meta property="og:url" content="{url}"><meta property="og:image" content="{og_image}">'
            f'<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">'
            f'<meta name="twitter:card" content="summary_large_image"><meta name="twitter:title" content="{escape(title)}">'
            f'<meta name="twitter:description" content="{escape(desc)}"><meta name="twitter:image" content="{og_image}">'
            f'<link rel="icon" href="{FAVICON}">{_fonts(root)}{ads}{head_extra}<style>{CSS}</style></head><body>'
            f'<header class="top"><div class="wrap"><a class="brand" href="{root}index.html"><i></i>{escape(config.SITE_NAME)}</a>'
            f'<nav>{nav}</nav></div></header><main class="wrap">{body}{ad_slot()}</main>'
            f'<footer class="wrap"><div>Updated {escape(stamp)}</div>'
            f'<div class="links">'
            + (f'<a href="{root}{method}">How the model works</a><a href="{root}about.html">About</a>'
               f'<a href="{root}about.html#contact">Contact</a>' if method else f'<a href="{root}about.html">About the model</a>')
            + f'<a href="{root}privacy.html">Privacy</a>'
            f'<span>For information and entertainment only, not betting advice. 21+. '
            f'Gambling problem? Call 1-800-GAMBLER.</span></div></footer>{JS}'
            # visits are counted on every public page; the private studio page stays out of the numbers
            f'{"" if active == config.STUDIO_PAGE else analytics()}</body></html>')


def _tale(r, profiles, root):
    """How the two teams of a game compare, side by side: where each stands in the model and the
    numbers behind it, the better side of each line in bold. profiles = {team id: teamdata profile}.
    '' unless both teams have a profile (and their season numbers). It is an extra on the game's
    page, so anything unexpected in a profile leaves the table out instead of stopping the build."""
    try:
        return _tale_html(r, profiles, root)
    except Exception:                                      # noqa: BLE001
        return ""


def _tale_html(r, profiles, root):
    a, h = profiles.get(int(r["away_id"])), profiles.get(int(r["home_id"]))
    if not a or not h or not a.get("factors") or not h.get("factors"):
        return ""

    def line(label, va, vh, better):                     # better: -1 the away side, 1 the home side, 0 neither
        return (f'<tr><td class="{"best" if better < 0 else ""}">{va}</td><td class="k">{label}</td>'
                f'<td class="{"best" if better > 0 else ""}">{vh}</td></tr>')

    def low(x, y):                                       # the smaller number is the better one
        return (x > y) - (x < y)
    rows = [line("Model rank", f'#{a["place"]}', f'#{h["place"]}', low(a["place"], h["place"])),
            line("Rating, in points", _signed(a["points"]), _signed(h["points"]), -low(a["points"], h["points"])),
            line("Record", f'{a["wins"]}-{a["losses"]}', f'{h["wins"]}-{h["losses"]}', 0),
            line("Offense rank", f'#{a["off_rank"]}', f'#{h["off_rank"]}', low(a["off_rank"], h["off_rank"])),
            line("Defense rank", f'#{a["def_rank"]}', f'#{h["def_rank"]}', low(a["def_rank"], h["def_rank"])),
            line("Schedule strength", f'#{a["sos_rank"]}', f'#{h["sos_rank"]}', low(a["sos_rank"], h["sos_rank"]))]
    for key, label, good in (("fg", "Effective FG %", 1), ("opp_fg", "Opponents’ effective FG %", -1), ("tov", "Turnover rate", -1),
                             ("opp_tov", "Turnovers forced", 1), ("orb", "Own misses rebounded", 1),
                             ("opp_orb", "Opponents’ misses they get", -1), ("ft", "Free throws made per 100 shots", 1),
                             ("opp_ft", "Free throws allowed per 100 shots", -1),
                             ("ppg", "Points per game", 1), ("opp_ppg", "Points allowed", -1)):
        x, y = a["factors"][key][0], h["factors"][key][0]
        fmt = (lambda v: f"{v:.1f}") if key in ("ppg", "opp_ppg") else (lambda v, k=key: _factor_value(k, v))
        rows.append(line(label, fmt(x), fmt(y), -good * low(x, y)))
    return ('<div class="sect st"><h2>How the two teams compare</h2><span>the model’s ratings today and this season’s numbers; '
            'effective FG % counts a made three as one and a half makes</span></div>'
            '<div class="tw"><table class="rt ft tale narrow"><thead><tr>'
            f'<th>{_named(a, root)}</th><th class="k"></th><th>{_named(h, root)}</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def game_page(r, teams, wu, stamp, line_note="", profiles=None):
    """A page of its own for one game: the model's call, the write-up, the line, how the two teams
    compare, and the result once the game is graded. Lives at games/<date>/<away>-vs-<home>.html and
    never goes away, so a search for "<away> vs <home> prediction" has something to land on.
    profiles = {team id: teamdata profile} for the comparison table and the links to the team pages."""
    teams = teams or {}
    final = r.get("away_pts") not in ("", None)
    h = _team(teams, r["home_id"], r["home"])
    d = datetime.fromisoformat(r["date"])
    day = d.strftime("%A, %B %-d, %Y")
    t = tip_ct(r["when"])
    tip = (t.strftime("%-I:%M %p") + " Central") if t else "time TBD"
    pa, ph = predicted_score(r)
    title = f'{r["away"]} vs {r["home"]} prediction, {d.strftime("%b %-d, %Y")}'
    if final:
        title = f'{r["away"]} vs {r["home"]} ({r["away_pts"]}-{r["home_pts"]}) result and model pick, {d.strftime("%b %-d, %Y")}'
    desc = (f'{r["pick"]} is the model pick. Projected score {r["away"]} {pa}, {r["home"]} {ph}'
            + (f'. Final: {r["away"]} {r["away_pts"]}, {r["home"]} {r["home_pts"]}.' if final else ".")
            + " College basketball prediction with the reasons behind it.")
    row = _row(r, teams, final=final, wu=None, link=False, root="../../")
    reasons = "".join(f"<li>{escape(x)}</li>" for x in (wu or {}).get("lines", [])) if wu else ""
    if final:
        won = r.get("pick_correct") == "1"
        verdict = (f'<p class="verdict {"W" if won else "L"}"><b>{"Correct" if won else "Missed"}.</b> The model had '
                   f'{escape(r["pick"])}; {escape(r["home"] if int(r["home_pts"]) > int(r["away_pts"]) else r["away"])} won '
                   f'{max(int(r["away_pts"]), int(r["home_pts"]))}-{min(int(r["away_pts"]), int(r["home_pts"]))}.</p>')
    else:
        verdict = ""
    ld = {"@context": "https://schema.org", "@type": "SportsEvent", "name": f'{r["away"]} at {r["home"]}',
          "sport": "Basketball", "startDate": r.get("start") or r["date"],
          "homeTeam": {"@type": "SportsTeam", "name": r["home"]}, "awayTeam": {"@type": "SportsTeam", "name": r["away"]},
          "url": f"{config.SITE_URL}/{game_path(r)}", "description": desc,
          "eventStatus": "https://schema.org/EventScheduled"}
    if h.get("logo"):
        ld["image"] = h["logo"]
    head = f'<script type="application/ld+json">{json.dumps(ld)}</script>'
    body = (f'<section class="hero"><div><p class="crumb"><a href="../../index.html">Today</a> &rsaquo; '
            f'<a href="../../results.html">Results</a> &rsaquo; {escape(day)}</p>'
            f'<h1>{escape(r["away"])} vs {escape(r["home"])}</h1>'
            f'<p>{escape(day)}, {escape(tip)}{" &middot; neutral site" if r.get("neutral") == "1" else ""}. '
            f'{"Final score and how the model did." if final else "Model prediction, projected score and the reasons."}</p></div></section>'
            f'<div class="games one">{row}</div>{verdict}'
            + (f'<div class="sect"><h2>Why the model {"had" if final else "likes"} {escape(r["pick"])}</h2></div>'
               f'<ul class="greasons one">{reasons}</ul>' if reasons else "")
            + (f'<p class="note">{escape(line_note)}</p>' if line_note else "")
            + (_tale(r, profiles, "../../") if profiles and teamdata else "")
            + '<p class="note">Every pick is locked before tip-off and graded from the final score. '
              f'<a href="../../{"model" if _there("model.html") else "about"}.html">How the model works</a>.</p>')
    return page(f"{title} | {config.SITE_NAME}", "results.html" if final else "index.html", body, stamp, desc,
                root="../../", head_extra=head, canonical=game_path(r))


def studio_page(stamp, date_label, gotd=None, teams=None, wu=None, caption="", yesterday=None, matches_site=None):
    """Private posting page: the day's clip, caption and share image in one place.
    gotd = the game the clip shows, which is the site's Game of the day (matches_site: True when the
    build confirms it is the same game as the card on the Today page). No caption = no clip has been
    rendered for today yet, so there is nothing to download."""
    teams = teams or {}
    if gotd:
        pa, ph = predicted_score(gotd)
        # no bet box on this page: it is about the post, and the clip and its caption never mention a bet
        card = gotd_card(gotd, teams, wu, pa, ph, show_bet=False,
                         kicker="Game of the day clip" if matches_site else "Today’s clip")
        clip = clip_box(caption) or (
            '<div class="clip"><div><b>Today’s clip is not ready yet</b><span>The next build makes it, for the game above. '
            'Until then there is nothing to post: the video file on the site is an earlier one.</span></div></div>')
    else:
        card = '<div class="empty"><b>No games today</b>Nothing to post; the next clip renders overnight.</div>'
        clip = ""
    rec = (f'<p class="note">Yesterday the picks went <b>{yesterday[0]}-{yesterday[1]}</b>; worth putting in the caption.</p>'
           if yesterday and sum(yesterday) else "")
    body = (f'<section class="hero"><div><h1>Posting studio</h1><p>{escape(date_label)}. This page is private: not linked, '
            'not indexed. Download, add a trending sound in the app, paste the caption, post.</p></div></section>'
            + card + clip + rec +
            '<div class="clip"><div><b>Share image</b><span>The link preview picture for X, Reddit and Discord posts.</span></div>'
            '<div class="cb"><a class="btn ghost" href="og.png" download="tipoffedge-today.png">Download image</a></div></div>'
            '<p class="note">Routine: post the clip at the same time each day, an hour or two before the first tip-off. '
            'Reply to comments in the first hour. Same clip to TikTok, Instagram Reels and YouTube Shorts.</p>')
    html = page(f"{config.SITE_NAME} - Studio", config.STUDIO_PAGE, body, stamp, "Private posting page.",
                head_extra='<meta name="robots" content="noindex,nofollow">')
    return html


# ---------------- rankings and team pages ----------------
def _ord(n):
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _signed(x, digits=1):
    """+21.4 / −8.2 (a real minus sign, so the column lines up)."""
    return f"{'+' if round(x, digits) >= 0 else '−'}{abs(x):.{digits}f}"


def _pct1(x):
    return f"{100 * x:.1f}%"


def _factor_value(key, x):
    """One of the model's eight inputs as the pages write it: free throws are a count per 100 shot
    attempts (no % sign: it is a rate, not a share), everything else a percentage."""
    return f"{100 * x:.1f}" if key in ("ft", "opp_ft") else _pct1(x)


def team_href(name, root=""):
    return f"{root}{teamdata.team_path(name)}"


def _move(p):
    """▲3 / ▼2 / – for the places a team has moved (see teamdata.moves)."""
    m = p.get("move")
    if not m:
        return '<td class="c-mv">–</td>'
    return f'<td class="c-mv {"up" if m > 0 else "dn"}">{"▲" if m > 0 else "▼"}{abs(m)}</td>'


RANK_JS = r"""<script>
(()=>{
const tb=document.querySelector('.rt tbody');if(!tb)return;
const rows=[...tb.rows],q=document.getElementById('rkq'),sel=document.getElementById('rkc'),n0=document.getElementById('rkn'),none=document.getElementById('rk0');
let key='rank',dir=1,F='all',C='',Q='';
function favs(){try{return new Set(JSON.parse(localStorage.getItem('te_favs')||'[]'))}catch(e){return new Set()}}
function apply(){
 const f=favs();let n=0;
 rows.forEach(r=>{const ok=(F==='all'||(F==='top25'&&+r.dataset.rank<=25)||(F==='fav'&&f.has(r.dataset.tid)))&&(!C||r.dataset.conf===C)&&(!Q||r.dataset.name.includes(Q));r.hidden=!ok;if(ok)n++});
 n0.textContent=n===rows.length?'All '+n+' teams':n+' of '+rows.length+' teams';none.hidden=n>0;
}
function sort(k){
 if(k===key)dir=-dir;else{key=k;dir=(k==='pts'||k==='win'||k==='move')?-1:1}
 rows.sort((a,b)=>{const d=k==='name'?a.dataset.name.localeCompare(b.dataset.name):parseFloat(a.dataset[k])-parseFloat(b.dataset[k]);return d?d*dir:+a.dataset.rank-+b.dataset.rank});
 rows.forEach(r=>tb.appendChild(r));
 document.querySelectorAll('.rt th[data-k]').forEach(h=>h.setAttribute('aria-sort',h.dataset.k===key?(dir>0?'ascending':'descending'):'none'));
}
document.querySelectorAll('.rt th[data-k]').forEach(h=>h.querySelector('button').addEventListener('click',()=>sort(h.dataset.k)));
document.querySelectorAll('.rkbar .chip').forEach(c=>c.addEventListener('click',()=>{F=c.dataset.f;document.querySelectorAll('.rkbar .chip').forEach(x=>x.classList.toggle('on',x===c));apply()}));
q.addEventListener('input',()=>{Q=q.value.trim().toLowerCase();apply()});
function conf(v){C=v;sel.value=v;apply()}
sel.addEventListener('change',()=>conf(sel.value));
document.querySelectorAll('a[data-conf]').forEach(a=>a.addEventListener('click',e=>{e.preventDefault();conf(a.dataset.conf);document.querySelector('.rkbar').scrollIntoView({behavior:'smooth',block:'start'})}));
// a star tapped in the table changes My teams: the main script saves it first, then this list follows
document.addEventListener('click',e=>{if(e.target.closest('.fav'))setTimeout(apply,0)});
// rankings.html#conf=Big%2012 opens on that league (the link on every team page)
function fromHash(){const m=/[#&]conf=([^&]+)/.exec(location.hash);if(!m)return;let v='';try{v=decodeURIComponent(m[1])}catch(e){}
 if(v&&[...sel.options].some(o=>o.value===v))conf(v)}
addEventListener('hashchange',fromHash);
apply();fromHash();
})();
</script>"""


def rankings_page(profs, confs, stamp, teams=None, facts=None):
    """Every rated Division I team, best first, with the parts its rating is made of. The table
    sorts on any column and narrows by conference, by name, to the top 25 or to My teams.
    profs = teamdata.profiles(...), confs = teamdata.conferences(profs),
    facts = {"median_gp": games the typical team has played, "since": date the Move column compares with}."""
    teams, facts = teams or {}, facts or {}
    n = len(profs)
    since = _short_date(facts.get("since") or "")
    moved = bool(since)                 # the Move column appears once there is an earlier day to compare with
    rows = []
    for p in profs:
        t = _team(teams, p["id"], p["name"])
        games = p["wins"] + p["losses"]
        rows.append(
            f'<tr data-tid="{p["id"]}" data-conf="{escape(p["conf"])}" data-name="{escape((p["name"] + " " + p["mascot"]).lower())}" '
            f'data-rank="{p["place"]}" data-pts="{p["points"]:.2f}" data-off="{p["off_rank"]}" data-def="{p["def_rank"]}" '
            f'data-sos="{p["sos_rank"]}" data-win="{(p["wins"] / games if games else 0):.3f}" data-move="{p.get("move") or 0}">'
            f'<td class="n">{p["place"]}</td>'
            f'<td class="t"><div class="tm">{_disc(t)}<div><a href="{team_href(p["name"])}">{escape(p["name"])}</a>'
            f'<small>{escape(p["conf"])}<span class="rec"> · {p["wins"]}-{p["losses"]}</span></small></div>'
            f'{_star(p["id"], p["name"])}</div></td>'
            f'<td class="c-rec">{p["wins"]}-{p["losses"]}</td><td class="pts">{_signed(p["points"])}</td>'
            f'<td>{p["off_rank"]}</td><td>{p["def_rank"]}</td><td class="c-sos">{p["sos_rank"]}</td>{_move(p) if moved else ""}</tr>')
    head = ('<tr><th data-k="rank" class="n" aria-sort="ascending"><button>#</button></th>'
            '<th data-k="name" class="t"><button>Team</button></th>'
            '<th data-k="win" class="c-rec"><button>Record</button></th>'
            '<th data-k="pts"><button title="Points better than an average Division I team on a neutral floor">Rating</button></th>'
            '<th data-k="off"><button title="National rank of the offense rating">Off<i>ense</i></button></th>'
            '<th data-k="def"><button title="National rank of the defense rating">Def<i>ense</i></button></th>'
            '<th data-k="sos" class="c-sos"><button title="How tough the schedule has been (1 = toughest)">Schedule</button></th>'
            + (f'<th data-k="move" class="c-mv"><button title="Places moved since {since}">Move</button></th>' if moved else "") + '</tr>')
    options = "".join(f'<option value="{escape(c)}">{escape(c)}</option>' for c in sorted({p["conf"] for p in profs if p["conf"]}))
    tools = ('<div class="rkbar"><button class="chip on" data-f="all">All teams</button>'
             '<button class="chip" data-f="top25">Top 25</button>'
             '<button class="chip favchip" data-f="fav">★ My teams</button>'
             f'<select id="rkc" aria-label="Conference"><option value="">All conferences</option>{options}</select>'
             '<input id="rkq" type="search" placeholder="Find a team" aria-label="Find a team" autocomplete="off">'
             '<span id="rkn" class="rkn"></span></div>')
    gp = facts.get("median_gp")
    share = min(1.0, gp / config.BLEND_GAMES) if gp is not None and config.BLEND_GAMES else 1.0
    early = (f'<p><b>Early-season note:</b> the typical team has played {gp:g} game{"s" if gp != 1 else ""}, so about '
             f'{100 * (1 - share):.0f}% of a typical rating still comes from last season’s team. That share shrinks with '
             f'every game until a team has played {config.BLEND_GAMES}, so expect the list to move more than a poll does.</p>' if share < 1 else "")
    home = config.HOME_COURT_POINTS
    intro = ('<div class="prose wide"><p>Every Division I team, ranked by the same ratings the daily picks are made from. '
             '<b>Rating</b> is how many points better than an average Division I team the model makes a team on a neutral floor. '
             'Tap a column to sort by it, or a team for its schedule and numbers.</p></div>')
    guide = ('<div class="sect st"><h2>How to read the rankings</h2></div><div class="prose wide">'
             f'<p>The gap between two teams’ ratings, plus about {home:g} points for the home team, is the projected margin when '
             f'they play: a +20 team at home against a +8 team projects to win by about {12 + home:g}. <b>Offense</b>, <b>Defense</b> '
             'and <b>Schedule</b> are national ranks in the three parts a rating is built from: what a team does with the ball, '
             'what it allows, and how strong its opponents have been (1 is the toughest schedule).'
             + (f' <b>Move</b> is how many places a team has gone up or down since {since}.' if moved else "")
             + ' The list is recalculated every morning from the games played so far.</p>' + early
             + '<p>Ratings come from each team’s shooting, turnovers, rebounding and free throws on both ends of the floor, '
               'adjusted for the opponents it has played. They are the model’s opinion, not a poll, and they move as results come in.'
             + (' <a href="model.html">How the model works</a>.' if _there("model.html") else "") + '</p></div>')
    conf_rows = "".join(
        f'<tr><td class="n">{i}</td><td class="t"><a href="#conf={quote(c["conf"], safe="")}" data-conf="{escape(c["conf"])}">{escape(c["conf"])}</a></td>'
        f'<td class="c-rec">{c["n"]}</td><td class="pts">{_signed(c["avg"])}</td><td>{c["top25"]}</td><td>{c["top100"]}</td>'
        f'<td class="t c-sos"><a href="{team_href(c["best"]["name"])}">{escape(c["best"]["name"])}</a> <i class="rk">#{c["best"]["place"]}</i></td></tr>'
        for i, c in enumerate(confs, 1))
    conf_table = ('<div class="sect st" id="conferences"><h2>Conference strength</h2><span>average rating of the teams in each league; '
                  'tap a league to see only its teams</span></div>'
                  '<div class="tw"><table class="rt ct"><thead><tr><th class="n">#</th><th class="t">Conference</th><th class="c-rec">Teams</th>'
                  '<th>Avg rating</th><th>Top 25</th><th>Top 100</th><th class="t c-sos">Best team</th></tr></thead>'
                  f'<tbody>{conf_rows}</tbody></table></div>') if confs else ""
    top = profs[0] if profs else None
    body = (f'<section class="hero"><div><h1>Rankings</h1><p>College basketball power ratings for all {n} Division I teams, updated daily.</p></div>'
            + (f'<div class="stats"><div class="stat am"><b>{escape(top["name"])}</b><span>No. 1 today, {_signed(top["points"])}</span></div>'
               f'<div class="stat"><b>{n}</b><span>teams rated</span></div></div>' if top else "") + '</section>'
            + intro + tools
            + f'<div class="tw"><table class="rt"><thead>{head}</thead><tbody>{"".join(rows)}</tbody></table></div>'
            '<div class="empty" id="rk0" hidden><b>No teams</b>Nothing matches that. Clear the search or pick another conference.</div>'
            + guide + conf_table + RANK_JS)
    return page(f"College Basketball Power Rankings: All {n} Division I Teams | {config.SITE_NAME}", "rankings.html", body, stamp,
                f"Model power ratings for all {n} Division I men’s college basketball teams, updated daily: overall rank, rating "
                "in points, offense, defense, strength of schedule and conference strength.")


def _game_day(g):
    """'Sat, Nov 21' for a game on a team's schedule."""
    try:
        return datetime.fromisoformat(g["date"]).strftime("%a, %b %-d")
    except (TypeError, ValueError):
        return g.get("date") or ""


def _sched_row(p, g, by_id, root):
    """One line of a team's schedule: when, who, the result, and what the model said."""
    opp = by_id.get(g["opp_id"])
    name = escape(g["opp"] or "TBD")
    who = (f'<a href="{root}{teamdata.team_path(opp["name"])}">{name}</a> <i class="rk">#{opp["place"]}</i>' if opp
           else name + ('' if g["opp"] in ("", "TBD") else ' <i class="rk">not D-I</i>'))
    where = {"home": "vs", "away": "at", "neutral": "vs"}[g["where"]]
    site_note = ' <i class="rk">neutral</i>' if g["where"] == "neutral" else ""
    t = tip_ct(g.get("when") or "")
    when = _game_day(g) + (f'<small>{t.strftime("%-I:%M %p")}</small>' if t and g["state"] != "final" else "")
    if g["state"] == "final":
        res = (f'<b class="{"up" if g["won"] else "dn"}">{"W" if g["won"] else "L"}</b> '
               f'{max(g["pts"], g["opp_pts"])}–{min(g["pts"], g["opp_pts"])}')
    else:
        res = '<span class="soon">Today</span>' if g["state"] == "today" else ""
    pk = g.get("pick")
    if pk:
        winner = p["name"] if pk["own"] else (g["opp"] or "the opponent")
        call = f'{escape(winner)} {max(pk["pf"], pk["pa"])}–{min(pk["pf"], pk["pa"])}'
        if not pk["official"]:
            mod = f'<span class="soon">Early look</span> {call}'
        else:
            mark = "" if pk["hit"] is None else f' <span class="okx {"W" if pk["hit"] else "L"}">{"✓" if pk["hit"] else "✗"}</span>'
            page_there = pk["path"] and _there(pk["path"])               # a few early games never got a page
            mod = ('<span class="ml">Model: </span>'
                   + (f'<a href="{root}{escape(pk["path"])}">{call}</a>' if page_there else call) + mark)
    elif g["state"] == "final" or g["opp"] not in ("", "TBD"):
        mod = '<span class="dimx">No pick' + ("" if g["rated"] else ": opponent not in Division I") + '</span>'
    else:
        mod = '<span class="dimx">Opponent not set yet</span>'
    return (f'<tr><td class="t d">{when}</td><td class="t">{where} {who}{site_note}</td>'
            f'<td class="rs">{res}</td><td class="t m">{mod}</td></tr>')


def _factor_rows(p, avgs, side, part):
    """The four inputs of one side of the ball: the number, the Division I average under it, the
    national rank. part = "offense" or "defense", for the line saying how much of that rating each is."""
    n = p["n_factors"]
    out = []
    for i, (key, label, weight, good) in enumerate(side):
        val, rank = p["factors"][key]
        share = f'{100 * getattr(config, weight):.0f}%' + (f' of the {part} rating' if i == 0 else "")
        out.append(f'<tr><td class="t"><b>{label}</b><small>{share}{" · lower is better" if good < 0 else ""}</small></td>'
                   f'<td class="pts">{_factor_value(key, val)}<small>avg {_factor_value(key, avgs[key])}</small></td>'
                   f'<td class="rkc"><span class="rkbar2" style="--p:{100 * (n - rank + 1) / n:.0f}%"></span>{_ord(rank)}</td></tr>')
    return "".join(out)


def team_page(p, profs, stamp, teams=None, avgs=None):
    """A page of its own for one team: where it stands in the model, the numbers the rating is built
    from, and every game with the model's pick beside the result. p = one of teamdata.profiles()."""
    teams = teams or {}
    by_id = {q["id"]: q for q in profs}
    t = _team(teams, p["id"], p["name"])
    n, root = len(profs), "../"
    full = f'{p["name"]} {p["mascot"]}'.strip()
    rec = f'{p["wins"]}-{p["losses"]}'
    mr, mw = p["model_record"]
    them = ("" if p["mascot"].lower().startswith("the ") else "the ") + escape(p["mascot"]) if p["mascot"] else "them"
    summary = (f'{escape(p["name"])} rates <b>{_ord(p["place"])} of {n}</b> Division I teams. The model makes {them} '
               f'<b>{abs(p["points"]):.1f} points {"better" if p["points"] >= 0 else "worse"}</b> than an average Division I team on a neutral floor. '
               f'The offense ranks {_ord(p["off_rank"])} nationally and the defense {_ord(p["def_rank"])}, and the schedule rates as '
               f'the {_ord(p["sos_rank"])}-toughest.')
    if p.get("move"):
        summary += (f' That is {"up" if p["move"] > 0 else "down"} {abs(p["move"])} place{"s" if abs(p["move"]) != 1 else ""} '
                    f'since {_short_date(p.get("move_since") or "")}.')
    notes = []
    if p["new_team"]:
        notes.append(f'{escape(p["name"])} is new to Division I, so there is no last season to lean on: the rating starts near the '
                     f'bottom and is earned game by game over the first {config.BLEND_GAMES}.')
    elif p["blend"] < 1:
        notes.append(f'Early-season note: after {p["gp"]} game{"s" if p["gp"] != 1 else ""}, about {100 * p["blend"]:.0f}% of this rating '
                     f'comes from this season and {100 * (1 - p["blend"]):.0f}% from last season’s team. Last season fades out '
                     f'completely once a team has played {config.BLEND_GAMES} games.')
    tiles = (f'<div class="tiles"><div class="tile am"><b>#{p["place"]}</b><span>of {n} teams</span></div>'
             f'<div class="tile"><b>{_signed(p["points"])}</b><span>rating, in points</span></div>'
             f'<div class="tile"><b>#{p["off_rank"]}</b><span>offense</span></div>'
             f'<div class="tile"><b>#{p["def_rank"]}</b><span>defense</span></div>'
             f'<div class="tile"><b>#{p["sos_rank"]}</b><span>schedule strength</span></div>'
             + (f'<div class="tile"><b>{mr}-{mw}</b><span>model’s picks in their games</span></div>' if mr + mw else "") + '</div>')
    factors = ""
    if p.get("factors") and avgs:
        head = '<thead><tr><th class="t">{}</th><th>{}</th><th>Rank</th></tr></thead>'
        ppg, opp_ppg = p["factors"]["ppg"], p["factors"]["opp_ppg"]
        factors = (
            f'<div class="sect st"><h2>The numbers behind the rating</h2><span>this season, {p["gp"]} game{"s" if p["gp"] != 1 else ""}; '
            'avg is the Division I average</span></div>'
            '<div class="two"><div class="tw"><table class="rt ft">' + head.format("Offense", "Team")
            + f'<tbody>{_factor_rows(p, avgs, teamdata.OFFENSE, "offense")}</tbody></table></div>'
            '<div class="tw"><table class="rt ft">' + head.format("Defense", "Opponents")
            + f'<tbody>{_factor_rows(p, avgs, teamdata.DEFENSE, "defense")}</tbody></table></div></div>'
            f'<p class="note">Scoring {ppg[0]:.1f} points a game ({_ord(ppg[1])}) and allowing {opp_ppg[0]:.1f} ({_ord(opp_ppg[1])})'
            + (f', at a pace of {p["pace"]:.0f} possessions a game' if p.get("pace") else "")
            + '. These eight numbers are everything the model knows about a team before it adjusts for the schedule. '
              'Effective field goal % counts a made three as one and a half makes.'
            + (f' <a href="{root}model.html">How the rating is built</a>.' if _there("model.html") else "") + '</p>')
    games = p["games"]
    done = [g for g in games if g["state"] == "final"]
    ahead = [g for g in games if g["state"] != "final"]
    sched = ""
    if games:
        thead = '<thead><tr><th class="t">Date</th><th class="t">Opponent</th><th>Result</th><th class="t">Model</th></tr></thead>'
        said = (f' The model has had the winner in {mr} of the {mr + mw} it picked.' if mr + mw else "")
        if ahead:
            sched += ('<div class="sect st"><h2>Coming up</h2><span>projected scores; a pick is official once it is locked on game day</span></div>'
                      f'<div class="tw"><table class="rt sched">{thead}<tbody>{"".join(_sched_row(p, g, by_id, root) for g in ahead)}</tbody></table></div>')
        if done:
            sched += (f'<div class="sect st"><h2>Results</h2><span>{rec} this season.{said}</span></div>'
                      f'<div class="tw"><table class="rt sched">{thead}<tbody>{"".join(_sched_row(p, g, by_id, root) for g in reversed(done))}</tbody></table></div>')
    league = [q for q in profs if q["conf"] == p["conf"] and p["conf"]]
    mates = ""
    if len(league) > 1:
        mates = (f'<div class="sect st"><h2>{escape(p["conf"])}</h2><span>where the league’s teams rate</span></div><p class="mates">'
                 + "".join(f'<a class="{"me" if q["id"] == p["id"] else ""}" href="{root}{teamdata.team_path(q["name"])}">'
                           f'<i>#{q["place"]}</i> {escape(q["name"])}</a>' for q in league) + '</p>')
    nxt = ahead[0] if ahead else None
    desc = (f'{full}: {_ord(p["place"])} of {n} in the {config.SITE_NAME} model ({rec}). Offense {_ord(p["off_rank"])}, defense '
            f'{_ord(p["def_rank"])}, schedule {_ord(p["sos_rank"])}. Schedule, results and the model’s pick for every game'
            + (f', next: {"vs" if nxt["where"] != "away" else "at"} {nxt["opp"]}' if nxt and nxt["opp"] not in ("", "TBD") else "") + ".")
    path = teamdata.team_path(p["name"])
    ld = [{"@context": "https://schema.org", "@type": "SportsTeam", "name": full, "sport": "Basketball",
           "url": f"{config.SITE_URL}/{path}", **({"logo": t["logo"]} if t.get("logo") else {}),
           **({"memberOf": {"@type": "SportsOrganization", "name": p["conf"]}} if p["conf"] else {})},
          {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
              {"@type": "ListItem", "position": 1, "name": "Rankings", "item": f"{config.SITE_URL}/rankings.html"},
              {"@type": "ListItem", "position": 2, "name": full, "item": f"{config.SITE_URL}/{path}"}]}]
    head = f'<script type="application/ld+json">{json.dumps(ld)}</script>'
    conf_link = (f' &rsaquo; <a href="{root}rankings.html#conf={quote(p["conf"], safe="")}">{escape(p["conf"])}</a>' if p["conf"] else "")
    body = (f'<section class="hero"><div><p class="crumb"><a href="{root}rankings.html">Rankings</a>{conf_link}</p>'
            f'<div class="thero" style="--pc:{t["vivid"]}">{_disc(t)}<div><h1>{escape(p["name"])}</h1>'
            f'<p>{escape(p["mascot"])}{" · " if p["mascot"] else ""}{escape(p["conf"])} · {rec}{_star(p["id"], p["name"])}</p></div></div></div></section>'
            + tiles + f'<div class="prose wide"><p>{summary}</p>' + "".join(f"<p>{x}</p>" for x in notes) + '</div>'
            + sched + factors + mates
            + f'<p class="note">The rating and the ranks are recalculated every morning; a result is added once the game is final. '
              f'Every pick is locked before tip-off and graded from the final score; see the full record on the '
              f'<a href="{root}results.html">Results</a> page.</p>')
    return page(f"{full} Basketball: Model Rating, Schedule and Predictions | {config.SITE_NAME}", "rankings.html", body, stamp, desc,
                root=root, head_extra=head, canonical=path)


def _example_block(ex):
    """The worked example on the method page: one real game, the arithmetic line by line."""
    if not ex:
        return ""
    fav, dog = (ex["home"], ex["away"]) if ex["home_rating"] >= ex["away_rating"] else (ex["away"], ex["home"])
    gap = abs(ex["home_rating"] - ex["away_rating"])
    gap_pts = config.POINTS_PER_RATING * gap
    court = ("Neutral floor, so nobody gets a home-court edge." if ex["neutral"] else
             f'{escape(ex["home"])} was at home, which {"adds" if ex["home_rating"] >= ex["away_rating"] else "takes"} '
             f'{config.HOME_COURT_POINTS:g} points {"to" if ex["home_rating"] >= ex["away_rating"] else "off"} that gap.')
    # the margin as the lines above add up to it (the stored numbers are rounded, so adding the
    # rounded pieces keeps the arithmetic on the page exact)
    shown = round(gap_pts, 1)
    margin = shown if ex["neutral"] else abs(shown + (1 if ex["home_rating"] >= ex["away_rating"] else -1) * config.HOME_COURT_POINTS)
    final = ""
    if ex.get("final"):
        ap, hp = ex["final"]
        won = ex["home"] if hp > ap else ex["away"]
        final = (f'<li><b>What happened:</b> {escape(won)} won {max(ap, hp)}–{min(ap, hp)}. '
                 f'{"The pick was right" if won == ex["pick"] else "The pick was wrong"}, and the margin missed by '
                 f'{abs((hp - ap) - (ex["ph"] - ex["pa"]))} points.</li>')
    return ('<div class="ex"><span class="kicker">Worked example</span>'
            f'<h3>{escape(ex["away"])} {"vs" if ex["neutral"] else "at"} {escape(ex["home"])}, {escape(ex["day"])}</h3><ol>'
            f'<li><b>Ratings:</b> {escape(ex["away"])} {ex["away_rating"]:.4f}, {escape(ex["home"])} {ex["home_rating"]:.4f}. '
            f'{escape(fav)} is ahead by {gap:.4f}.</li>'
            f'<li><b>Into points:</b> {gap:.4f} × {config.POINTS_PER_RATING} = {gap_pts:.1f} points better than {escape(dog)} on a neutral floor.</li>'
            f'<li><b>Home court:</b> {court}</li>'
            f'<li><b>Projected margin:</b> {escape(ex["pick"])} by {margin:.1f}.</li>'
            f'<li><b>Projected total:</b> the two teams’ scoring levels add up to {ex["total"]:.1f} points.</li>'
            f'<li><b>Projected score:</b> half the total each, plus and minus half the margin: '
            f'{escape(ex["away"])} {ex["pa"]}, {escape(ex["home"])} {ex["ph"]}.</li>{final}</ol>'
            + (f'<p><a href="{escape(ex["path"])}">This game’s own page</a> has the pick as it was posted.</p>'
               if ex.get("path") and _there(ex["path"]) else "")
            + '</div>')


def _record_block(rec):
    """How the picks have done, by how confident the model was. Shown only while
    config.SHOW_RESULTS_STATS is on, like the totals on the Results page."""
    if not rec or not config.SHOW_RESULTS_STATS:
        return ('<p>Every graded game, with the projected and the actual score side by side, is on the '
                '<a href="results.html">Results</a> page. Nothing is ever removed from it.</p>')
    games = rec["right"] + rec["wrong"]
    # one bar per band: the share of those picks that won, with the record beside it
    bars = _meters([(f'{escape(label)}<small>{w + l} game{"s" if w + l != 1 else ""}</small>', w / (w + l),
                     f'<b>{100 * w / (w + l):.0f}%</b>{w}-{l}', "", "") for label, w, l in rec["bands"] if w + l])
    sw, sl = rec.get("strong") or (0, 0)
    return (f'<p>Through {escape(rec["last"])} the model has picked the winner in <b>{rec["right"]} of {games} games '
            f'({100 * rec["right"] / games:.0f}%)</b>' + (f', and in {sw} of {sw + sl} strong picks ({100 * sw / (sw + sl):.0f}%)' if sw + sl else "")
            + '. The honest way to read a model is by how sure it was, so here is the same record split by the size of the '
            'projected margin. Each bar is the share of those picks that won:</p>'
            + bars +
            f'<p>A game projected inside three points is close to a coin flip, and the record shows it. The projected '
            f'margin has missed the real one by {rec["margin_miss"]:.1f} points on average, and the projected total by '
            f'{rec["total_miss"]:.1f}. Every one of those games is on the <a href="results.html">Results</a> page, '
            'and none is ever removed.</p>')


MODEL_FAQ = (
    ("When are the picks posted?",
     "Each day’s picks are posted overnight, by about 4:30 AM Central, and the page is refreshed before each block of tip-offs "
     "through the day. A game added to the schedule late gets its pick at the next refresh, as long as it has not tipped off."),
    ("Does a pick ever change after it is posted?",
     "No. A pick is locked the moment it is posted. If the ratings move later in the day, the posted pick stays as it was, "
     "and that is the one that gets graded."),
    ("What is the early look?",
     "Once the day’s last game has tipped off, the Today page lists the next day’s games with projected scores. Those are "
     "not picks yet: the official picks are made overnight, after the night’s results are counted, and can differ slightly."),
    ("Why is a game missing?",
     "The model only rates Division I teams, so a game against a lower-division opponent gets no pick. A bracket game whose "
     "opponent is not decided yet appears once the matchup is set."),
    ("Why does the model like a team the betting line does not?",
     "The line knows things the model does not, such as injuries and lineup news, and it is usually closer to the truth. When "
     "the two disagree the game is marked as an upset pick so you can see it for what it is: the riskiest kind of pick on the site."),
    ("Is this betting advice?",
     "No. It is a model’s opinion, published so anyone can check it against the results. It is wrong often, as the record "
     "shows, and nothing here should be read as a reason to bet money."),
    ("Is it free?",
     "Yes. There is no sign-up, no paid tier and no picks for sale."),
)


def model_page(stamp, facts=None):
    """How the model works, start to finish, written from the code: every number on this page is
    read from config.py and bets.py when the page is built, so it cannot drift from what the model does.
    facts = live numbers from the build (all optional): n_teams, median_gp, record, example."""
    import bets
    f = facts or {}
    w = [round(100 * x) for x in (config.W_SHOOT, config.W_TOV, config.W_REB, config.W_FT)]
    strong_pts = config.STRONG_PICK_GAP * config.POINTS_PER_RATING
    n = f.get("n_teams")
    gp = f.get("median_gp")
    share = min(1.0, gp / config.BLEND_GAMES) if gp is not None and config.BLEND_GAMES else None
    live = (f' Right now the typical team has played {gp:g} game{"s" if gp != 1 else ""}, so about {100 * share:.0f}% of a typical '
            f'rating is this season and {100 * (1 - share):.0f}% is last season.' if share is not None and share < 1 else "")
    faq_html = "".join(f"<h3>{escape(q)}</h3><p>{a}</p>" for q, a in MODEL_FAQ)
    ld = {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in MODEL_FAQ]}
    body = (
        '<section class="hero"><div><h1>How the model works</h1><p>The whole method in plain English: what goes in, how a score '
        'comes out, and how the picks are kept honest.</p></div></section>'
        '<div class="prose">'
        '<h2>The short version</h2>'
        f'<p>Every Division I team{f" (all {n} of them)" if n else ""} gets a rating from four things it does on offense and the '
        'same four things it allows on defense. The rating is adjusted for how strong its opponents have been. The gap between '
        f'two teams’ ratings, plus about {config.HOME_COURT_POINTS:g} points for the home team, becomes a projected margin and a '
        'projected score. Every pick is posted before tip-off, locked, and graded against the final score where anyone can see it.</p>'
        '<p>It began as a spreadsheet. The same formulas now run automatically every morning.</p>'

        '<h2>Step 1: Rate every team from four things</h2>'
        '<p>Basketball games are decided by a short list of things: making shots, keeping the ball, rebounding your own misses '
        'and getting to the free throw line. Coaches and analysts call them the four factors. The model scores each team on all four, for '
        'its own offense and for what its opponents manage against its defense, and weights them like this:</p>'
        '<div class="tw"><table class="rt ft narrow"><thead><tr><th class="t">Factor</th><th>Weight</th><th class="t">On offense</th>'
        '<th class="t">On defense</th></tr></thead><tbody>'
        f'<tr><td class="t"><b>Shooting</b></td><td class="pts">{w[0]}%</td><td class="t">effective field goal %</td><td class="t">opponents’ effective field goal %</td></tr>'
        f'<tr><td class="t"><b>Turnovers</b></td><td class="pts">{w[1]}%</td><td class="t">share of possessions not turned over</td><td class="t">turnovers forced</td></tr>'
        f'<tr><td class="t"><b>Rebounding</b></td><td class="pts">{w[2]}%</td><td class="t">own misses rebounded</td><td class="t">opponents’ misses kept off the glass</td></tr>'
        f'<tr><td class="t"><b>Free throws</b></td><td class="pts">{w[3]}%</td><td class="t">free throws made per shot attempt</td><td class="t">free throws opponents make per shot attempt</td></tr>'
        '</tbody></table></div>'
        '<p>Effective field goal % counts a made three as one and a half makes, because it is worth one and a half times the '
        'points. Free throws are counted per shot attempt, so a team is rewarded for getting to the line as well as for making '
        'them, and a defense for keeping opponents off it. A turnover rate is turnovers divided by the possessions that could '
        'have ended in one (shots, trips to the line and turnovers). A rebound rate is offensive rebounds divided by the misses '
        'that were there to get. The four offense scores add up to an offense rating, the four defense scores to a defense '
        'rating, and the two together are the team’s rating.</p>'
        '<p>The weights are not a guess. They were fitted to the results of all 5,752 games between Division I teams last '
        'season, and they say that taking care of the ball matters almost as much as shooting, and that both matter far more '
        'than rebounding or free throws.</p>'
        + ('<p>Every team page lists these eight numbers with their national ranks, so you can see exactly why a team rates '
           'where it does. Start from the <a href="rankings.html">Rankings</a>.</p>' if _there("rankings.html") else "") +

        '<h2>Step 2: Adjust for who they played</h2>'
        '<p>Shooting 50% against the weakest schedule in the country is not the same as doing it in a major conference. So the '
        'model measures how strong each team’s opponents have been, using nothing but game results: who beat whom, by how much, '
        f'and where. Margins are capped at 25 points so running up the score does not count, and home court is taken out. '
        'A team that has played a tough schedule gets credit for it in its rating, and a team that has feasted on weak opponents '
        'is docked.</p>'

        '<h2>Step 3: Early in the season, last year fades out</h2>'
        f'<p>Three games tell you very little about a team. So each season starts from last season’s rating, and this season’s '
        f'numbers take over a little more with every game: after {config.BLEND_GAMES // 4} games a quarter of the rating is new, '
        f'after {config.BLEND_GAMES // 2} games half, and from game {config.BLEND_GAMES} on last season is gone.{live}</p>'
        '<p>Last season’s rating also leans twice as hard on how strong a team’s schedule was, because the league a team plays '
        'in says more about next year’s team than last year’s shooting numbers do. A team that is new to Division I has no last '
        'season at all, so it starts near the bottom and earns its way up.</p>'

        '<h2>Step 4: From ratings to a score</h2>'
        f'<p>The gap between two ratings is turned into points: one full point of rating is worth {config.POINTS_PER_RATING} '
        f'points of margin, a scale that was fitted to more than 2,400 real games. The home team then gets '
        f'{config.HOME_COURT_POINTS:g} points, which is what home teams have actually been worth this season. Nobody gets it at a neutral site.</p>'
        '<p>The projected total comes from how many points each team’s games usually produce: the average of what it scores and '
        'what it allows, added for the two teams. Half the total goes to each side, the favorite gets half the margin added and '
        f'the underdog has it taken away. The first-half pick is the same side, leading at the break by '
        f'{100 * config.FIRST_HALF_SHARE:.0f}% of the projected final margin.</p>'
        + _example_block(f.get("example")) +

        '<h2>What the labels mean</h2>'
        f'<p>A <b>strong pick</b> is a game the model projects by {strong_pts:.0f} points or more. An <b>upset pick</b> is one where '
        'the model picks the team the betting line has as the underdog, and an <b>ultra upset</b> is an upset pick that is also a '
        f'strong pick. An <b>O/U play</b> is a game where the projected total is at least {config.OU_EDGE_POINTS} points away from '
        'the posted over/under.</p>'

        '<h2>Best Bets</h2>'
        '<p>The Best Bets page asks a different question: not who wins, but where the model sees a better chance than the price '
        'implies. Betting lines are sharp, so the model does not replace them. It first puts its own margins on the same scale '
        'as that day’s spreads, then starts from the line and moves '
        f'{100 * bets.MODEL_WEIGHT:.0f}% of the way toward its own number, and works out the chance of each bet winning from how much '
        f'real games scatter around a projection (about {bets.MARGIN_SD:g} points for margins and {bets.TOTAL_SD:g} for totals).</p>'
        f'<p>A bet makes the list only if the model gives it at least a {100 * bets.MIN_CHANCE:.0f}% chance and that chance beats '
        f'what the odds imply by {100 * bets.MIN_EDGE:.0f} percentage points or more. Some bets are never taken: spreads of '
        f'{bets.MAX_SPREAD:g} points or more (early in the season the model underrates blowouts), moneyline favorites shorter than '
        f'{bets.fmt_odds(bets.MAX_FAV_ML)}, and any game where the model and the line are more than {bets.MAX_DISAGREE:g} points apart, '
        'because that usually means bad data rather than a bargain. Each game can put only its best bet on the list.</p>'
        f'<p>The day’s top {bets.SINGLES} single bets are locked once most of the day’s games have a line, and they are graded '
        'won, lost or push from the final score like every other pick. The game behind the top bet is the Game of the day. '
        'Parlays built from the same bets are listed too; a parlay needs every leg to win, so it loses far more often than a single bet.</p>'

        '<h2>Locked, graded, never edited</h2>'
        '<p>A pick only means something if it cannot be changed afterward. Each pick is written to a public record the moment '
        'it is posted, with the time. No pick is added for a game that has already tipped off, the betting line saved with a '
        'pick is the first one seen that day, and results are graded from the final score, usually the same night. Wrong picks '
        'stay on the record next to the right ones.</p>'
        + _record_block(f.get("record")) +

        '<h2>What the model does not know</h2>'
        '<p>It sees box scores and results, and nothing else. It does not know that a star is injured or suspended, that a team '
        'is on the last night of a road trip, or that a coach is resting starters. It does not watch games. It also knows less in '
        'November than in February, when every team has a full season of its own numbers. The betting market knows all of those '
        'things, which is why the model is at its weakest when it disagrees with the line.</p>'

        '<h2>It keeps learning</h2>'
        '<p>Every final score goes back into the ratings the next morning. The settings are checked against results too: the '
        'home-court value, for example, was raised from 2.7 to 4 points in mid-November 2026 after two weeks of games showed home '
        'teams doing better than the model expected. A week later the four factors themselves were re-measured (effective '
        'field goal % in place of plain field goal %, free throws per shot in place of free throw %) and re-weighted, after a '
        'replay of every game of the season showed the new version picking more winners and missing the margin by less. When a '
        'setting changes, picks already on the record stay exactly as they were posted.</p>'

        '<h2>Questions people ask</h2>' + faq_html +

        '<h2>Words used on this site</h2>'
        '<p><b>Spread:</b> the number of points the betting line gives the underdog. <b>Moneyline (ML):</b> a bet on who wins, '
        'with no points. <b>Over/under (O/U) or total:</b> the combined points of both teams. <b>Edge:</b> the model’s chance of a '
        'bet winning minus the chance its odds imply. <b>Push:</b> a bet that lands exactly on the number and is refunded. '
        '<b>Neutral site:</b> a game where neither team is at home.</p>'

        '<h2>Please read this part</h2>'
        '<p>Everything here is for information and entertainment. It is not betting advice. Never bet money you cannot afford '
        'to lose, and you must be of legal age to gamble where you live. If gambling is a problem for you or someone you know, '
        'call or text 1-800-GAMBLER (US).</p>'
        '</div>')
    head = f'<script type="application/ld+json">{json.dumps(ld)}</script>'
    return page(f"How the College Basketball Model Works | {config.SITE_NAME}", "model.html", body, stamp,
                f"How the {config.SITE_NAME} college basketball model works: the four factors behind every team rating, the schedule "
                "adjustment, how a projected score is made, how Best Bets are chosen and how every pick is locked and graded.",
                head_extra=head)


def about_page(stamp):
    """Who is behind the site and how it is run. The method itself has its own page (model_page);
    until that page and the Rankings exist, this page simply does not point at them."""
    name = (getattr(config, "OWNER_NAME", "") or "").strip()
    email = _email()
    social = [(k, v) for k, v in (getattr(config, "SOCIAL_LINKS", None) or {}).items() if v]
    method, ranks = _there("model.html"), _there("rankings.html")
    who = (f'{escape(config.SITE_NAME)} is an independent, one-person project'
           + (f', built and run by {escape(name)}' if name else "")
           + '. It started as a spreadsheet for picking college basketball games. In 2026 the spreadsheet was '
             'rebuilt as this site so that every pick would be posted in public before the game and could be checked afterward.')
    more = ""
    if method:
        more = (' The full method, with a worked example, is on <a href="model.html">How the model works</a>'
                + (', and every team’s numbers are on the <a href="rankings.html">Rankings</a>' if ranks else "") + '.')
    elif ranks:
        more = ' Every team’s numbers are on the <a href="rankings.html">Rankings</a>.'
    links = ", ".join(f'<a href="{escape(v)}" rel="me noopener">{escape(k)}</a>' for k, v in social)
    if email:
        contact = (f'<p>Questions, corrections and feedback are welcome at <a href="mailto:{escape(email)}">{escape(email)}</a>.'
                   + (f' You can also follow along on {links}.' if links else "") + '</p>')
    elif links:
        contact = f'<p>Follow along on {links}. Questions and corrections are welcome in the comments there.</p>'
    else:
        contact = '<p>Questions and corrections can be sent through the site’s public GitHub repository.</p>'
    body = (f'<section class="hero"><div><h1>About</h1><p>What {escape(config.SITE_NAME)} is, who runs it and how it is kept honest.</p></div></section>'
            '<div class="prose">'
            f'<p>{escape(config.SITE_NAME)} publishes a projected score and a pick for every game between two Division I men’s '
            f'college basketball teams, every game day, all season{", along with power rankings for every team" if ranks else ""}. '
            'It is free, with no sign-up and nothing for sale.</p>'
            '<h2>Who is behind it</h2>'
            f'<p>{who}</p>'
            '<h2>How the numbers are made</h2>'
            '<p>The picks come from a statistical model, not from opinions. It rates every team on shooting, turnovers, '
            'rebounding and free throws at both ends of the floor, adjusts for the strength of the schedule, and turns the gap '
            f'between two teams into a projected score.{more}</p>'
            '<h2>The standards the site holds itself to</h2>'
            '<p><b>Posted before tip-off.</b> Every pick is on the site, with a timestamp, before the game starts. '
            '<b>Never edited.</b> Once a pick is posted it is locked. <b>Graded in public.</b> Every result goes on the '
            '<a href="results.html">Results</a> page, wrong picks next to right ones, and none is ever removed. '
            '<b>Fixed in the open.</b> When the data feed gets something wrong, a canceled game listed as played for example, '
            'the record is corrected, and the files behind the site are public, so every change leaves a trace.</p>'
            '<h2>When it updates</h2>'
            '<p>Picks for the day are posted overnight, by about 4:30 AM Central. The pages are refreshed before each block of '
            'tip-offs during the day to pick up betting lines and schedule changes, live scores run in your browser during the '
            f'games, and final scores are graded through the evening.{" The rankings and team pages are recalculated every morning." if ranks else ""}</p>'
            '<h2>Where the data comes from</h2>'
            '<p>Team statistics, schedules, scores and betting lines come from CollegeBasketballData. Live scores on the Today, '
            'Live and Best Bets pages come from ESPN. Team names and logos belong to the schools.</p>'
            '<h2 id="contact">Contact</h2>'
            + contact +
            '<h2>Please read this part</h2>'
            '<p>Everything here is for information and entertainment. It is not betting advice, and a model that is right three '
            'times in four is still wrong one game in four. Never bet money you can’t afford to lose. You must be of legal age '
            'to gamble where you live. If gambling is a problem for you or someone you know, call or text 1-800-GAMBLER (US).</p>'
            '</div>')
    return page(f"About {config.SITE_NAME}: Who Runs It and How It Works", "about.html", body, stamp,
                f"About {config.SITE_NAME}: an independent college basketball prediction model that posts every pick before "
                "tip-off and grades it in public. Who runs it, how it updates, where the data comes from and how to get in touch.")


def _email():
    """The public contact address from config.py ('' until one is set)."""
    return (getattr(config, "CONTACT_EMAIL", "") or "").strip()


def privacy_page(stamp):
    body = ('<section class="hero"><div><h1>Privacy</h1><p>Short version: no accounts, no sign-up, and no personal information collected.</p></div></section>'
            '<div class="prose">'
            f'<p>{escape(config.SITE_NAME)} is a set of static pages. There is no sign-up, no login and no form, and the site '
            'does not collect names, email addresses or any other personal information.</p>'
            '<h2>Advertising</h2>'
            '<p>The site may show ads served by Google AdSense. Google and its partners use cookies and similar technologies to '
            'show ads and measure them, which may include ads based on your visits to this and other websites. You can opt out '
            'of personalized advertising at <a href="https://www.google.com/settings/ads">Google\u2019s ad settings</a>, and '
            'read how Google uses data from sites that use its services at '
            '<a href="https://policies.google.com/technologies/partner-sites">policies.google.com/technologies/partner-sites</a>.</p>'
            '<h2>Live scores and fonts</h2>'
            '<p>On game days the Today, Live and Best Bets pages ask ESPN for live scores from your browser, and the pages load fonts from Google '
            'Fonts. Those services see your IP address in the ordinary way any web request does.</p>'
            '<h2>Hosting</h2>'
            '<p>The pages are hosted on GitHub Pages, which keeps standard server logs. See '
            '<a href="https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement">GitHub\u2019s privacy statement</a>.</p>'
            + ('<h2>Visit counts</h2>'
               '<p>The site counts page views with Cloudflare Web Analytics, which uses no cookies and does not identify or '
               'follow individual visitors. See <a href="https://www.cloudflare.com/web-analytics/">Cloudflare\u2019s description</a>.</p>'
               if analytics() else "") +
            '<h2>Your browser\u2019s storage</h2>'
            '<p>If you star teams for My teams, that list is kept in your browser on your device and is never sent anywhere. '
            'Beyond that the site stores nothing in your browser except what the ad and font services above set.</p>'
            '<h2>Contact</h2>'
            + (f'<p>Questions about this page can be sent to <a href="mailto:{escape(_email())}">{escape(_email())}</a>.</p>' if _email() else
               '<p>Questions about this page can be sent through the site\u2019s GitHub repository.</p>') +
            '</div>')
    return page(f"Privacy | {config.SITE_NAME}", "privacy.html", body, stamp, f"Privacy policy for {config.SITE_NAME}.")


def clip_box(caption):
    """Download + caption for the day's TikTok/Reels clip (shown inside the Game of the Day card)."""
    if not caption:
        return ""
    return ('<div class="clip"><div><b>Today\u2019s clip</b><span>12-second vertical video for TikTok, Reels and Shorts. '
            'Add a trending sound in the app when you post.</span></div>'
            '<div class="cb"><a class="btn" href="daily.mp4" download="tipoffedge-daily.mp4">Download clip</a>'
            f'<button class="btn ghost" data-copy>Copy caption</button></div><textarea hidden>{escape(caption)}</textarea></div>')


BET_WORD = {"W": "Won", "L": "Lost", "P": "Push"}


def gotd_card(r, teams, wu, pa, ph, caption="", bet=None, top=False, final="", lines_out=True,
              kicker="Game of the day", show_bet=True):
    """The Game of the day at the top of the Today page: the game behind the day's top bet.
    top=True: `bet` is that bet (the #1 on the day's locked list, or before the lock the best one on
    the board) and the card follows it through the game. The page's script shows the live score and
    grades the bet at the final, the way the Best Bets page does; final = "70-75" (away-home) and
    bet["result"] when a build has already graded it. Without a top bet the card is a fallback (the
    day's biggest matchup) and says why there is no bet: lines_out=False means no line is posted yet.
    The private posting page shows the clip's matchup with this card too: show_bet=False, own kicker."""
    a, h = _team(teams, r["away_id"], r["away"]), _team(teams, r["home_id"], r["home"])
    ra, rh = (wu or {}).get("away_rank"), (wu or {}).get("home_rank")
    home_pick = r["pick"] == r["home"]
    t = tip_ct(r["when"])
    tip = t.strftime("%-I:%M %p") + " CT" if t else "TBD"
    pills = _line_pills(r, teams)                      # the bet gets its own box below, not a pill
    import bets as B
    hooks, more = "", ""
    accent = (h if home_pick else a)["vivid"]
    if not show_bet:
        thebet = ""
    elif bet and top:
        res = bet.get("result") if bet.get("result") in BET_WORD else ""
        state = (f'<div class="gst"><span class="res {res}">{BET_WORD[res]}</span>{f"<em>Final {escape(final)}</em>" if final else ""}</div>'
                 if res else '<div class="gst" hidden></div>')
        thebet = (f'<div class="gbet top{" " + res if res else ""}"><span>Today’s best bet</span>'
                  f'<b>{escape(bet["label"])} <i>{B.fmt_odds(bet["odds"])}</i></b>'
                  f'<small>{bet["chance"] * 100:.0f}% model chance, +{bet["edge"] * 100:.0f} pts edge</small>{state}</div>')
        num = "" if bet.get("num") in (None, "") else f'{float(bet["num"]):g}'
        hooks = (f' data-ea="{escape(a["espn"])}" data-eh="{escape(h["espn"])}" data-kind="{escape(bet["kind"])}"'
                 f' data-side="{escape(bet["side"])}" data-num="{num}" data-res="{res}"')
        if bet["kind"] != "Total":                     # the stripe down the side takes the color of the team the bet is on
            accent = (h if bet["side"] == "home" else a)["vivid"]
        more = '<a class="gmore" href="bets.html">All of today’s best bets &rarr;</a>'
    elif bet:
        thebet = (f'<div class="gbet"><span>The bet</span><b>{escape(bet["label"])} {B.fmt_odds(bet["odds"])}</b>'
                  f'<small>{bet["chance"] * 100:.0f}% model chance</small></div>')
    elif not lines_out:
        thebet = ('<div class="gbet none"><span>Today’s best bet</span><b>Not posted yet</b>'
                  '<small>It goes here as soon as the betting lines are out</small></div>')
    else:
        thebet = ('<div class="gbet none"><span>Today’s best bet</span><b>No bet today</b>'
                  '<small>Nothing on today’s lines clears the model’s bar, so this is the day’s biggest matchup</small></div>')
    reasons = "".join(f"<li>{escape(x)}</li>" for x in (wu or {}).get("lines", [])[:5])

    def side(team, rk, cls, lose):
        return (f'<div class="gt {cls}{" lose" if lose else ""}">{_disc(team)}<div class="gn">'
                f'{f"<small>#{rk}</small>" if rk else ""}<b>{escape(team["name"])}</b><span>{escape(team["mascot"])}</span></div></div>')
    flag = ('<span class="flag">Strong pick</span>' if r.get("strong_pick") else "")
    return (f'<section class="gotd" style="--pc:{accent}"{hooks}>'
            f'<div class="gh"><span class="kicker">{escape(kicker)}</span><span class="gtip">{escape(tip)}'
            f'{" &middot; Neutral site" if r.get("neutral") == "1" else ""}</span></div>'
            f'<div class="gbody">{side(a, ra, "a", home_pick)}'
            f'<div class="gmid"><div class="gscore"><span class="{"l" if home_pick else "w"}">{pa}</span><span class="dash"></span>'
            f'<span class="{"w" if home_pick else "l"}">{ph}</span></div><div class="gpick">{flag}Projected winner: <b>{escape(r["pick"])}</b></div>{thebet}{pills}</div>'
            f'{side(h, rh, "h", not home_pick)}</div>'
            f'{f"<ul class=greasons>{reasons}</ul>" if reasons else ""}{more}</section>')


def open_feature(rows, bets_by_game):
    """The best bet among the games still open, with its game: {"bet", "row", "final"} or None.
    What the Game of the day card uses when the build did not hand it the day's locked top bet."""
    by_key = {r.get("game_key"): r for r in rows}
    open_bets = [(k, b) for k, b in (bets_by_game or {}).items() if k in by_key]
    if not open_bets:
        return None
    key, bet = min(open_bets, key=lambda kb: (-kb[1]["edge"], -kb[1]["chance"]))
    return {"bet": bet, "row": by_key[key], "final": ""}


def early_look(early, teams=None):
    """The next day's games as an early look: one compact row per game, visitor first, with the
    projected score. Shown on the Today page from the day's last tip-off until the overnight build.
    early = {"label": "Saturday, Nov 21", "rows": rows shaped like ledger rows (saved nowhere, no line,
    no bet), "ranks": {team id: model rank}, "waiting": games still without a matchup,
    "official": "3:30 AM"}. Nothing here is a pick yet, and the text says so. "" when there are no rows."""
    rows = (early or {}).get("rows") or []
    if not rows:
        return ""
    teams, ranks = teams or {}, early.get("ranks") or {}

    def side(t, tid, pts, win):
        rank = ranks.get(str(tid))
        return (f'<div class="et{" w" if win else ""}"><span>{escape(t["name"])}'
                + (f'<i class="rk" title="Model rank">#{rank}</i>' if rank else "") + f'</span><b>{pts}</b></div>')

    def game(r):
        a, h = _team(teams, r["away_id"], r["away"]), _team(teams, r["home_id"], r["home"])
        pa, ph = predicted_score(r)
        home_pick = r["pick"] == r["home"]
        t = tip_ct(r["when"])
        return (f'<div class="eg" style="--pc:{(h if home_pick else a)["vivid"]}">'
                f'<div class="etime">{t.strftime("%-I:%M %p") if t else "Time TBD"}'
                f'{"<small>Neutral</small>" if r.get("neutral") == "1" else ""}</div><div>'
                f'{side(a, r["away_id"], pa, not home_pick)}{side(h, r["home_id"], ph, home_pick)}</div></div>')
    n, wait = len(rows), early.get("waiting") or 0
    when = f' (about {escape(early["official"])} Central)' if early.get("official") else ""
    return (f'<section class="early" id="early"><span class="kicker">Early look</span><h2>{escape(early.get("label") or "")}</h2>'
            f'<p>The model’s first projected {"scores for <b>" + str(n) + " games</b>" if n != 1 else "score for <b>1 game</b>"}, '
            f'visitor listed first. <b>These are not official picks yet.</b> The picks, betting lines and best bets post '
            f'overnight{when}, and the numbers can still move a little as the latest results are counted.'
            + (f' {wait} more game{"s are" if wait != 1 else " is"} waiting on a matchup.' if wait else "")
            + ' Times are Central.</p>'
            f'<div class="elist">{"".join(game(r) for r in rows)}</div></section>')


LEGEND = ('<details class="legend"><summary>How to read this page</summary><div class="lg">'
          '<div><b>Game of the day</b>The game behind the day\u2019s top bet: the biggest gap the model finds between its '
          'chance and the price. It stays that game all day and shows the result when it ends.</div>'
          '<div><b>Predicted score</b>The model\u2019s projected final. The bigger number is the pick.</div>'
          '<div><b>Edge bar</b>How far apart the two teams rate. A full bar is a lopsided matchup.</div>'
          '<div><b><span class="flag">Strong pick</span></b>The model projects a win by about 15 points or more. '
          'These are its most confident picks.</div>'
          '<div><b><span class="flag up">Upset pick</span></b>The model picks the team the betting market has as the underdog. '
          '<span class="flag ultra">Ultra upset</span> is an upset pick that is also a strong pick.</div>'
          '<div><b>Line</b>The sportsbook favorite and spread, and the over/under. An orange O/U pill with '
          '<b style="display:inline;color:var(--amber)">Over</b> or <b style="display:inline;color:var(--amber)">Under</b> marks a game where '
          f'the model\u2019s total is {config.OU_EDGE_POINTS}+ points off the line.</div>'
          '<div><b><span class="ln betpill"><i>Bet</i>Wake Forest +17.5<b>\u2212110</b></span></b>The one bet the model likes in that game: '
          'the side, spread or total where its chance beats the price. The projected winner is not always the bet; a favorite can be the '
          'pick to win and still be a bad number. Games with no Bet pill have no edge.</div>'
          '<div><b>#12</b>Where a team ranks in the model among all Division I teams.</div>'
          '<div><b>Why ...?</b>Tap it under any game for the reasons behind the pick, in plain English.</div>'
          '<div><b>1H</b>First-half pick: the team the model has ahead at halftime, and by about how much.</div>'
          '</div></details>')


def today_page(rows, date_label, stamp, stats_note, teams=None, date_iso="", n_final=0, writeups=None, yesterday=None,
               gotd=None, caption="", bets_by_game=None, feature=None, early=None):
    """gotd = the day's biggest matchup (ledger row). feature = {"bet", "row", "final", "wu"}: the day's
    top bet and its game, which is what the Game of the day card shows ("wu" = the write-up to show
    with it, when it differs from the game's row). Without one the card uses the best bet among the
    games still open, and only on a day with nothing to bet the biggest matchup.
    early = the next day's games as an early look (see early_look), handed over by the builds that run
    after the day's last tip-off: it goes under whatever is left of today, and when nothing is left it
    is what the page shows instead of an empty box."""
    teams = teams or {}
    writeups = writeups or {}
    bets_by_game = bets_by_game or {}
    gotd_html = ""
    feature = feature or open_feature(rows, bets_by_game)
    if feature:
        fr = feature["row"]
        pa, ph = predicted_score(fr)
        gotd_html = gotd_card(fr, teams, feature.get("wu") or writeups.get(fr.get("game_key")), pa, ph, caption, feature["bet"],
                              top=True, final=feature.get("final") or "")
    elif gotd:
        pa, ph = predicted_score(gotd)
        gotd_html = gotd_card(gotd, teams, writeups.get(gotd.get("game_key")), pa, ph, caption,
                              lines_out=any(r.get("line_spread") or r.get("line_total") for r in rows))
    n_strong = sum(1 for r in rows if r["strong_pick"])
    n_ou = sum(1 for r in rows if ou_play(r))
    n_up = sum(1 for r in rows if upset(r))
    done_note = (f' <a class="donelink" href="results.html">{n_final} finished game{"s" if n_final != 1 else ""}'
                 ' now on Results &rarr;</a>') if n_final else ""
    early_html = early_look(early, teams)
    if early_html and rows:                              # the early look sits under the games still on the board
        done_note += f' <a class="donelink" href="#early">Early look at {escape(early.get("label") or "tomorrow")} &darr;</a>'
    n_all = len(rows) + n_final
    # what the page is, in the words people search for (also feeds the title and description below)
    lead = (f'College basketball predictions for {"all " + str(n_all) + " games" if n_all > 1 else "the one game"} today: '
            'model picks, projected scores and the reasons behind them. ' if n_all else
            'College basketball predictions from a statistical model, posted every game day. ')
    # the counters describe the games still on the board; with none left, four zeros say nothing
    stats = (f'<div class="stats"><div class="stat"><b>{len(rows)}</b><span>games</span></div>'
             f'<div class="stat am"><b>{n_strong}</b><span>strong picks</span></div>'
             f'<div class="stat am"><b>{n_ou}</b><span>O/U plays</span></div>'
             f'<div class="stat up"><b>{n_up}</b><span>upset picks</span></div>'
             + (f'<div class="stat {"win" if yesterday[0] >= yesterday[1] else "loss"}"><b>{yesterday[0]}-{yesterday[1]}</b><span>yesterday</span></div>'
                if yesterday and config.SHOW_RESULTS_STATS and sum(yesterday) else "")
             + '</div>') if rows or not early_html else ""
    hero = (f'<section class="hero"><div><h1>{escape(date_label)}</h1><p>{lead}{escape(stats_note)}. Times are Central.{done_note}</p></div>'
            f'{stats}</section>')
    if not rows and n_final:
        # the day is done: the Game of the day keeps its place with its result, then the next day's early look
        body = hero + gotd_html + (
            '<div class="alldone"><b>All of today\'s games are final.</b> See how the picks did on the '
            '<a class="donelink" href="results.html">Results</a> page.</div>' + early_html if early_html else
            '<div class="empty"><b>All of today\'s games are final</b>'
            'See how the picks did on the <a class="donelink" href="results.html">Results</a> page.</div>')
    elif not rows:
        body = hero + '<div class="empty"><b>No games today</b>Picks post here each morning on game days.</div>' + early_html
    else:
        chips = ('<div class="bar"><button class="chip on" data-f="all">All games</button>'
                 '<button class="chip favchip" data-f="fav">\u2605 My teams<span class="n">0</span></button>'
                 '<button class="chip" data-f="strong">Strong picks only</button>'
                 '<button class="chip" data-f="ou">O/U plays</button>'
                 '<button class="chip" data-f="upset">Upset picks</button></div>'
                 '<div class="empty" data-empty="strong" hidden><b>No strong picks</b>None of these games has a big enough edge.</div>'
                 '<div class="empty" data-empty="upset" hidden><b>No upset picks</b>The model agrees with every betting favorite today.</div>'
                 '<div class="empty" data-empty="fav" hidden><b>No games for your teams</b>Tap the \u2606 next to any team to add it to My teams. '
                 'Favorites are remembered on this device.</div>'
                 f'<div class="empty" data-empty="ou" hidden><b>No O/U plays</b>No projected total is {config.OU_EDGE_POINTS}+ points off the line.</div>')
        present = {}
        for r in rows:
            for tid in (r["away_id"], r["home_id"]):
                c = (teams.get(str(tid)) or {}).get("conf")
                if c:
                    present[c] = present.get(c, 0) + 1
        majors = ["ACC", "Big 12", "Big East", "Big Ten", "SEC"]
        order = [c for c in majors if c in present] + sorted(c for c in present if c not in majors)
        n_top = sum(1 for r in rows if any(0 < ((writeups.get(r.get("game_key")) or {}).get(k) or 0) <= 25
                                           for k in ("away_rank", "home_rank")))
        conf_sel = ('<label class="confsel"><span>Show</span><select id="conf"><option value="">All conferences</option>'
                    + (f'<option value="top25">Top 25 ({n_top})</option>' if n_top else "")
                    + "".join(f'<option value="{escape(c)}">{escape(c)} ({present[c]})</option>' for c in order)
                    + '</select></label>')
        counts = {k: sum(1 for r in rows if slot_of(r["when"]) == k) for k, *_ in SLOTS}
        slot_chips = (conf_sel + '<div class="bar slots"><button class="chip on" data-s="all">All day<span class="n">'
                      f'{len(rows)}</span></button>'
                      + "".join(f'<button class="chip" data-s="{k}" data-hi="{hi}">{lab}<span class="n">{counts[k]}</span></button>'
                                for k, lab, lo, hi in SLOTS if counts[k])
                      + '<button class="chip livechip" data-s="live">Live now<span class="n">0</span></button></div>'
                      '<div class="empty" data-empty="slot" hidden><b>No games in this window</b>Pick another time block.</div>'
                      '<div class="empty" data-empty="live" hidden><b>Nothing live right now</b>Live games show up here with the score and clock.</div>'
                      '<div class="empty" data-empty="mix" hidden><b>Nothing here</b>No games match both filters in this time block.</div>'
                      '<div class="empty" data-empty="conf" hidden><b>No games</b>Nothing from that conference in this view. Try All day.</div>')
        body = (hero + gotd_html + slot_chips + chips + LEGEND + f'<div class="games" data-date="{escape(date_iso)}">'
                + "".join(_row(r, teams, wu=writeups.get(r.get("game_key")), bet=bets_by_game.get(r.get("game_key"))) for r in rows) + "</div>"
                + early_html)
    short = _short_date(date_iso)
    title = f'College Basketball Predictions Today{", " + short if short else ""} | {config.SITE_NAME}'
    desc = ((f'Model picks and projected scores for {"all " + str(n_all) if n_all > 1 else "the"} college basketball '
             f'game{"s" if n_all != 1 else ""} on {date_label}'
             + (f', including {gotd["away"]} vs {gotd["home"]}' if gotd else "")
             + '. Free, updated through the day, and every pick is graded after the final.') if n_all else "")
    ld = {"@context": "https://schema.org", "@type": "WebSite", "name": config.SITE_NAME, "url": site_url()}
    return page(title, "index.html", body, stamp, desc, head_extra=f'<script type="application/ld+json">{json.dumps(ld)}</script>')


def _short_date(date_iso):
    """'2026-11-17' -> 'Nov 17' ('' when there is no date)."""
    try:
        return datetime.fromisoformat(date_iso).strftime("%b %-d")
    except (TypeError, ValueError):
        return ""


def _record(rows, col):
    g = [r for r in rows if r.get(col) in ("0", "1")]
    w = sum(1 for r in g if r[col] == "1")
    return w, len(g) - w


RESULTS_TITLE = f"College Basketball Results and Model Record | {config.SITE_NAME}"
RESULTS_DESC = ("Every college basketball prediction graded against the final score: the pick, the projected score "
                "and what actually happened, day by day. Nothing is ever removed.")


RESULTS_DAYS = 3        # game days listed on results.html itself (about 130 games); every day also lives for good on its week's page
RESULT_CHIPS = ('<div class="bar"><button class="chip on" data-f="all">All games</button>'
                '<button class="chip favchip" data-f="fav">★ My teams<span class="n">0</span></button>'
                '<button class="chip" data-f="strong">Strong picks only</button>'
                '<button class="chip" data-f="ou">O/U plays</button>'
                '<button class="chip" data-f="upset">Upset picks</button></div>'
                '<div class="empty" data-empty="strong" hidden><b>No strong picks</b>No graded strong picks yet.</div>'
                '<div class="empty" data-empty="upset" hidden><b>No upset picks</b>No graded upset picks yet.</div>'
                '<div class="empty" data-empty="fav" hidden><b>No results for your teams yet</b>Tap the ☆ next to any team to add it to My teams.</div>'
                '<div class="empty" data-empty="ou" hidden><b>No O/U plays</b>No graded over/under plays yet.</div>')


def week_start(date_iso):
    """The Monday of the week a date falls in, as 'YYYY-MM-DD'."""
    d = datetime.fromisoformat(date_iso).date()
    return (d - timedelta(days=d.weekday())).isoformat()


def week_path(monday_iso):
    """Where a week of results lives for good: results/<its Monday>.html."""
    return f"results/{monday_iso}.html"


def _week_label(monday_iso):
    a = datetime.fromisoformat(monday_iso)
    return f'{a.strftime("%b %-d")} to {(a + timedelta(days=6)).strftime("%b %-d")}'


def _meters(items):
    """A meter list: one row per item with its name, a bar for the share and the figure beside it.
    items = [(name html, share 0..1, figure html, link or "", extra class)]. A row with a link is one
    big link (the weeks on the Results page); the bar drops under the name on a narrow screen."""
    rows = []
    for name, share, figure, href, cls in items:
        inner = (f'<span class="mn">{name}</span><span class="mb"><i style="width:{100 * max(0.0, min(1.0, share)):.0f}%"></i></span>'
                 f'<span class="mv">{figure}</span>')
        rows.append(f'<a class="mrow{cls}" href="{escape(href)}">{inner}</a>' if href else f'<div class="mrow{cls}">{inner}</div>')
    return f'<div class="mlist">{"".join(rows)}</div>'


def _by_week(graded):
    weeks = {}
    for r in graded:
        weeks.setdefault(week_start(r["date"]), []).append(r)
    return weeks


def _week_meters(graded, root="", current=""):
    """Every week of the season, newest first: how often the pick won, as a bar, with the record.
    A week links to its own page when that page exists; the week being shown is marked instead."""
    weeks = _by_week(graded)
    items = []
    for wk in sorted(weeks, reverse=True):
        w, l = _record(weeks[wk], "pick_correct")
        path = week_path(wk)
        items.append((f'{_week_label(wk)}<small>{w + l} game{"s" if w + l != 1 else ""}</small>', w / (w + l),
                      f'<b>{100 * w / (w + l):.0f}%</b>{w}-{l}', root + path if wk != current and _there(path) else "",
                      " cur" if wk == current else ""))
    return _meters(items)


def _day_blocks(by_date, dates, teams, root=""):
    from datetime import date as _d
    far = datetime.max.replace(tzinfo=config.CT)
    parts = []
    for d in dates:
        day = sorted(by_date[d], key=lambda r: tip_ct(r["when"]) or far, reverse=True)   # latest tip first
        dw, dl = _record(day, "pick_correct")
        label = _d.fromisoformat(d).strftime("%A, %b %-d")
        parts.append(f'<div class="day"><h2>{label}</h2><span>{dw}-{dl}</span></div>'
                     f'<div class="games">{"".join(_row(r, teams, final=True, root=root) for r in day)}</div>')
    return "".join(parts)


def _result_tiles(graded, season=True):
    """The record tiles above a list of results ('' while config.SHOW_RESULTS_STATS is off)."""
    if not config.SHOW_RESULTS_STATS or not graded:
        return ""
    pw, pl = _record(graded, "pick_correct")
    sw, sl = _record(graded, "strong_correct")
    hw, hl = _record(graded, "fh_correct")
    ou = [ou_result(r) for r in graded]
    ow, ol = ou.count("1"), ou.count("0")
    ups = [r for r in graded if upset(r)]
    uw, ul = _record(ups, "pick_correct")
    xw, xl = _record([r for r in ups if upset(r) == "ultra"], "pick_correct")
    errs = [abs(float(r["total_error"])) for r in graded if r["total_error"]]
    mae = f"{sum(errs) / len(errs):.1f}" if errs else "—"

    def pct(w, l):
        return f"{100 * w / (w + l):.0f}%" if w + l else "—"
    return (f'<div class="stats"><div class="stat"><b>{pw}-{pl}</b><span>all picks, {pct(pw, pl)}</span></div>'
            f'<div class="stat am"><b>{sw}-{sl}</b><span>strong, {pct(sw, sl)}</span></div>'
            f'<div class="stat am"><b>{ow}-{ol}</b><span>O/U plays, {pct(ow, ol)}</span></div>'
            f'<div class="stat up"><b>{uw}-{ul}</b><span>upset picks, {pct(uw, ul)}</span></div>'
            f'<div class="stat up"><b>{xw}-{xl}</b><span>ultra upsets, {pct(xw, xl)}</span></div>'
            f'<div class="stat"><b>{hw}-{hl}</b><span>first half, {pct(hw, hl)}</span></div>'
            f'<div class="stat"><b>{mae}</b><span>avg total miss</span></div></div>')


def results_page(rows, stamp, teams=None):
    """results.html: the season's record, the last RESULTS_DAYS game days in full, and every week of
    the season as one row (how often the pick won) linking to that week's own page.
    The page used to list every graded game of the season: 1.7 MB and 37,000 page elements three
    weeks in, on its way past 10 MB by March. Each game still has a permanent home, on its week's
    page (write_result_weeks). On a site that has no week pages yet every day stays listed here."""
    teams = teams or {}
    graded = [r for r in rows if r["pick_correct"] in ("0", "1")]
    hero = (f'<section class="hero"><div><h1>Season results</h1><p>Every pick is locked before tip-off and graded from the final score.</p></div>'
            f'{_result_tiles(graded)}</section>')
    if not graded:
        return page(RESULTS_TITLE, "results.html",
                    hero + '<div class="empty"><b>No graded games yet</b>Results appear the morning after each game day.</div>', stamp,
                    RESULTS_DESC)
    by_date = {}
    for r in graded:
        by_date.setdefault(r["date"], []).append(r)
    dates = sorted(by_date, reverse=True)
    weeks = note = ""
    if any(_there(week_path(w)) for w in _by_week(graded)):
        older = len(dates) - RESULTS_DAYS
        dates = dates[:RESULTS_DAYS]
        weeks = ('<div class="sect st" id="weeks"><h2>Week by week</h2><span>how often the pick won; tap a week for every game in it</span></div>'
                 + _week_meters(graded))
        if older > 0:
            note = (f'<p class="note">Showing the last {len(dates)} game days. Every earlier game is on its week’s page: '
                    '<a href="#weeks">week by week</a>.</p>')
    return page(RESULTS_TITLE, "results.html", hero + note + RESULT_CHIPS + _day_blocks(by_date, dates, teams) + weeks, stamp, RESULTS_DESC)


def results_week_page(monday, week_rows, teams=None, season=None, prev="", nxt=""):
    """One week of results at results/<monday>.html: every graded game of that week, for good.
    season = every graded row (for the week-by-week list under the games); prev / nxt = the Mondays
    of the weeks before and after that have a page. The "Updated" line carries the day after the
    week's last graded game, not the build time, so a finished week's page comes out byte for byte
    the same every morning and is not saved again."""
    teams = teams or {}
    root = "../"
    label = _week_label(monday)
    year = monday[:4]
    by_date = {}
    for r in week_rows:
        by_date.setdefault(r["date"], []).append(r)
    dates = sorted(by_date, reverse=True)
    w, l = _record(week_rows, "pick_correct")
    stamp = (datetime.fromisoformat(dates[0]) + timedelta(days=1)).strftime("%b %d, %Y")
    hero = (f'<section class="hero"><div><p class="crumb"><a href="{root}results.html">Results</a> &rsaquo; {escape(label)}</p>'
            f'<h1>Results, {escape(label)}</h1><p>Every pick of the week, locked before tip-off and '
            f'graded from the final score.</p></div>{_result_tiles(week_rows)}</section>')
    pager = ('<div class="pager">'
             + (f'<a href="{root}{week_path(prev)}">&lsaquo; {escape(_week_label(prev))}</a>' if prev else "<span></span>")
             + f'<a href="{root}results.html#weeks">All weeks</a>'
             + (f'<a href="{root}{week_path(nxt)}">{escape(_week_label(nxt))} &rsaquo;</a>' if nxt else "<span></span>") + '</div>')
    return page(f"College Basketball Results, {label}, {year} | {config.SITE_NAME}", "results.html",
                hero + RESULT_CHIPS + _day_blocks(by_date, dates, teams, root) + pager, stamp,
                f"Every college basketball prediction from {label}, {year}, graded against the final score: "
                f"the model had the winner in {w} of {w + l} games.",
                root=root, canonical=week_path(monday))


def write_result_weeks(rows, teams=None, docs=None):
    """Write the page of every week that has graded games. A page whose content has not changed is
    left alone (a finished week never changes again), so a build touches one or two files here.
    Returns the number of pages written."""
    docs = docs or DOCS
    weeks = _by_week([r for r in rows if r["pick_correct"] in ("0", "1")])
    order = sorted(weeks)
    paths = {week_path(w) for w in order}
    fresh = paths - COMING
    COMING.update(fresh)                       # the week pages link to each other: all of them are on the way
    n = 0
    try:
        for i, wk in enumerate(order):
            html = results_week_page(wk, weeks[wk], teams, prev=order[i - 1] if i else "",
                                     nxt=order[i + 1] if i + 1 < len(order) else "")
            p = docs / week_path(wk)
            p.parent.mkdir(parents=True, exist_ok=True)
            try:
                same = p.read_text(encoding="utf-8") == html
            except (OSError, UnicodeError):
                same = False
            if not same:
                p.write_text(html, encoding="utf-8")
                n += 1
    finally:
        COMING.difference_update(fresh)
    return n


def _bet_disc(b, teams, mini=False):
    if b["kind"] == "Total":
        return f'<div class="disc ou"><em>{"O" if b["side"] == "over" else "U"}</em></div>'
    tid, name = (b["home_id"], b["home"]) if b["side"] == "home" else (b["away_id"], b["away"])
    return _disc(_team(teams, tid, name))


def _bet_where(b, teams):
    t = tip_ct(b["when"])
    tip = t.strftime("%-I:%M %p") if t else "TBD"
    return (f'{escape(_short(teams, b["away_id"], b["away"]))} @ {escape(_short(teams, b["home_id"], b["home"]))}'
            f' \u00b7 {tip}')


def _single(i, b, teams, status="", live=False):
    """One row of the single-bet list. status = HTML for the right-hand column (default: model chance).
    live = add what the page's script needs to follow the game and grade the bet at the final (BETS_JS)."""
    import bets as B
    if not status:
        status = (f'<div class="pc"><b>{b["chance"] * 100:.0f}%</b><small><span class="mc">model chance, </span>'
                  f'+{b["edge"] * 100:.0f}<span class="mc"> pts</span> edge</small>'
                  f'<div class="bar2"><i style="width:{b["chance"] * 100:.0f}%"></i></div></div>')
    hooks = ""
    if live:
        a, h = _team(teams, b["away_id"], b["away"]), _team(teams, b["home_id"], b["home"])
        num = "" if b.get("num") in (None, "") else f'{float(b["num"]):g}'
        hooks = (f' data-ea="{escape(a["espn"])}" data-eh="{escape(h["espn"])}" data-kind="{escape(b["kind"])}"'
                 f' data-side="{escape(b["side"])}" data-num="{num}" data-res="{escape(b.get("result") or "")}"')
    return (f'<div class="bet{" " + b["result"] if b.get("result") else ""}"{hooks}><div class="rk">{i}</div>{_bet_disc(b, teams)}'
            f'<div class="bl"><b>{escape(b["label"])} <span style="color:var(--mute);font-weight:600">{B.fmt_odds(b["odds"])}</span></b>'
            f'<small>{_bet_where(b, teams)}</small></div>'
            f'<span class="kind {b["kind"]}">{"Moneyline" if b["kind"] == "ML" else b["kind"]}</span>{status}</div>')


def _from_book(b):
    """A bets.csv row as the dict the renderer expects."""
    r = dict(b)
    r["odds"], r["chance"], r["edge"] = int(b["odds"]), float(b["chance"]), float(b["edge"])
    return r


def _status(b, final=""):
    """Right-hand column of a locked bet: W / L / Push once it is graded (with the final score,
    "83-54" away-home, when the caller has it), otherwise the model's chance."""
    res = b.get("result")
    fin = f'<small class="fin">Final {escape(final)}</small>' if final else ""
    if res == "W":
        return f'<div class="pc"><span class="res W big">W</span>{fin}</div>'
    if res == "L":
        return f'<div class="pc"><span class="res L big">L</span>{fin}</div>'
    if res == "P":
        return f'<div class="pc"><span class="res P big">Push</span>{fin}</div>'
    return (f'<div class="pc"><b>{b["chance"] * 100:.0f}%</b><small>model chance</small>'
            f'<div class="bar2"><i style="width:{b["chance"] * 100:.0f}%"></i></div></div>')


# Today's locked bets grade themselves in the visitor's browser, from the same public scoreboard the
# Today page uses: the live score while a game is on, then W / L / Push the minute it goes final.
# Builds only happen a few times a day (and each one spends data-API calls), so without this an
# evening bet showed no result until the overnight build. The rules mirror bets.grade_bet; the
# builds still do the official grading, and a bet a build has already graded is left alone.
BETS_JS = r"""<script>
(()=>{
const box=document.getElementById('bets-live');if(!box)return;
const rows=[...box.querySelectorAll('.bet')],sub=document.getElementById('bets-sub'),day=box.dataset.day;
const et=back=>new Date(Date.now()-back*36e5).toLocaleDateString('en-CA',{timeZone:'America/New_York'});
const current=()=>day===et(0)||day===et(5);   // this slate's own day, or after midnight Eastern while its late games finish
if(!day||!current()||rows.every(r=>r.dataset.res))return;   // nothing left to follow
const API='https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard?groups=50&limit=500&dates=';
function grade(r,a,h){
 const k=r.dataset.kind,s=r.dataset.side,n=parseFloat(r.dataset.num)||0;
 const v=k==='Total'?(a+h-n)*(s==='over'?1:-1):(s==='home'?h-a:a-h)+(k==='Spread'?n:0);
 return v>0?'W':v<0?'L':'P'}
function tally(){let w=0,l=0,p=0,open=0;
 rows.forEach(r=>{const x=r.dataset.res;if(x==='W')w++;else if(x==='L')l++;else if(x==='P')p++;else open++});
 if(sub&&w+l+p){const rec=w+'-'+l+(p?'-'+p:'');sub.textContent=open?rec+' so far, '+open+' still to play':'final: '+rec}
 return open}
let busy=false,over=false;
async function poll(){
 if(busy||over||document.hidden)return;
 if(!current()){over=true;clearInterval(timer);return}
 busy=true;
 try{
  const j=await fetch(API+day.replace(/-/g,''),{cache:'no-store',...(AbortSignal.timeout?{signal:AbortSignal.timeout(20000)}:{})}).then(r=>r.json());
  const map={};
  for(const e of j.events||[]){const c=(e.competitions||[])[0];if(!c)continue;const sc={};
   c.competitors.forEach(p=>sc[p.team.id]=+p.score||0);const t=(c.status||e.status||{}).type||{};
   map[c.competitors.map(p=>p.team.id).sort().join('-')]={sc,state:t.state,done:t.completed===true,detail:t.shortDetail||t.detail||''}}
  rows.forEach(r=>{
   if(r.dataset.res||!r.dataset.ea||!r.dataset.eh)return;
   const m=map[[r.dataset.ea,r.dataset.eh].sort().join('-')],pc=r.querySelector('.pc');
   if(!m||!pc||m.state==='pre')return;
   const a=m.sc[r.dataset.ea]||0,h=m.sc[r.dataset.eh]||0;
   if(m.state==='in'){r.classList.add('is-live');
    pc.innerHTML='<b></b><small class="lvrow"><span class="livetag">LIVE</span><span class="clock"></span></small>';
    pc.querySelector('b').textContent=a+'-'+h;pc.querySelector('.clock').textContent=m.detail}
   else if(m.done){const g=grade(r,a,h);r.dataset.res=g;r.classList.remove('is-live');r.classList.add(g);
    pc.innerHTML='<span class="res '+g+' big">'+(g==='P'?'Push':g)+'</span><small class="fin"></small>';
    pc.querySelector('.fin').textContent='Final '+a+'-'+h}
   else if(!pc.querySelector('.off')){   // postponed or canceled: no result, say why
    const s=document.createElement('small');s.className='off';s.textContent=m.detail;pc.appendChild(s)}
  });
  if(!tally()){over=true;clearInterval(timer)}
 }catch(e){}finally{busy=false}
}
const timer=setInterval(poll,60000);poll();
document.addEventListener('visibilitychange',()=>{if(!document.hidden)poll()});
})();
</script>"""


CLV_MIN_BETS = 20        # the closing-line sentence appears once this many graded bets have a closing line


def _clv_note(clv):
    """One sentence on whether the lines moved the bets' way after they were posted, once there are
    enough bets for it to mean something. Beating the closing line is the earliest sign of a real
    edge; a record needs hundreds of bets to say the same thing."""
    if not clv or clv["n"] < CLV_MIN_BETS:
        return ""
    pts = clv["points"]
    way = "in the bets\u2019 favor" if pts > 0.005 else "against the bets" if pts < -0.005 else "either way"
    return (f' Closing lines: of {clv["n"]} graded spread and total bets, the line moved the bet\u2019s way after it was posted in '
            f'{clv["beat"]}, against it in {clv["worse"]} and not at all in {clv["same"]}, an average of {abs(pts):.1f} points {way}.')


def bets_page(best, date_label, stamp, teams=None, book=None, date_iso="", finals=None, clv=None):
    """finals = {(date, away_id, home_id): "83-54"} final scores (away-home) for graded games, shown
    under each graded bet's W / L. clv = bets.closing_value(...): how the lines moved after the bets
    were posted, or None."""
    import bets as B
    teams = teams or {}
    book = book or []
    finals = finals or {}

    def final_of(b):
        return finals.get((b["date"], str(b["away_id"]), str(b["home_id"])), "")
    today_book = [_from_book(b) for b in book if b["date"] == date_iso]
    past_dates = sorted({b["date"] for b in book if b["date"] < date_iso and b["result"]})
    yday = past_dates[-1] if past_dates else ""
    yday_book = [_from_book(b) for b in book if b["date"] == yday]

    def rec(w, l, p):
        return f"{w}-{l}" + (f"-{p}" if p else "")

    def pct(w, l):
        return f"{100 * w / (w + l):.0f}%" if w + l else "\u2014"
    yw, yl, yp = B.record(book, yday) if yday else (0, 0, 0)
    sw, sl, sp = B.record(book)
    stats = ""
    if sw + sl + sp:
        ylabel = "yesterday" if yday and date_iso and (datetime.fromisoformat(date_iso) - datetime.fromisoformat(yday)).days == 1 \
            else datetime.fromisoformat(yday).strftime("%a %b %-d").replace(" 0", " ") if yday else "last day"
        # the record alone flatters: at -110 a bet has to win 52.4% of the time to break even, so the
        # season's profit or loss in units (one unit a bet, at each bet's own price) sits beside it
        u = B.units(book)
        u_txt = ("+" if u > 0 else "\u2212" if u < 0 else "") + f"{abs(u):.1f}"
        stats = (f'<div class="stats"><div class="stat {"win" if yw > yl else "loss" if yl > yw else ""}"><b>{rec(yw, yl, yp)}</b>'
                 f'<span>top bets {escape(ylabel)}</span></div>'
                 f'<div class="stat am"><b>{rec(sw, sl, sp)}</b><span>season, {pct(sw, sl)}</span></div>'
                 f'<div class="stat {"win" if u > 0.05 else "loss" if u < -0.05 else ""}"><b>{u_txt}</b>'
                 f'<span>units, 1 a bet</span></div></div>')
    hero = ('<section class="hero"><div><h1>Best Bets</h1>'
            f'<p>{escape(date_label)}. The model\u2019s projections against the current lines. The top single bets lock in '
            f'each morning; each one shows the live score while its game is on and is graded the minute it ends. '
            f'Parlays rebuild before each time block from games that haven\u2019t tipped off. Times are Central.</p></div>{stats}</section>')
    singles = best["singles"]
    if today_book:
        done = sum(1 for b in today_book if b.get("result"))
        # "Nov 18, 2026 03:23 AM CT" -> "locked in at 3:23 AM CT" (this used to show the year as well)
        at = re.search(r"(\d{1,2}:\d{2} [AP]M(?: CT)?)$", today_book[0].get("locked_at") or "")
        sub = "locked in at " + escape(at.group(1).lstrip("0")) if at else "locked in"
        if done:
            tw, tl, tp = B.record([b for b in book if b["date"] == date_iso])
            sub = f"{rec(tw, tl, tp)} so far, {len(today_book) - done} still to play" if done < len(today_book) else f"final: {rec(tw, tl, tp)}"
        # these rows follow their games in the visitor's browser (BETS_JS): live score while a game is
        # on, W/L at the final, without waiting for the next build
        rows = "".join(_single(i, b, teams, _status(b, final_of(b)), live=True) for i, b in enumerate(today_book, 1))
        single_html = (f'<div class="sect"><h2>Today\u2019s top {len(today_book)} single bets</h2><span id="bets-sub">{sub}</span></div>'
                       f'<div class="singles" id="bets-live" data-day="{escape(date_iso)}">{rows}</div>')
    elif singles:
        rows = "".join(_single(i, b, teams) for i, b in enumerate(singles, 1))
        single_html = (f'<div class="sect"><h2>Top {len(singles)} single bets</h2><span>Preview, locks in once most lines are posted</span></div>'
                       f'<div class="singles">{rows}</div>')
    else:
        single_html = ('<div class="empty"><b>No qualifying bets right now</b>Lines usually post by late morning, '
                       'or every game today has already tipped off.</div>')
    if yday_book:
        ylab = datetime.fromisoformat(yday).strftime("%A, %b %-d")
        rows = "".join(_single(i, b, teams, _status(b, final_of(b))) for i, b in enumerate(yday_book, 1))
        single_html += (f'<div class="sect"><h2>{escape(ylab)}</h2><span>top bets went {rec(yw, yl, yp)}</span></div>'
                        f'<div class="singles past">{rows}</div>')
    cards = []
    for n, pl in best["parlays"].items():
        if not pl:
            cards.append(f'<div class="card none"><h3>{n}-leg parlay</h3>Only {best["pool"]} bet'
                         f'{"" if best["pool"] == 1 else "s"} qualify right now, not enough for {n} legs.</div>')
            continue
        legs = "".join(f'<li>{_bet_disc(b, teams)}<div><b>{escape(b["label"])}</b><small>{_bet_where(b, teams)}'
                       f' \u00b7 {B.fmt_odds(b["odds"])}</small></div><span class="p">{b["chance"] * 100:.0f}%</span></li>'
                       for b in pl["legs"])
        cards.append(f'<div class="card"><header><h3>{n}-leg parlay</h3><div class="od">{B.fmt_odds(pl["odds"])}</div>'
                     f'<div class="cs">Model chance <b>{pl["chance"] * 100:.1f}%</b> \u00b7 $10 pays <b>${10 * pl["decimal"]:,.2f}</b></div>'
                     f'</header><ol>{legs}</ol></div>')
    parlay_html = ('<div class="sect"><h2>Parlays</h2><span>The top bets, one per game</span></div>'
                   f'<div class="cards">{"".join(cards)}</div>')
    note = (f'<p class="note">How these are picked: each game\u2019s moneyline, spread and over/under are scored by the '
            f'model\u2019s chance of winning them, based on how far off its projections usually are. A bet needs at least a '
            f'{B.MIN_CHANCE * 100:.0f}% model chance and has to beat its price by {B.MIN_EDGE * 100:.0f}+ points; each game\u2019s best one makes the list, ranked by edge '
            f'(model chance minus the chance the odds imply). Spread and total bets assume the usual {B.fmt_odds(B.STD_ODDS)} odds, '
            'so check your book\u2019s price. Parlay chances treat the games as independent. These are model estimates, not sure things.</p>'
            f'<p class="note">Reading the record: at {B.fmt_odds(B.STD_ODDS)} a bet has to win {100 * B.break_even():.1f}% of the time just to break '
            'even, so a winning record can still lose money. The units figure counts one unit on every graded bet at its listed price.'
            + _clv_note(clv) + '</p>')
    short = _short_date(date_iso)
    return page(f'College Basketball Best Bets Today{", " + short if short else ""} | {config.SITE_NAME}', "bets.html",
                hero + single_html + parlay_html + note + (BETS_JS if today_book else ""), stamp,
                "Today\u2019s college basketball best bets from the model: the top single bets and 3, 6 and 8-leg parlays "
                "against the current lines, locked each morning and graded in public.")


LIVE_CSS = """
.lv-hero p{max-width:760px}
.lb{background:var(--panel);border:1px solid var(--line);border-radius:var(--r);padding:14px 18px;margin-bottom:12px;display:grid;
 grid-template-columns:1fr auto;gap:8px 18px;align-items:center;border-left:4px solid var(--line)}
.lb.hot{border-left-color:var(--amber)}.lb.strongbet{border-left-color:#ff5f6d}
.lb .teams{font:700 17px Barlow,sans-serif}.lb .teams small{display:block;color:var(--mute);font-weight:600;font-size:13px;margin-top:2px}
.lb .lsc{font:900 34px/1 'Big Shoulders Display',sans-serif;text-align:right}.lb .lsc small{display:block;font:600 12px Barlow,sans-serif;color:var(--mute);margin-top:2px}
.lb .call{grid-column:1/-1;display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.lb .tag{font:800 12px Barlow,sans-serif;letter-spacing:.8px;text-transform:uppercase;padding:5px 10px;border-radius:999px;background:#1c1c22;color:var(--mute)}
.lb .tag.bet{background:var(--amber);color:#1a1000}.lb .tag.ultra{background:linear-gradient(90deg,#ff5f6d,#f2a541);color:#16070a}
.lb .why2{grid-column:1/-1;color:#c9c9c4;font-size:14px;line-height:1.45}.lb .why2 b{color:var(--ink)}
.lb .meta2{grid-column:1/-1;color:var(--mute);font-size:12px}
.lvstate{color:var(--mute);font-size:13px;margin:0 0 14px}
"""

LIVE_JS = r"""<script>
(()=>{
const G=JSON.parse(document.getElementById('live-data').textContent);
const box=document.getElementById('live-list');const state=document.getElementById('live-state');
const API='https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard?groups=50&limit=500&dates=';
const SP=4, SPS=8, TO=6, TOS=11;   // points of edge for a lean / a strong call (spread, total)
function elapsed(st){ // minutes played, from ESPN period + clock
 const p=st.period||0; const m=/(\d+):(\d+)/.exec(st.displayClock||''); const left=m?(+m[1]+(+m[2])/60):0;
 if(p<=0)return 0; if(p===1)return 20-left; if(p===2)return 40-left; return 40+(p-2)*5-left;}
function fmt(x){return (x>0?'+':'\u2212')+Math.abs(x).toFixed(1).replace(/\.0$/,'')}
function render(list){
 if(!list.length){box.innerHTML='<div class="empty"><b>No games in progress</b>Live calls appear here once games tip off. The page refreshes itself every minute.</div>';return}
 box.innerHTML=list.map(x=>{
  const g=x.g;const cls=x.strength==='strong'?'lb strongbet':x.strength==='lean'?'lb hot':'lb';
  const tags=x.calls.map(c=>`<span class="tag ${c.strong?'ultra':'bet'}">${c.text}</span>`).join('')||'<span class="tag">No edge right now</span>';
  return `<div class="${cls}"><div class="teams">${g.away} @ ${g.home}<small>${x.clock}</small></div>
   <div class="lsc">${x.sa} - ${x.sh}<small>opened ${g.lineTxt}${g.ou?' \u00b7 O/U '+g.ou:''}</small></div>
   <div class="call">${tags}</div><div class="why2">${x.why}</div>
   <div class="meta2">Model now: ${g.home} ${fmt(x.projM)} \u00b7 projected total ${x.projT.toFixed(0)} \u00b7 ${x.min.toFixed(0)} of 40 min played</div></div>`}).join('');
}
let busy=false;
async function poll(){
 if(busy||document.hidden)return;busy=true;      // not in a background tab, and one request at a time
 try{
  const d=G.date.replace(/-/g,'');const j=await fetch(API+d,{cache:'no-store',...(AbortSignal.timeout?{signal:AbortSignal.timeout(20000)}:{})}).then(r=>r.json());
  const map={};for(const e of j.events||[]){const c=(e.competitions||[])[0];if(!c)continue;const sc={};c.competitors.forEach(p=>sc[p.team.id]=+p.score||0);
   const st=c.status||e.status;map[c.competitors.map(p=>p.team.id).sort().join('-')]={sc,state:st.type.state,detail:st.type.shortDetail||'',period:st.period,displayClock:st.displayClock}}
  const out=[];let live=0;
  for(const g of G.games){const m=map[[g.ea,g.eh].sort().join('-')];if(!m||m.state!=='in')continue;live++;
   const sa=m.sc[g.ea]||0,sh=m.sc[g.eh]||0,min=Math.min(40,Math.max(0.5,elapsed(m)));const left=Math.max(0,40-min);
   // live projection: what has happened + what the model expected for the rest of the game
   const projM=(sh-sa)+g.m*(left/40);          // home margin at the final
   const projT=(sa+sh)+g.t*(left/40);
   const calls=[];const whys=[];
   if(g.hl!==null){ // g.hl = opening home line (negative = home favored)
     const edge=projM-(-g.hl);                  // + means home is doing better than the opening number
     const favHome=g.hl<0;const fav=favHome?g.home:g.away,dog=favHome?g.away:g.home;const favAhead=favHome?(sh-sa):(sa-sh);
     const favEdge=favHome?edge:-edge;         // edge from the opening favorite's side
     const winsFav=favHome?projM>0:projM<0;
     if(favEdge>=SP){calls.push({text:`${fav} live (${winsFav?'ML or spread':'spread only'})`,strong:favEdge>=SPS});
       whys.push(`<b>${fav}</b> opened ${fmt(-Math.abs(g.hl))} and ${favAhead<0?'is trailing':'is only up '+favAhead}, but the model still projects a win by ${Math.abs(projM).toFixed(0)}. A live line on ${fav} should be much better than the opener.`)}
     else if(favEdge<=-SP){calls.push({text:`${dog} live (${winsFav?'spread only':'ML or spread'})`,strong:favEdge<=-SPS});
       whys.push(`The opener had <b>${fav}</b> ${fmt(-Math.abs(g.hl))}; with ${left.toFixed(0)} minutes left the model projects ${projM>0?g.home:g.away} by ${Math.abs(projM).toFixed(0)}. ${dog} on the live line is the play.`)}
   }
   if(g.ou){const te=projT-g.ou;
     if(te>=TO){calls.push({text:`Over ${g.ou} live`,strong:te>=TOS});whys.push(`Pace: ${sa+sh} points in ${min.toFixed(0)} minutes; projected total <b>${projT.toFixed(0)}</b> vs the opening ${g.ou}. If the live total still sits near the opener, the Over has value.`)}
     else if(te<=-TO){calls.push({text:`Under ${g.ou} live`,strong:te<=-TOS});whys.push(`Pace: ${sa+sh} points in ${min.toFixed(0)} minutes; projected total <b>${projT.toFixed(0)}</b> vs the opening ${g.ou}. If the live total still sits near the opener, the Under has value.`)}}
   const strength=calls.some(c=>c.strong)?'strong':calls.length?'lean':'';
   out.push({g,sa,sh,min,projM,projT,clock:m.detail,calls,why:whys.join(' ')||`Score is tracking the opening numbers. Nothing to take here yet.`,strength,score:Math.max(...calls.map(c=>c.strong?2:1),0)});
  }
  out.sort((a,b)=>b.score-a.score||Math.abs(b.projM)-Math.abs(a.projM));
  state.textContent=live?`${live} game${live===1?'':'s'} in progress \u00b7 scores from ESPN, refreshed every minute`:'No games in progress right now.';
  render(out);
 }catch(e){state.textContent='Could not reach the live score feed. Will retry.'}finally{busy=false}
}
poll();setInterval(poll,60000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)poll()});
})();
</script>"""


def live_page(rows, teams, stamp, date_iso, date_label):
    """Live calls: opening line vs what the model projects from the live score and clock."""
    teams = teams or {}
    games = []
    for r in rows:
        a, h = _team(teams, r["away_id"], r["away"]), _team(teams, r["home_id"], r["home"])
        if not (a["espn"] and h["espn"]):
            continue
        try:
            m = float(r["differential"]) * config.POINTS_PER_RATING * (1 if r["pick"] == r["home"] else -1)
            t = float(r["total"])
        except (TypeError, ValueError):
            continue
        hl = None
        if r.get("line_spread"):
            sp = float(r["line_spread"])
            hl = 0.0 if sp == 0 or not r.get("line_fav") else (-sp if r["line_fav"] == r["home"] else sp)
        line_txt = ("pick\u2019em" if hl == 0 else f'{_short(teams, r["home_id"] if hl < 0 else r["away_id"], r["line_fav"])} \u2212{abs(hl):g}') if hl is not None else "no line"
        games.append({"away": r["away"], "home": r["home"], "ea": a["espn"], "eh": h["espn"], "m": round(m, 1), "t": round(t, 1),
                      "hl": hl, "ou": float(r["line_total"]) if r.get("line_total") else None, "lineTxt": line_txt})
    data = json.dumps({"date": date_iso, "games": games})
    body = (f'<section class="hero lv-hero"><div><h1>Live calls</h1><p>{escape(date_label)}. For games in progress only: the opening '
            'line against what the model projects from the live score and the clock. When a favorite is trailing but the model '
            'still projects a win, or the pace is far off the total, the live line in your book is usually the better number. '
            'Check the live price before you bet; this page cannot see live odds.</p></div></section>'
            '<p class="lvstate" id="live-state">Loading live scores\u2026</p><div id="live-list"></div>'
            '<p class="note">How it works: projected final = what has already happened + the model\u2019s pre-game expectation for '
            f'the minutes left. A call needs {4}+ points of edge on the spread or {6}+ on the total; the red tag means double that. '
            'Model estimates, not guarantees.</p>'
            f'<script type="application/json" id="live-data">{data}</script>{LIVE_JS}')
    return page(f"Live College Basketball Scores vs the Model | {config.SITE_NAME}", "live.html", body, stamp,
                "Live college basketball betting calls: opening lines against the model's in-game projection.",
                head_extra=f"<style>{LIVE_CSS}</style>")


def write(index_html, results_html, bets_html="", docs=DOCS, stamp="", studio_html="", live_html=""):
    docs.mkdir(parents=True, exist_ok=True)
    if live_html:
        (docs / "live.html").write_text(live_html, encoding="utf-8")
    if studio_html:
        (docs / config.STUDIO_PAGE).write_text(studio_html, encoding="utf-8")
    (docs / "about.html").write_text(about_page(stamp), encoding="utf-8")
    (docs / "privacy.html").write_text(privacy_page(stamp), encoding="utf-8")
    (docs / "index.html").write_text(index_html, encoding="utf-8")
    (docs / "results.html").write_text(results_html, encoding="utf-8")
    if bets_html:
        (docs / "bets.html").write_text(bets_html, encoding="utf-8")
    (docs / ".nojekyll").write_text("", encoding="utf-8")
    # robots.txt is a public file, so it names nothing private: the posting page keeps itself out
    # of search with its own noindex tag, and listing it (or the clip) here would hand both
    # addresses to anyone who opens this file
    (docs / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {config.SITE_URL}/sitemap.xml\n", encoding="utf-8")
    # sitemap: what a search engine should spend its time on. The home page as the bare domain and the
    # daily pages, dated today; the rankings and every team page (rebuilt each morning); the method,
    # About and Privacy pages; and the game pages of the last GAME_PAGE_DAYS days, each dated the day
    # after its game (when its result went up). Older game pages stay on the site and stay linked
    # from Results and the team pages, but they are thin by nature (one finished game each), so they
    # are left out here and marked noindex by retire_old_games().
    today = _stamp_date(stamp)
    urls = [(site_url(p), today) for p in ("index.html", "live.html", "bets.html", "results.html")]
    if (docs / "rankings.html").exists():
        urls.append((site_url("rankings.html"), _file_date(docs / "rankings.html")))
    urls += [(site_url(p), "") for p in ("model.html", "about.html", "privacy.html") if (docs / p).exists()]
    for p in sorted((docs / "teams").glob("*.html")):
        urls.append((site_url("teams/" + p.name), _file_date(p)))
    for p in sorted((docs / "results").glob("*.html")):          # one page per week of graded games
        urls.append((site_url("results/" + p.name), _file_date(p)))
    floor = _games_floor(today)
    for p in sorted((docs / "games").glob("*/*.html")):
        if floor and p.parent.name < floor:
            continue
        rel = str(p.relative_to(docs)).replace("\\", "/")
        try:
            mod = (datetime.fromisoformat(p.parent.name) + timedelta(days=1)).date().isoformat()
        except ValueError:
            mod = ""
        urls.append((site_url(rel), min(mod, today) if mod and today else mod))
    (docs / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + "".join(f"<url><loc>{escape(u)}</loc>{f'<lastmod>{m}</lastmod>' if m else ''}</url>" for u, m in urls)
        + "</urlset>\n", encoding="utf-8")


GAME_PAGE_DAYS = 7      # a game page is listed in the sitemap, and open to search engines, for this many days


def _games_floor(today_iso):
    """The oldest game date still treated as fresh ('' when today's date is unknown: keep everything)."""
    try:
        days = int(getattr(config, "GAME_PAGE_DAYS", GAME_PAGE_DAYS))
        return (datetime.fromisoformat(today_iso) - timedelta(days=days)).date().isoformat()
    except (TypeError, ValueError):
        return ""


def _file_date(path):
    """The day a page was last written, read from its own "Updated ..." line ('' if it has none)."""
    try:
        m = re.search(r"<div>Updated ([^<]+)</div>", path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError):
        return ""
    return _stamp_date(m.group(1)) if m else ""


NOINDEX = '<meta name="robots" content="noindex,follow">'


def retire_old_games(docs=DOCS, today_iso="", last_run=""):
    """Mark the pages of games more than GAME_PAGE_DAYS old "noindex, follow". They stay on the site
    for anyone who follows a link, but a search engine is told not to list hundreds of one-game pages
    as if they were the substance of the site: that is the rankings, the team pages and the current
    games. Pages that old are never rebuilt, so the tag is added to the file once.
    last_run = the date this was last done: only the days that have crossed the line since then are
    opened (every older day the first time). Returns the number of pages changed."""
    floor = _games_floor(today_iso)
    if not floor:
        return 0
    done_to = _games_floor(last_run) if last_run else ""
    n = 0
    for folder in (docs / "games").glob("*"):
        if not folder.is_dir() or folder.name >= floor or (done_to and folder.name < done_to):
            continue
        for p in folder.glob("*.html"):
            try:
                html = p.read_text(encoding="utf-8")
                if 'name="robots"' in html or "<head>" not in html:
                    continue
                p.write_text(html.replace("<head>", "<head>" + NOINDEX, 1), encoding="utf-8")
                n += 1
            except (OSError, UnicodeError):                # one unreadable page is not worth a failed build
                continue
    return n


def fix_canonicals(docs=DOCS):
    """One-time repair for game pages written before Nov 17, 2026. Those pages named the Today
    or Results tab as their "canonical" address, which tells search engines the page is a copy
    and not to list it. Pages older than three days are never rebuilt, so this rewrites just that
    one tag (and the matching share address) in place. Returns the number of pages changed."""
    n = 0
    for p in (docs / "games").glob("*/*.html"):
        own = escape(site_url(str(p.relative_to(docs)).replace("\\", "/")))
        html = p.read_text(encoding="utf-8")
        new = re.sub(r'(<link rel="canonical" href=")[^"]*(")', lambda m: m.group(1) + own + m.group(2), html, count=1)
        new = re.sub(r'(<meta property="og:url" content=")[^"]*(")', lambda m: m.group(1) + own + m.group(2), new, count=1)
        if new != html:
            p.write_text(new, encoding="utf-8")
            n += 1
    return n


def _stamp_date(stamp):
    """'Nov 17, 2026 03:24 AM CT' -> '2026-11-17' ('' if the stamp is missing or in another shape)."""
    try:
        return datetime.strptime(" ".join((stamp or "").split()[:3]), "%b %d, %Y").date().isoformat()
    except ValueError:
        return ""
