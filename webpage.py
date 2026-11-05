"""Builds index.html (Today's Picks) and results.html (Season Results).

Look: true black, a scoreboard-style predicted score in condensed numerals as the
centerpiece of every game row, team logos on a disc of each team's own color.
"""
import json
import re
from datetime import datetime
from html import escape
from pathlib import Path

import config

SLOTS = [("early", "Before 2 PM", 0, 14), ("aft", "2\u20135 PM", 14, 17),
         ("eve", "5\u20138 PM", 17, 20), ("late", "After 8 PM", 20, 24)]   # Central time

DOCS = Path(__file__).resolve().parent   # site pages live at the top of the repo

FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" '
         'href="https://fonts.gstatic.com" crossorigin><link href="https://fonts.googleapis.com/css2?'
         'family=Barlow:wght@400;500;600&family=Big+Shoulders+Display:wght@600;800;900&display=swap" rel="stylesheet">')

CSS = """
:root{--bg:#000;--panel:#0c0c0e;--panel2:#141418;--line:#222228;--ink:#f3f3f1;--mute:#8d8f97;--dim:#5c5e66;
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
 .top .wrap{gap:8px}.brand{font-size:20px}.brand i{width:18px;height:18px}nav{gap:0}nav a{padding:7px 8px;font-size:13px}
}
@media (prefers-reduced-motion:no-preference){.g{animation:in .35s ease-out both}@keyframes in{from{opacity:0;transform:translateY(6px)}}}
"""

