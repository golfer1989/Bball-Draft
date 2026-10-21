"""Builds docs/index.html (Today's Picks) and docs/results.html (Season Results)."""
from html import escape
from pathlib import Path

DOCS = Path(__file__).resolve().parent   # site pages live at the top of the repo

CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#16181d;--mute:#6b7280;--line:#e5e7eb;--acc:#1d4ed8;--good:#15803d;--bad:#b91c1c;--hi:#eef4ff}
@media (prefers-color-scheme:dark){:root{--bg:#0f1115;--card:#171a21;--ink:#e8eaed;--mute:#9aa0aa;--line:#2a2f3a;--acc:#7aa2ff;--good:#4ade80;--bad:#f87171;--hi:#1b2333}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
header{background:var(--card);border-bottom:1px solid var(--line);padding:14px 16px}
.wrap{max-width:1180px;margin:0 auto;padding:0 16px}
h1{font-size:18px;margin:0 0 8px}nav a{margin-right:18px;color:var(--mute);text-decoration:none;font-weight:600;padding-bottom:6px}
nav a.on{color:var(--acc);border-bottom:2px solid var(--acc)}
.meta{color:var(--mute);font-size:12px;margin:12px 0}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin:14px 0}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.tile .k{color:var(--mute);font-size:12px;text-transform:uppercase;letter-spacing:.04em}
.tile .v{font-size:24px;font-weight:700;font-variant-numeric:tabular-nums}.tile .s{color:var(--mute);font-size:12px}
.scroll{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:10px;margin-bottom:24px}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
th,td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}
th{font-size:12px;color:var(--mute);font-weight:600;background:var(--card);position:sticky;top:0}
td.n,th.n{text-align:right}tr.strong td{background:var(--hi)}
.pick{font-weight:700}.ok{color:var(--good);font-weight:700}.no{color:var(--bad);font-weight:700}
.badge{display:inline-block;font-size:11px;font-weight:700;padding:1px 7px;border-radius:99px;background:var(--acc);color:var(--card)}
h2{font-size:15px;margin:22px 0 8px}.empty{padding:28px;text-align:center;color:var(--mute)}
"""


def page(title, active, body, stamp):
    tabs = [("index.html", "Today's Picks"), ("results.html", "Season Results")]
    nav = "".join(f'<a href="{h}" class="{"on" if h == active else ""}">{t}</a>' for h, t in tabs)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)}</title>
<style>{CSS}</style></head><body>
<header><div class="wrap"><h1>CBB Model</h1><nav>{nav}</nav></div></header>
<main class="wrap"><div class="meta">Updated {escape(stamp)}</div>{body}</main></body></html>"""


def _f(v, nd=3):
    try:
        return f"{float(v):.{nd}f}"
    except (TypeError, ValueError):
        return "—"


def _tip(when):
    """'Jan 21, 2026 6:00 PM ET' -> '6:00 PM'"""
    parts = when.replace(" ET", "").split()
    return " ".join(parts[-2:]) if len(parts) >= 2 and parts[-1] in ("AM", "PM") else when


def today_page(rows, date_label, stamp, stats_note):
    if not rows:
        body = f'<div class="scroll"><div class="empty">No games on {escape(date_label)}</div></div>'
    else:
        trs = []
        for r in rows:
            strong = bool(r["strong_pick"])
            trs.append(
                f'<tr class="{"strong" if strong else ""}"><td>{escape(_tip(r["when"]))}</td>'
                f'<td>{escape(r["away"])}</td><td>{escape(r["home"])}</td>'
                f'<td class="n">{_f(r["away_rating"])}</td><td class="n">{_f(r["home_rating"])}</td>'
                f'<td class="pick">{escape(r["pick"])}</td><td class="n">{_f(r["differential"])}</td>'
                f'<td>{"<span class=badge>STRONG</span>" if strong else ""}</td>'
                f'<td class="n">{_f(r["total"], 1)}</td>'
                f'<td>{escape(r["fh_pick"] or "—")}</td><td class="n">{_f(r["fh_margin"], 1)}</td></tr>')
        n_strong = sum(1 for r in rows if r["strong_pick"])
        body = (f'<div class="tiles"><div class="tile"><div class="k">Games</div><div class="v">{len(rows)}</div>'
                f'<div class="s">{escape(date_label)}</div></div><div class="tile"><div class="k">Strong picks</div>'
                f'<div class="v">{n_strong}</div><div class="s">{escape(stats_note)}</div></div></div>'
                '<div class="scroll"><table><thead><tr><th>Tip (ET)</th><th>Away</th><th>Home</th>'
                '<th class="n">Away</th><th class="n">Home</th><th>Pick</th><th class="n">Differential</th>'
                '<th>Strong</th><th class="n">Total</th><th>1H Pick</th><th class="n">1H Margin</th></tr></thead>'
                f'<tbody>{"".join(trs)}</tbody></table></div>')
    return page("CBB Model - Today's Picks", "index.html", body, stamp)


