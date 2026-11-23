# Tipoff Edge

The code and the pages of [tipoffedge.com](https://tipoffedge.com): college basketball predictions from a four-factor
model, posted before tip-off, locked, and graded in public against the final score.

It began as a spreadsheet (`NEWBBALLMODEL2024-FUTURE.xlsm`). The same idea now runs by itself every day.

## How it runs

The site is this repository's top folder, served by GitHub Pages. One workflow, **Daily picks**
(`.github/workflows/daily.yml`), builds it. A Cloudflare Worker (`tipoffedge-timer`) starts that workflow on time;
GitHub's own schedule is the backup. Each run checks what is due and stops in seconds when nothing is.

| When (Central) | What the run does |
|---|---|
| About 3:23 AM | Overnight build: grades yesterday, downloads fresh team stats, locks the day's picks, rewrites every page |
| Before 9 AM, 11 AM, 2 PM, 5 PM and 8 PM | Refresh: current betting lines, picks for games added late, results of games that have ended |
| 8:30 PM to 12:30 AM, once an hour | Score update: grades the games that have gone final |

The data comes from the CollegeBasketballData API. Its key is the repository secret `CBBD_API_KEY` and appears nowhere
in the code.

## The files

| File | What it is |
|---|---|
| `build.py` | One run from start to finish: download, grade, rate, pick, write the pages |
| `fetch.py` | The data feed and the code that reads its answers |
| `model.py` | The ratings, the schedule adjustment, the early-season blend and the prediction |
| `config.py` | Every setting, with the evidence behind each one |
| `ledger.py` | `data/ledger.csv`: every pick, written once and graded once |
| `bets.py` | Best Bets: the model's numbers against the betting lines |
| `writeup.py` | The plain-English reasons under each pick |
| `teamdata.py` | What the Rankings and the team pages show |
| `webpage.py` | Every page of the site |
| `share.py`, `video.py` | The share image and the daily clip |
| `tests.py` | The tests |

## The model in short

Every Division I team is rated on four things on offense and the same four on defense: shooting (effective field goal
%), turnovers, offensive rebounding and free throws made per shot attempt, weighted 42 / 37 / 14 / 7. The rating is
adjusted for the strength of the schedule, last season's rating fades out over a team's first 20 games, and the gap
between two ratings plus home court becomes a projected margin and score. The full account, written from the code, is
the site's [How the model works](https://tipoffedge.com/model.html) page.

## Checking a change

```
pip install -r requirements.txt pytest
python -m pytest -q tests.py
```

`python build.py` runs a full build (it needs the data key in the `CBBD_API_KEY` environment variable);
`--refresh` and `--scores` run the two lighter kinds.