JS = """<script>
(()=>{
const games=[...document.querySelectorAll('.g')];
const box=document.querySelector('[data-date]');
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
const etDay=()=>new Date().toLocaleDateString('en-CA',{timeZone:'America/New_York'});
const isToday=box&&box.dataset.date===etDay();
if(box&&box.dataset.date&&box.dataset.date<etDay()){ // last build was an earlier day
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
if(!isToday)return;
const liveChip=document.querySelector('.chip[data-s=live]');
async function poll(){
 try{
  const d=box.dataset.date.replace(/-/g,'');
  const j=await fetch('https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard?groups=50&limit=500&dates='+d,{cache:'no-store'}).then(r=>r.json());
  const map={};
  for(const e of j.events||[]){const c=(e.competitions||[])[0];if(!c)continue;const sc={};
   c.competitors.forEach(p=>sc[p.team.id]=p.score);const st=(c.status||e.status).type;
   map[c.competitors.map(p=>p.team.id).sort().join('-')]={sc,state:st.state,detail:st.shortDetail||st.detail||''}}
  let live=0,open=0;
  games.forEach(g=>{
   const m=map[[g.dataset.ea,g.dataset.eh].sort().join('-')];
   if(!m||m.state==='pre'){open++;return}
   const a=+m.sc[g.dataset.ea]||0,h=+m.sc[g.dataset.eh]||0,lv=g.querySelector('.lv');if(!lv)return;
   lv.hidden=false;lv.querySelector('.la').textContent=a;lv.querySelector('.lh').textContent=h;
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
  if(!open)clearInterval(timer);
 }catch(e){}
}
const timer=setInterval(poll,60000);poll();
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


def _line_pills(r, teams, final=False):
    """Market line under the predicted score: favorite and spread, then the over/under."""
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


def _row(r, teams, final=False, wu=None, link=True):
    a, h = _team(teams, r["away_id"], r["away"]), _team(teams, r["home_id"], r["home"])
    href = game_path(r) if link and r.get("date") else ""
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
                  f'</div>{_line_pills(r, teams)}</div>')
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
            f'<div class="team a{" lose" if lose_a else ""}">{_disc(a)}<div class="nm"><b>{escape(a["name"])}{_rk(a)}{_star(r["away_id"], a["name"])}</b><span>{escape(a["mascot"])}</span></div></div>'
            f'{center}'
            f'<div class="team h{" lose" if lose_h else ""}">{_disc(h)}<div class="nm"><b>{escape(h["name"])}{_rk(h)}{_star(r["home_id"], h["name"])}</b><span>{escape(h["mascot"])}</span></div></div>'
            f'<div class="side">{side}</div>{_why(wu, r["pick"], href) if wu else (f"<a class=gl href={href}>Breakdown &rarr;</a>" if final and href else "")}</article>')


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


def page(title, active, body, stamp, description="", root="", head_extra="", og_image=""):
    """root = relative path back to the site root ("../../" for games/<date>/x.html)."""
    tabs = [("index.html", "Today"), ("live.html", "Live"), ("bets.html", "Best Bets"), ("results.html", "Results")]
    nav = "".join(f'<a href="{root}{h}" class="{"on" if h == active else ""}">{t}</a>' for h, t in tabs)
    og_image = og_image or f"{config.SITE_URL}/og.png?v={_v(stamp)}"
    ads = (f'<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={escape(config.ADSENSE_CLIENT)}"'
           ' crossorigin="anonymous"></script>') if config.ADSENSE_CLIENT else ""
    desc = description or ("College basketball predictions from a statistical model: picks, projected scores, "
                           "betting-line edges and a public, locked-before-tipoff record.")
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width,initial-scale=1"><meta name="color-scheme" content="dark">'
            f'<title>{escape(title)}</title><meta name="description" content="{escape(desc)}">'
            f'<link rel="canonical" href="{config.SITE_URL}/{active}">'
            f'<meta property="og:type" content="website"><meta property="og:site_name" content="{escape(config.SITE_NAME)}">'
            f'<meta property="og:title" content="{escape(title)}"><meta property="og:description" content="{escape(desc)}">'
            f'<meta property="og:url" content="{config.SITE_URL}/{active}"><meta property="og:image" content="{og_image}">'
            f'<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">'
            f'<meta name="twitter:card" content="summary_large_image"><meta name="twitter:title" content="{escape(title)}">'
            f'<meta name="twitter:description" content="{escape(desc)}"><meta name="twitter:image" content="{og_image}">'
            f'<link rel="icon" href="{FAVICON}">{FONTS}{ads}{head_extra}<style>{CSS}</style></head><body>'
            f'<header class="top"><div class="wrap"><a class="brand" href="{root}index.html"><i></i>{escape(config.SITE_NAME)}</a>'
            f'<nav>{nav}</nav></div></header><main class="wrap">{body}{ad_slot()}</main>'
            f'<footer class="wrap"><div>Updated {escape(stamp)}</div>'
            f'<div class="links"><a href="{root}about.html">About the model</a><a href="{root}privacy.html">Privacy</a>'
            f'<span>For information and entertainment only, not betting advice. 21+. '
            f'Gambling problem? Call 1-800-GAMBLER.</span></div></footer>{JS}</body></html>')


def game_page(r, teams, wu, stamp, line_note=""):
    """A page of its own for one game: the model's call, the write-up, the line, and the result
    once the game is graded. Lives at games/<date>/<away>-vs-<home>.html and never goes away,
    so a search for "<away> vs <home> prediction" has something to land on."""
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
    row = _row(r, teams, final=final, wu=None, link=False)
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
            + '<p class="note">Every pick is locked before tip-off and graded from the final score. '
              '<a href="../../about.html">How the model works</a>.</p>')
    return page(title, "results.html" if final else "index.html", body, stamp, desc, root="../../", head_extra=head)


def studio_page(stamp, date_label, gotd=None, teams=None, wu=None, caption="", yesterday=None):
    """Private posting page: the day's clip, caption and share image in one place."""
    teams = teams or {}
    if gotd:
        pa, ph = predicted_score(gotd)
        card = gotd_card(gotd, teams, wu, pa, ph)
    else:
        card = '<div class="empty"><b>No games today</b>Nothing to post; the next clip renders overnight.</div>'
    rec = (f'<p class="note">Yesterday the picks went <b>{yesterday[0]}-{yesterday[1]}</b>; worth putting in the caption.</p>'
           if yesterday and sum(yesterday) else "")
    body = (f'<section class="hero"><div><h1>Posting studio</h1><p>{escape(date_label)}. This page is private: not linked, '
            'not indexed. Download, add a trending sound in the app, paste the caption, post.</p></div></section>'
            + card + clip_box(caption) + rec +
            '<div class="clip"><div><b>Share image</b><span>The link preview picture for X, Reddit and Discord posts.</span></div>'
            '<div class="cb"><a class="btn ghost" href="og.png" download="tipoffedge-today.png">Download image</a></div></div>'
            '<p class="note">Routine: post the clip at the same time each day, an hour or two before the first tip-off. '
            'Reply to comments in the first hour. Same clip to TikTok, Instagram Reels and YouTube Shorts.</p>')
    html = page(f"{config.SITE_NAME} - Studio", config.STUDIO_PAGE, body, stamp, "Private posting page.",
                head_extra='<meta name="robots" content="noindex,nofollow">')
    return html