def _record(rows, col):
    g = [r for r in rows if r[col] in ("0", "1")]
    w = sum(1 for r in g if r[col] == "1")
    return w, len(g) - w


def results_page(rows, stamp):
    graded = [r for r in rows if r["pick_correct"] in ("0", "1")]
    pw, pl = _record(graded, "pick_correct")
    sw, sl = _record(graded, "strong_correct")
    hw, hl = _record(graded, "fh_correct")
    errs = [abs(float(r["total_error"])) for r in graded if r["total_error"]]
    mae = sum(errs) / len(errs) if errs else None

    def pct(w, l):
        return f"{100 * w / (w + l):.1f}%" if w + l else "—"

    tiles = (f'<div class="tiles"><div class="tile"><div class="k">All picks</div><div class="v">{pw}-{pl}</div>'
             f'<div class="s">{pct(pw, pl)}</div></div><div class="tile"><div class="k">Strong picks</div>'
             f'<div class="v">{sw}-{sl}</div><div class="s">{pct(sw, sl)}</div></div>'
             f'<div class="tile"><div class="k">1H picks</div><div class="v">{hw}-{hl}</div>'
             f'<div class="s">{pct(hw, hl)}</div></div>'
             f'<div class="tile"><div class="k">Total, avg miss</div><div class="v">{_f(mae, 1)}</div>'
             f'<div class="s">points</div></div></div>')
    if not graded:
        return page("CBB Model - Season Results", "results.html",
                    tiles + '<div class="scroll"><div class="empty">No graded games yet</div></div>', stamp)
    by_date = {}
    for r in graded:
        by_date.setdefault(r["date"], []).append(r)
    sections = []
    for d in sorted(by_date, reverse=True):
        day = by_date[d]
        dw, dl = _record(day, "pick_correct")
        trs = []
        for r in day:
            ok = r["pick_correct"] == "1"
            sc = r["strong_correct"]
            hc = r.get("fh_correct", "")
            trs.append(
                f'<tr class="{"strong" if r["strong_pick"] else ""}"><td>{escape(r["away"])}</td>'
                f'<td>{escape(r["home"])}</td><td class="n">{r["away_pts"]}-{r["home_pts"]}</td>'
                f'<td class="pick">{escape(r["pick"])}</td><td class="{"ok" if ok else "no"}">{"W" if ok else "L"}</td>'
                f'<td>{"" if sc == "" else ("<span class=ok>W</span>" if sc == "1" else "<span class=no>L</span>")}</td>'
                f'<td class="n">{_f(r["total"], 1)}</td><td class="n">{int(r["away_pts"]) + int(r["home_pts"])}</td>'
                f'<td>{escape(r["fh_pick"] or "—")}</td>'
                f'<td>{"" if hc == "" else ("<span class=ok>W</span>" if hc == "1" else "<span class=no>L</span>")}</td></tr>')
        sections.append(
            f'<h2>{escape(d)} &nbsp;<span class="meta">{dw}-{dl}</span></h2><div class="scroll"><table><thead><tr>'
            '<th>Away</th><th>Home</th><th class="n">Final</th><th>Pick</th><th>Result</th><th>Strong</th>'
            f'<th class="n">Proj total</th><th class="n">Actual</th><th>1H Pick</th><th>1H</th></tr></thead><tbody>{"".join(trs)}</tbody></table></div>')
    return page("CBB Model - Season Results", "results.html", tiles + "".join(sections), stamp)


def write(index_html, results_html, docs=DOCS):
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "index.html").write_text(index_html, encoding="utf-8")
    (docs / "results.html").write_text(results_html, encoding="utf-8")
    (docs / ".nojekyll").write_text("", encoding="utf-8")
