# CBB Model

College basketball picks rebuilt from `NEWBBALLMODEL2024-FUTURE.xlsm`, with the spreadsheet's formula mistakes fixed.
Every morning GitHub Actions pulls fresh stats, grades yesterday's games, locks today's picks, and publishes the site.

## What runs where

| Spreadsheet | Here |
|---|---|
| Power Query: RealGM Team Totals / Opponent Totals | `cbb/fetch.py` → `realgm_stats()` |
| Power Query: RealGM schedule (`Table 0`) | `cbb/fetch.py` → `realgm_schedule()` (also used for final scores) |
| Power Query: TeamRankings 1st-half PPG (`First`) | `cbb/fetch.py` → `tr_first_half()` |
| Power Query: TeamRankings strength of schedule | not used: no formula in the sheet referenced it |
| TEAMSORT macro (copy + sort) | not needed: teams are matched by RealGM team id |
| Combined Stats sheet | `cbb/model.py` → `team_rating()` |
| WINNERS sheet | `cbb/model.py` → `predict()` |
| DailyReport (macro appends each day) | `data/ledger.csv` + Season Results page |

## Fixes vs the spreadsheet

1. **Turnover %** is now `TOV / (FGA + 0.44·FTA + TOV)`. Because of a misplaced parenthesis, the sheet computed `TOV / (FGA + FTA + APG/100)`.
2. **Offense rebounding weight** is now 0.2, matching defense. The sheet had 2, so offensive rebounding made up about 60% of every Offense rating.
3. **ppg / TOTAL** is now (points scored + points allowed) / 2 per team. A misplaced parenthesis had moved the average into the VLOOKUP's match argument, so the sheet used points scored only.
4. **Lookups**: teams now match exactly by id. The sheet's ranges stopped at row 362 of 366.
5. **Strong Pick** (the sheet called it "99.5% Winner") now triggers when the gap is > 0.055. That flags the same ~12% of games the sheet's 0.2 cutoff did, on the corrected scale.

Backtest: 2,319 games played after the workbook's Jan 21, 2026 stats snapshot, so the stats came before every game. Results are straight-up winners. There's no betting-line comparison.

| | Spreadsheet formulas | Corrected |
|---|---|---|
| Pick accuracy | 60.9% | **64.1%** |
| Strong-pick accuracy (12% of games) | 70.6% | **84.5%** |
| Rating gap vs final margin (correlation) | 0.32 | **0.44** |
| Total, average miss | 15.4 pts | **14.6 pts** |

## Settings

Everything adjustable lives in `cbb/config.py`: weights, the strong-pick cutoff, the 1H column, and the early-season rule. Until the median team has played 3 games, the model uses last season's final stats.

## Run it by hand

```
pip install -r requirements.txt
python run_daily.py                 # today
python run_daily.py --date 2026-11-15
python -m pytest -q tests           # checks (needs pytest)
```

## Team names

RealGM stats and the RealGM schedule share team ids, so they always match.
TeamRankings names map through `data/teamrankings_names.csv` (all 365 matched for 2025-26).
If TeamRankings adds or renames a team, the Actions log prints the unmatched name. Add a row to that CSV to fix it.