def about_page(stamp):
    body = (f'<section class="hero"><div><h1>About the model</h1><p>What {escape(config.SITE_NAME)} is and how the numbers are made.</p></div></section>'
            '<div class="prose">'
            f'<p>{escape(config.SITE_NAME)} publishes college basketball predictions from a statistical model, every game day, '
            'all season. It started as a spreadsheet and now runs automatically.</p>'
            '<h2>How a prediction is made</h2>'
            '<p>Each Division I team gets an <b>offense</b> and a <b>defense</b> rating built from the four factors of '
            'basketball: shooting, turnovers, offensive rebounding and free throws, for the team and for what its opponents '
            'manage against it. The rating is then adjusted for <b>strength of schedule</b>, measured from actual game '
            'results so a team that has played tough opponents gets credit for it, and the home team gets a <b>home-court</b> '
            'edge (none at neutral sites). Early in the season last year\u2019s numbers fade out as each team plays games.</p>'
            '<p>The gap between the two ratings becomes a projected margin and a projected score. A <b>strong pick</b> is a game '
            'where that gap is large. An <b>upset pick</b> is one where the model disagrees with the betting favorite. An '
            '<b>O/U play</b> is a game where the model\u2019s projected total is well off the posted over/under.</p>'
            '<h2>Best Bets</h2>'
            '<p>The Best Bets page compares the model to the current betting lines and lists the single bets and parlays where '
            'the model\u2019s chance of winning beats the price. The top single bets lock in each morning and are graded from '
            'the final score, so the record is what the page actually showed, not a highlight reel.</p>'
            '<h2>The record is public</h2>'
            '<p>Every pick is written down before tip-off and never changed. The Results page shows each graded game with the '
            'projected and actual scores. No pick is ever removed.</p>'
            '<h2>Data</h2>'
            '<p>Team statistics, schedules, scores and betting lines come from CollegeBasketballData. Live scores on the Today '
            'page come from ESPN. Team logos belong to the schools.</p>'
            '<h2>Please read this part</h2>'
            '<p>Everything here is for information and entertainment. It is not betting advice, and a model that is right '
            'two-thirds of the time is wrong one game in three. Never bet money you can\u2019t afford to lose. You must be of '
            'legal age to gamble where you live. If gambling is a problem for you or someone you know, call or text '
            '1-800-GAMBLER (US).</p>'
            '</div>')
    return page(f"{config.SITE_NAME} - About", "about.html", body, stamp,
                f"How the {config.SITE_NAME} college basketball model makes its predictions, and how its record is kept.")


