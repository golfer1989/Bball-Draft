"""Builds index.html (Today's Picks) and results.html (Season Results).

Look: true black, a scoreboard-style predicted score in condensed numerals as the
centerpiece of every game row, team logos on a disc of each team's own color.
"""
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
@media (max-width:860px){
 .g{grid-template-columns:1fr auto 1fr;grid-template-areas:"time time time" "a s h" "line line line" "side side side";row-gap:10px;padding:14px}
 .mid{display:contents}.mid .score,.mid>div:first-child{grid-area:s}.line{grid-area:line}
 .time{grid-area:time}.time br{display:none}
 .team.a{grid-area:a;flex-direction:column;text-align:center;gap:6px}.team.h{grid-area:h;flex-direction:column;text-align:center;gap:6px}
 .score{font-size:38px}.side{grid-area:side;flex-direction:row;justify-content:space-between;align-items:center;flex-wrap:wrap}
 .nm b{font-size:15px;white-space:normal}.disc{flex-basis:46px;width:46px;height:46px}.disc img{width:32px;height:32px}
 .meter{width:90px}.stats{gap:18px}
}
@media (prefers-reduced-motion:no-preference){.g{animation:in .35s ease-out both}@keyframes in{from{opacity:0;transform:translateY(6px)}}}
"""

JS = """<script>
(()=>{
const games=[...document.querySelectorAll('.g')];
const box=document.querySelector('[data-date]');
let F='all',S='all';
function apply(){
 games.forEach(g=>{const t=F==='all'||g.classList.contains(F);
  const s=S==='all'||(S==='live'?g.classList.contains('is-live'):g.dataset.slot===S);g.hidden=!(t&&s)});
 document.querySelectorAll('.day').forEach(d=>{const n=d.nextElementSibling;const none=n&&[...n.children].every(g=>g.hidden);d.hidden=none;if(n)n.hidden=none});
 const any=games.some(g=>!g.hidden);
 document.querySelectorAll('[data-empty]').forEach(m=>{const k=m.dataset.empty;
  m.hidden=any||!((k===F&&S==='all')||(k==='slot'&&S!=='all'&&S!=='live'&&F==='all')||(k==='live'&&S==='live')||(k==='mix'&&F!=='all'&&S!=='all'))});
}
function pick(sel,attr,set){document.querySelectorAll(sel).forEach(c=>c.addEventListener('click',()=>{
 document.querySelectorAll(sel).forEach(x=>x.classList.toggle('on',x===c));set(c.dataset[attr]);apply()}))}
pick('.chip[data-f]','f',v=>F=v);pick('.chip[data-s]','s',v=>S=v);
const etDay=()=>new Date().toLocaleDateString('en-CA',{timeZone:'America/New_York'});
const isToday=box&&box.dataset.date===etDay();
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
            "abbr": (t.get("abbr") or name[:3]).upper()[:4], "color": _hex(t.get("color")),
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


def _row(r, teams, final=False):
    a, h = _team(teams, r["away_id"], r["away"]), _team(teams, r["home_id"], r["home"])
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
    live_attrs = "" if final else (
        f' data-slot="{slot_of(r["when"])}" data-ea="{escape(a["espn"])}" data-eh="{escape(h["espn"])}"'
        f' data-pick="{"h" if home_pick else "a"}"')
    return (f'<article class="g{" strong" if strong else ""}{" ou" if ou_play(r) else ""}'
            f'{" upset" if up else ""}{" ultra" if up == "ultra" else ""}" style="--pc:{pc}"{live_attrs}>'
            f'<div class="time">{_tip(r["when"])}{"<small>Neutral</small>" if r.get("neutral") == "1" else ""}</div>'
            f'<div class="team a{" lose" if lose_a else ""}">{_disc(a)}<div class="nm"><b>{escape(a["name"])}</b><span>{escape(a["mascot"])}</span></div></div>'
            f'{center}'
            f'<div class="team h{" lose" if lose_h else ""}">{_disc(h)}<div class="nm"><b>{escape(h["name"])}</b><span>{escape(h["mascot"])}</span></div></div>'
            f'<div class="side">{side}</div></article>')


def page(title, active, body, stamp):
    tabs = [("index.html", "Today"), ("results.html", "Results")]
    nav = "".join(f'<a href="{h}" class="{"on" if h == active else ""}">{t}</a>' for h, t in tabs)
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width,initial-scale=1"><meta name="color-scheme" content="dark">'
            f'<title>{escape(title)}</title>{FONTS}<style>{CSS}</style></head><body>'
            f'<header class="top"><div class="wrap"><a class="brand" href="index.html"><i></i>Bball Draft</a>'
            f'<nav>{nav}</nav></div></header><main class="wrap">{body}</main>'
            f'<footer class="wrap">Updated {escape(stamp)}</footer>{JS}</body></html>')


def today_page(rows, date_label, stamp, stats_note, teams=None, date_iso=""):
    teams = teams or {}
    n_strong = sum(1 for r in rows if r["strong_pick"])
    n_ou = sum(1 for r in rows if ou_play(r))
    n_up = sum(1 for r in rows if upset(r))
    hero = (f'<section class="hero"><div><h1>{escape(date_label)}</h1><p>{escape(stats_note)}. Times are Central.</p></div>'
            f'<div class="stats"><div class="stat"><b>{len(rows)}</b><span>games</span></div>'
            f'<div class="stat am"><b>{n_strong}</b><span>strong picks</span></div>'
            f'<div class="stat am"><b>{n_ou}</b><span>O/U plays</span></div>'
            f'<div class="stat up"><b>{n_up}</b><span>upset picks</span></div></div></section>')
    if not rows:
        body = hero + '<div class="empty"><b>No games today</b>Picks post here each morning on game days.</div>'
    else:
        chips = ('<div class="bar"><button class="chip on" data-f="all">All games</button>'
                 '<button class="chip" data-f="strong">Strong picks only</button>'
                 '<button class="chip" data-f="ou">O/U plays</button>'
                 '<button class="chip" data-f="upset">Upset picks</button></div>'
                 '<div class="empty" data-empty="strong" hidden><b>No strong picks</b>None of these games has a big enough edge.</div>'
                 '<div class="empty" data-empty="upset" hidden><b>No upset picks</b>The model agrees with every betting favorite today.</div>'
                 f'<div class="empty" data-empty="ou" hidden><b>No O/U plays</b>No projected total is {config.OU_EDGE_POINTS}+ points off the line.</div>')
        counts = {k: sum(1 for r in rows if slot_of(r["when"]) == k) for k, *_ in SLOTS}
        slot_chips = ('<div class="bar slots"><button class="chip on" data-s="all">All day<span class="n">'
                      f'{len(rows)}</span></button>'
                      + "".join(f'<button class="chip" data-s="{k}" data-hi="{hi}">{lab}<span class="n">{counts[k]}</span></button>'
                                for k, lab, lo, hi in SLOTS if counts[k])
                      + '<button class="chip livechip" data-s="live">Live now<span class="n">0</span></button></div>'
                      '<div class="empty" data-empty="slot" hidden><b>No games in this window</b>Pick another time block.</div>'
                      '<div class="empty" data-empty="live" hidden><b>Nothing live right now</b>Live games show up here with the score and clock.</div>'
                      '<div class="empty" data-empty="mix" hidden><b>Nothing here</b>No games match both filters in this time block.</div>')
        body = (hero + slot_chips + chips + f'<div class="games" data-date="{escape(date_iso)}">'
                + "".join(_row(r, teams) for r in rows) + "</div>")
    return page("Bball Draft - Today", "index.html", body, stamp)


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
        return page("Bball Draft - Results", "results.html",
                    hero + '<div class="empty"><b>No graded games yet</b>Results appear the morning after each game day.</div>', stamp)
    by_date = {}
    for r in graded:
        by_date.setdefault(r["date"], []).append(r)
    chips = ('<div class="bar"><button class="chip on" data-f="all">All games</button>'
             '<button class="chip" data-f="strong">Strong picks only</button>'
             '<button class="chip" data-f="ou">O/U plays</button>'
             '<button class="chip" data-f="upset">Upset picks</button></div>'
             '<div class="empty" data-empty="strong" hidden><b>No strong picks</b>No graded strong picks yet.</div>'
             '<div class="empty" data-empty="upset" hidden><b>No upset picks</b>No graded upset picks yet.</div>'
             '<div class="empty" data-empty="ou" hidden><b>No O/U plays</b>No graded over/under plays yet.</div>')
    parts = []
    from datetime import date as _d
    for d in sorted(by_date, reverse=True):
        day = by_date[d]
        dw, dl = _record(day, "pick_correct")
        label = _d.fromisoformat(d).strftime("%A, %b %-d")
        parts.append(f'<div class="day"><h2>{label}</h2><span>{dw}-{dl}</span></div>'
                     f'<div class="games">{"".join(_row(r, teams, final=True) for r in day)}</div>')
    return page("Bball Draft - Results", "results.html", hero + chips + "".join(parts), stamp)


def write(index_html, results_html, docs=DOCS):
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "index.html").write_text(index_html, encoding="utf-8")
    (docs / "results.html").write_text(results_html, encoding="utf-8")
    (docs / ".nojekyll").write_text("", encoding="utf-8")
