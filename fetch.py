"""Scrapers for RealGM (team stats, opponent stats, schedule/results) and
TeamRankings (1st-half points). These replace the workbook's Power Query
connections. Every fetch is saved under data/raw/ so a failed download falls
back to the last good copy instead of breaking the site."""
import re
import time
from pathlib import Path

import requests
from lxml import html as lh

from . import config

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
RAW = Path(__file__).resolve().parent.parent / "data" / "raw"

STAT_COLS = ["GP", "MPG", "PPG", "FGM", "FGA", "FG%", "3PM", "3PA", "3P%", "FTM", "FTA",
             "FT%", "ORB", "DRB", "RPG", "APG", "SPG", "BPG", "TOV", "PF"]


class FetchError(Exception):
    pass


def get(url, tries=4, pause=5):
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
            if r.status_code == 200 and len(r.text) > 500:
                return r.text
            last = f"HTTP {r.status_code}"
        except requests.RequestException as e:
            last = str(e)
        time.sleep(pause * (i + 1))
    raise FetchError(f"{url}: {last}")


def _num(s):
    s = s.strip().replace(",", "")
    if s in ("", "-", "—"):
        return None
    return float(s)


# ---------------- RealGM team / opponent stats ----------------
def parse_realgm_stats(text):
    """Return {team_id: {"name":..., "GP":..., "PPG":..., ...}} from a RealGM team-stats page."""
    doc = lh.fromstring(text)
    out = {}
    for tr in doc.xpath("//table//tbody/tr"):
        tds = tr.xpath("./td")
        if len(tds) < 22:
            continue
        links = tds[1].xpath(".//a[@href]")
        if not links:
            continue
        m = re.search(r"/(\d+)/Stats", links[0].get("href"))
        if not m:
            continue
        row = {"name": links[0].text_content().strip()}
        for col, td in zip(STAT_COLS, tds[2:22]):
            row[col] = _num(td.text_content())
        out[int(m.group(1))] = row
    return out


def realgm_stats(season, which):
    url = (config.REALGM_TEAM if which == "team" else config.REALGM_OPP).format(season=season)
    return parse_realgm_stats(get(url))


# ---------------- RealGM schedule / results ----------------
def parse_realgm_schedule(text):
    """Return list of games: date_text, away/home id+name, result (away_pts, home_pts) or None."""
    doc = lh.fromstring(text)
    games = []
    for tr in doc.xpath("//table//tbody/tr"):
        cells = {td.get("data-th"): td for td in tr.xpath("./td")}
        if "Away Team" not in cells or "Home Team" not in cells:
            continue

        def team(td):
            for a in reversed(td.xpath(".//a[@href]")):
                m = re.search(r"/(\d+)/Rosters", a.get("href"))
                if m and a.text_content().strip():
                    return int(m.group(1)), a.text_content().strip()
            return None, td.text_content().strip()

        aid, aname = team(cells["Away Team"])
        hid, hname = team(cells["Home Team"])
        res = cells.get("Result")
        res_txt = res.text_content().strip() if res is not None else ""
        score = None
        m = re.fullmatch(r"(\d+)\s*-\s*(\d+)", res_txt)
        if m:  # RealGM lists away score first (verified on a box score)
            score = (int(m.group(1)), int(m.group(2)))
        date_td = cells.get("Date")
        when = " ".join(date_td.itertext()).split() if date_td is not None else []
        games.append({
            "when": " ".join(when),
            "away_id": aid, "away": aname,
            "home_id": hid, "home": hname,
            "away_pts": score[0] if score else None,
            "home_pts": score[1] if score else None,
            "status": res_txt,
        })
    return games


def realgm_schedule(date_str):
    return parse_realgm_schedule(get(config.REALGM_SCHEDULE.format(date=date_str)))


# ---------------- TeamRankings 1st-half PPG ----------------
def parse_tr_first_half(text, column):
    """Return {teamrankings_name: value} for the requested column (e.g. 'Last 3')."""
    doc = lh.fromstring(text)
    tables = doc.xpath("//table[contains(@class,'tr-table')]")
    if not tables:
        raise FetchError("TeamRankings table not found")
    t = tables[0]
    heads = [th.text_content().strip() for th in t.xpath(".//thead//th")]
    if column not in heads:
        raise FetchError(f"column {column!r} not in {heads}")
    ci = heads.index(column)
    out = {}
    for tr in t.xpath(".//tbody/tr"):
        tds = tr.xpath("./td")
        if len(tds) <= ci:
            continue
        name = tds[1].get("data-sort") or tds[1].text_content().strip()
        try:
            out[name] = _num(tds[ci].text_content())
        except ValueError:
            continue
    return out


def tr_first_half(date_str):
    return parse_tr_first_half(get(config.TR_FIRST_HALF.format(date=date_str)), config.FIRST_HALF_COLUMN)