def privacy_page(stamp):
    body = ('<section class="hero"><div><h1>Privacy</h1><p>Short version: this site keeps no accounts and collects nothing itself.</p></div></section>'
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
            '<p>On game days the Today page asks ESPN for live scores from your browser, and the pages load fonts from Google '
            'Fonts. Those services see your IP address in the ordinary way any web request does.</p>'
            '<h2>Hosting</h2>'
            '<p>The pages are hosted on GitHub Pages, which keeps standard server logs. See '
            '<a href="https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement">GitHub\u2019s privacy statement</a>.</p>'
            '<h2>Your browser\u2019s storage</h2>'
            '<p>The site stores nothing in your browser beyond what the ad and font services above set.</p>'
            '<h2>Contact</h2>'
            f'<p>Questions about this page can be sent through the site\u2019s GitHub repository.</p>'
            '</div>')
    return page(f"{config.SITE_NAME} - Privacy", "privacy.html", body, stamp, f"Privacy policy for {config.SITE_NAME}.")


def clip_box(caption):
    """Download + caption for the day's TikTok/Reels clip (shown inside the Game of the Day card)."""
    if not caption:
        return ""
    return ('<div class="clip"><div><b>Today\u2019s clip</b><span>12-second vertical video for TikTok, Reels and Shorts. '
            'Add a trending sound in the app when you post.</span></div>'
            '<div class="cb"><a class="btn" href="daily.mp4" download="tipoffedge-daily.mp4">Download clip</a>'
            f'<button class="btn ghost" data-copy>Copy caption</button></div><textarea hidden>{escape(caption)}</textarea></div>')


def gotd_card(r, teams, wu, pa, ph, caption=""):
    """The marquee matchup at the top of the Today page."""
    a, h = _team(teams, r["away_id"], r["away"]), _team(teams, r["home_id"], r["home"])
    ra, rh = (wu or {}).get("away_rank"), (wu or {}).get("home_rank")
    home_pick = r["pick"] == r["home"]
    t = tip_ct(r["when"])
    tip = t.strftime("%-I:%M %p") + " CT" if t else "TBD"
    pills = _line_pills(r, teams)
    reasons = "".join(f"<li>{escape(x)}</li>" for x in (wu or {}).get("lines", [])[:5])

    def side(team, rk, cls, lose):
        return (f'<div class="gt {cls}{" lose" if lose else ""}">{_disc(team)}<div class="gn">'
                f'{f"<small>#{rk}</small>" if rk else ""}<b>{escape(team["name"])}</b><span>{escape(team["mascot"])}</span></div></div>')
    flag = ('<span class="flag">Strong pick</span>' if r.get("strong_pick") else "")
    return (f'<section class="gotd" style="--pc:{(h if home_pick else a)["vivid"]}">'
            f'<div class="gh"><span class="kicker">Game of the day</span><span class="gtip">{escape(tip)}'
            f'{" &middot; Neutral site" if r.get("neutral") == "1" else ""}</span></div>'
            f'<div class="gbody">{side(a, ra, "a", home_pick)}'
            f'<div class="gmid"><div class="gscore"><span class="{"l" if home_pick else "w"}">{pa}</span><span class="dash"></span>'
            f'<span class="{"w" if home_pick else "l"}">{ph}</span></div><div class="gpick">{flag}Model pick: <b>{escape(r["pick"])}</b></div>{pills}</div>'
            f'{side(h, rh, "h", not home_pick)}</div>'
            f'{f"<ul class=greasons>{reasons}</ul>" if reasons else ""}</section>')


LEGEND = ('<details class="legend"><summary>How to read this page</summary><div class="lg">'
          '<div><b>Predicted score</b>The model\u2019s projected final. The bigger number is the pick.</div>'
          '<div><b>Edge bar</b>How far apart the two teams rate. A full bar is a lopsided matchup.</div>'
          '<div><b><span class="flag">Strong pick</span></b>The rating gap is big enough that the model has historically been right about 80% of the time.</div>'
          '<div><b><span class="flag up">Upset pick</span></b>The model picks the team the betting market has as the underdog. '
          '<span class="flag ultra">Ultra upset</span> is an upset pick that is also a strong pick.</div>'
          '<div><b>Line</b>The sportsbook favorite and spread, and the over/under. An orange O/U pill with '
          '<b style="display:inline;color:var(--amber)">Over</b> or <b style="display:inline;color:var(--amber)">Under</b> marks a game where '
          f'the model\u2019s total is {config.OU_EDGE_POINTS}+ points off the line.</div>'
          '<div><b>#12</b>Where a team ranks in the model among all Division I teams.</div>'
          '<div><b>Why ...?</b>Tap it under any game for the reasons behind the pick, in plain English.</div>'
          '<div><b>1H</b>First-half pick, from each team\u2019s first-half scoring in its last three games.</div>'
          '</div></details>')


def today_page(rows, date_label, stamp, stats_note, teams=None, date_iso="", n_final=0, writeups=None, yesterday=None,
               gotd=None, caption=""):
    teams = teams or {}
    writeups = writeups or {}
    gotd_html = ""
    if gotd:
        pa, ph = predicted_score(gotd)
        gotd_html = gotd_card(gotd, teams, writeups.get(gotd.get("game_key")), pa, ph, caption)
    n_strong = sum(1 for r in rows if r["strong_pick"])
    n_ou = sum(1 for r in rows if ou_play(r))
    n_up = sum(1 for r in rows if upset(r))
    done_note = (f' <a class="donelink" href="results.html">{n_final} finished game{"s" if n_final != 1 else ""}'
                 ' now on Results &rarr;</a>') if n_final else ""
    hero = (f'<section class="hero"><div><h1>{escape(date_label)}</h1><p>{escape(stats_note)}. Times are Central.{done_note}</p></div>'
            f'<div class="stats"><div class="stat"><b>{len(rows)}</b><span>games</span></div>'
            f'<div class="stat am"><b>{n_strong}</b><span>strong picks</span></div>'
            f'<div class="stat am"><b>{n_ou}</b><span>O/U plays</span></div>'
            f'<div class="stat up"><b>{n_up}</b><span>upset picks</span></div>'
            + (f'<div class="stat {"win" if yesterday[0] >= yesterday[1] else "loss"}"><b>{yesterday[0]}-{yesterday[1]}</b><span>yesterday</span></div>'
               if yesterday and config.SHOW_RESULTS_STATS and sum(yesterday) else "")
            + '</div></section>')
    if not rows and n_final:
        body = hero + ('<div class="empty"><b>All of today\'s games are final</b>'
                       'See how the picks did on the <a class="donelink" href="results.html">Results</a> page.</div>')
    elif not rows:
        body = hero + '<div class="empty"><b>No games today</b>Picks post here each morning on game days.</div>'
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
                + "".join(_row(r, teams, wu=writeups.get(r.get("game_key"))) for r in rows) + "</div>")
    return page(f"{config.SITE_NAME} - Today", "index.html", body, stamp)


def _record(rows, col):
    g = [r for r in rows if r.get(col) in ("0", "1")]
    w = sum(1 for r in g if r[col] == "1")
    return w, len(g) - w


def results_page(rows, stamp, teams=None):
    teams = teams or {}
    graded = [r for r in rows if r["pick_correct"] in ("0", "1")]
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

    hero = (f'<section class="hero"><div><h1>Season results</h1><p>Every pick is locked before tip-off and graded from the final score.</p></div>'
            f'<div class="stats"><div class="stat"><b>{pw}-{pl}</b><span>all picks, {pct(pw, pl)}</span></div>'
            f'<div class="stat am"><b>{sw}-{sl}</b><span>strong, {pct(sw, sl)}</span></div>'
            f'<div class="stat am"><b>{ow}-{ol}</b><span>O/U plays, {pct(ow, ol)}</span></div>'
            f'<div class="stat up"><b>{uw}-{ul}</b><span>upset picks, {pct(uw, ul)}</span></div>'
            f'<div class="stat up"><b>{xw}-{xl}</b><span>ultra upsets, {pct(xw, xl)}</span></div>'
            f'<div class="stat"><b>{hw}-{hl}</b><span>first half, {pct(hw, hl)}</span></div>'
            f'<div class="stat"><b>{mae}</b><span>avg total miss</span></div></div></section>')
    if not config.SHOW_RESULTS_STATS:          # record totals switched off in config.py for now
        hero = re.sub(r'<div class="stats">.*</div></section>$', '</section>', hero)
    if not graded:
        return page(f"{config.SITE_NAME} - Results", "results.html",
                    hero + '<div class="empty"><b>No graded games yet</b>Results appear the morning after each game day.</div>', stamp)
    by_date = {}
    for r in graded:
        by_date.setdefault(r["date"], []).append(r)
    chips = ('<div class="bar"><button class="chip on" data-f="all">All games</button>'
             '<button class="chip favchip" data-f="fav">\u2605 My teams<span class="n">0</span></button>'
             '<button class="chip" data-f="strong">Strong picks only</button>'
             '<button class="chip" data-f="ou">O/U plays</button>'
             '<button class="chip" data-f="upset">Upset picks</button></div>'
             '<div class="empty" data-empty="strong" hidden><b>No strong picks</b>No graded strong picks yet.</div>'
             '<div class="empty" data-empty="upset" hidden><b>No upset picks</b>No graded upset picks yet.</div>'
             '<div class="empty" data-empty="fav" hidden><b>No results for your teams yet</b>Tap the \u2606 next to any team to add it to My teams.</div>'
             '<div class="empty" data-empty="ou" hidden><b>No O/U plays</b>No graded over/under plays yet.</div>')
    parts = []
    from datetime import date as _d
    far = datetime.max.replace(tzinfo=config.CT)
    for d in sorted(by_date, reverse=True):
        day = sorted(by_date[d], key=lambda r: tip_ct(r["when"]) or far, reverse=True)   # latest tip first
        dw, dl = _record(day, "pick_correct")
        label = _d.fromisoformat(d).strftime("%A, %b %-d")
        parts.append(f'<div class="day"><h2>{label}</h2><span>{dw}-{dl}</span></div>'
                     f'<div class="games">{"".join(_row(r, teams, final=True) for r in day)}</div>')
    return page(f"{config.SITE_NAME} - Results", "results.html", hero + chips + "".join(parts), stamp)


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


def _single(i, b, teams, status=""):
    """One row of the single-bet list. status = HTML for the right-hand column (default: model chance)."""
    import bets as B
    if not status:
        status = (f'<div class="pc"><b>{b["chance"] * 100:.0f}%</b><small><span class="mc">model chance, </span>'
                  f'+{b["edge"] * 100:.0f}<span class="mc"> pts</span> edge</small>'
                  f'<div class="bar2"><i style="width:{b["chance"] * 100:.0f}%"></i></div></div>')
    return (f'<div class="bet{" " + b["result"] if b.get("result") else ""}"><div class="rk">{i}</div>{_bet_disc(b, teams)}'
            f'<div class="bl"><b>{escape(b["label"])} <span style="color:var(--mute);font-weight:600">{B.fmt_odds(b["odds"])}</span></b>'
            f'<small>{_bet_where(b, teams)}</small></div>'
            f'<span class="kind {b["kind"]}">{"Moneyline" if b["kind"] == "ML" else b["kind"]}</span>{status}</div>')


def _from_book(b):
    """A bets.csv row as the dict the renderer expects."""
    r = dict(b)
    r["odds"], r["chance"], r["edge"] = int(b["odds"]), float(b["chance"]), float(b["edge"])
    return r


def _status(b):
    res = b.get("result")
    if res == "W":
        return '<div class="pc"><span class="res W big">W</span></div>'
    if res == "L":
        return '<div class="pc"><span class="res L big">L</span></div>'
    if res == "P":
        return '<div class="pc"><span class="res P big">Push</span></div>'
    return (f'<div class="pc"><b>{b["chance"] * 100:.0f}%</b><small>model chance</small>'
            f'<div class="bar2"><i style="width:{b["chance"] * 100:.0f}%"></i></div></div>')


def bets_page(best, date_label, stamp, teams=None, book=None, date_iso=""):
    import bets as B
    teams = teams or {}
    book = book or []
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
        stats = (f'<div class="stats"><div class="stat {"win" if yw > yl else "loss" if yl > yw else ""}"><b>{rec(yw, yl, yp)}</b>'
                 f'<span>top bets {escape(ylabel)}</span></div>'
                 f'<div class="stat am"><b>{rec(sw, sl, sp)}</b><span>season, {pct(sw, sl)}</span></div></div>')
    hero = ('<section class="hero"><div><h1>Best Bets</h1>'
            f'<p>{escape(date_label)}. The model\u2019s projections against the current lines. The top single bets lock in '
            f'each morning and are graded from the final score; parlays rebuild before each time block from games that '
            f'haven\u2019t tipped off. Times are Central.</p></div>{stats}</section>')
    singles = best["singles"]
    if today_book:
        done = sum(1 for b in today_book if b.get("result"))
        sub = ("locked in at " + escape(today_book[0]["locked_at"].split(", ")[-1]) if "locked_at" in today_book[0] else "locked in")
        if done:
            tw, tl, tp = B.record([b for b in book if b["date"] == date_iso])
            sub = f"{rec(tw, tl, tp)} so far, {len(today_book) - done} still to play" if done < len(today_book) else f"final: {rec(tw, tl, tp)}"
        rows = "".join(_single(i, b, teams, _status(b)) for i, b in enumerate(today_book, 1))
        single_html = (f'<div class="sect"><h2>Today\u2019s top {len(today_book)} single bets</h2><span>{sub}</span></div>'
                       f'<div class="singles">{rows}</div>')
    elif singles:
        rows = "".join(_single(i, b, teams) for i, b in enumerate(singles, 1))
        single_html = (f'<div class="sect"><h2>Top {len(singles)} single bets</h2><span>Preview, locks in once most lines are posted</span></div>'
                       f'<div class="singles">{rows}</div>')
    else:
        single_html = ('<div class="empty"><b>No qualifying bets right now</b>Lines usually post by late morning, '
                       'or every game today has already tipped off.</div>')
    if yday_book:
        ylab = datetime.fromisoformat(yday).strftime("%A, %b %-d")
        rows = "".join(_single(i, b, teams, _status(b)) for i, b in enumerate(yday_book, 1))
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
            'so check your book\u2019s price. Parlay chances treat the games as independent. These are model estimates, not sure things.</p>')
    return page(f"{config.SITE_NAME} - Best Bets", "bets.html", hero + single_html + parlay_html + note, stamp)


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
async function poll(){
 try{
  const d=G.date.replace(/-/g,'');const j=await fetch(API+d,{cache:'no-store'}).then(r=>r.json());
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
 }catch(e){state.textContent='Could not reach the live score feed. Will retry.'}
}
poll();setInterval(poll,60000);
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
    return page(f"{config.SITE_NAME} - Live", "live.html", body, stamp,
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
    (docs / "robots.txt").write_text(f"User-agent: *\nDisallow: /{config.STUDIO_PAGE}\nDisallow: /daily.mp4\nAllow: /\n"
                                     f"Sitemap: {config.SITE_URL}/sitemap.xml\n", encoding="utf-8")
    pages = ["index.html", "live.html", "bets.html", "results.html", "about.html", "privacy.html"]
    pages += sorted(str(p.relative_to(docs)).replace("\\", "/") for p in (docs / "games").glob("*/*.html"))
    (docs / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + "".join(f"<url><loc>{config.SITE_URL}/{p}</loc></url>" for p in pages) + "</urlset>\n", encoding="utf-8")
