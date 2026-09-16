# Research Log

Every strategy change: what changed, what happened, keep or discard, why. Append-only, don't rewrite history even when a config gets discarded later.

## Baseline (2026-09-16)
Raw MA-cross (20-period), close crosses and closes past SMA, stop 8pts, RR 2:1, no filters.
- 60d yfinance GC=F 5min data: +$1,727 (+3.5%), Sharpe 1.64, win rate 36%.
- **Grid sweep, 45 ma/stop/rr combos on same data: only 10/45 profitable, median Sharpe -1.47.** Edge is fragile, heavily param-dependent, likely overfit to this specific 60-day window. See README for full sweep table.
- Not paper-trading-ready on this evidence alone, but running anyway per user decision (paper money, low cost to learn) - see next entries for attempts to make it more robust.

**Bug note:** batch 09:54 UTC below has a code bug — `confirm_bars` was wired to require the confirmation count at the exact same bar as the raw cross, which is structurally impossible (count is always 1 there), so both `confirm_bars=2` rows show 0 trades / DISCARD. That's not a real result, it's a bug. Fixed (proper pending-cross state machine in `backtest.py`) and re-run in the 09:56 UTC batch below — use that one, the 09:54 confirm_bars rows are void.

## Experiment batch 2026-09-16 09:54 UTC
Data: yfinance GC=F 5min, 13484 bars (2026-07-08 00:10:00-04:00 to 2026-09-16 04:35:00-04:00) - **60-day sample, not long-history, treat as directional only**
Split: train=9438 bars (first 70%), test=4046 bars (last 30%, out-of-sample)

| Variant | Train | Test (OOS) | Verdict |
|---|---|---|---|
| baseline (ma20/stop8/rr2, no filters) | trades=321, win_rate=36.8%, pnl=$1,677, sharpe=2.30, max_dd=-3.7% | trades=170, win_rate=34.7%, pnl=$50, sharpe=0.21, max_dd=-3.3% | KEEP - holds OOS |
| + regime filter (SMA100 trend, only trade with it) | trades=261, win_rate=33.3%, pnl=$-783, sharpe=-1.13, max_dd=-3.2% | trades=120, win_rate=36.7%, pnl=$600, sharpe=2.11, max_dd=-2.5% | KEEP - holds OOS |
| + confirm_bars=2 (needs 2 closes past sma, cuts false crosses) | trades=0, win_rate=0.0%, pnl=$0, sharpe=nan, max_dd=0.0% | trades=0, win_rate=0.0%, pnl=$0, sharpe=nan, max_dd=0.0% | DISCARD - fails OOS |
| + session filter (NY session only, 13-21 UTC) | trades=85, win_rate=37.6%, pnl=$625, sharpe=1.64, max_dd=-1.9% | trades=49, win_rate=36.7%, pnl=$253, sharpe=1.36, max_dd=-1.7% | KEEP - holds OOS |
| + ATR volatility filter (skip quiet bars, atr14 >= 3pts) | trades=310, win_rate=36.8%, pnl=$1,630, sharpe=2.27, max_dd=-3.9% | trades=164, win_rate=34.8%, pnl=$68, sharpe=0.26, max_dd=-2.7% | KEEP - holds OOS |
| + regime + confirm_bars=2 combined | trades=0, win_rate=0.0%, pnl=$0, sharpe=nan, max_dd=0.0% | trades=0, win_rate=0.0%, pnl=$0, sharpe=nan, max_dd=0.0% | DISCARD - fails OOS |

## Experiment batch 2026-09-16 09:56 UTC
Data: yfinance GC=F 5min, 13484 bars (2026-07-08 00:10:00-04:00 to 2026-09-16 04:35:00-04:00) - **60-day sample, not long-history, treat as directional only**
Split: train=9438 bars (first 70%), test=4046 bars (last 30%, out-of-sample)

| Variant | Train | Test (OOS) | Verdict |
|---|---|---|---|
| baseline (ma20/stop8/rr2, no filters) | trades=321, win_rate=36.8%, pnl=$1,677, sharpe=2.30, max_dd=-3.7% | trades=170, win_rate=34.7%, pnl=$50, sharpe=0.21, max_dd=-3.3% | KEEP - holds OOS |
| + regime filter (SMA100 trend, only trade with it) | trades=261, win_rate=33.3%, pnl=$-783, sharpe=-1.13, max_dd=-3.2% | trades=120, win_rate=36.7%, pnl=$600, sharpe=2.11, max_dd=-2.5% | KEEP - holds OOS |
| + confirm_bars=2 (needs 2 closes past sma, cuts false crosses) | trades=351, win_rate=36.2%, pnl=$1,347, sharpe=1.77, max_dd=-4.4% | trades=174, win_rate=33.3%, pnl=$-522, sharpe=-1.41, max_dd=-4.3% | DISCARD - fails OOS |
| + session filter (NY session only, 13-21 UTC) | trades=85, win_rate=37.6%, pnl=$625, sharpe=1.64, max_dd=-1.9% | trades=49, win_rate=36.7%, pnl=$253, sharpe=1.36, max_dd=-1.7% | KEEP - holds OOS |
| + ATR volatility filter (skip quiet bars, atr14 >= 3pts) | trades=310, win_rate=36.8%, pnl=$1,630, sharpe=2.27, max_dd=-3.9% | trades=164, win_rate=34.8%, pnl=$68, sharpe=0.26, max_dd=-2.7% | KEEP - holds OOS |
| + regime + confirm_bars=2 combined | trades=250, win_rate=36.0%, pnl=$850, sharpe=1.34, max_dd=-2.2% | trades=108, win_rate=36.1%, pnl=$396, sharpe=1.47, max_dd=-2.2% | KEEP - holds OOS |

**Reading the 09:56 batch (the correct one) - all six technically "profitable OOS" but not equally trustworthy:**
- **Baseline**: train Sharpe 2.30 -> test Sharpe 0.21. Big drop-off, barely profitable OOS. Weak.
- **Regime filter alone**: train Sharpe **-1.13** (lost money) -> test Sharpe **+2.11**. Flipped sign between windows - that's not an edge, that's noise. Don't trust this row despite the OOS number looking good.
- **confirm_bars=2 alone**: train 1.77 -> test -1.41. Flipped the other way. Discard, confirmed overfit.
- **Session filter (NY hours only)**: train 1.64 -> test 1.36. Most consistent of all six, same sign, similar magnitude, both positive. Best candidate so far.
- **ATR filter**: train 2.27 -> test 0.26. Barely differs from baseline (atr_min=3pts wasn't a very restrictive threshold) - didn't really test anything new.
- **Regime + confirm_bars=2 combined**: train 1.34 -> test 1.47. Also consistent, both positive, similar magnitude. Second-best candidate.

**Honest caveat on all of this:** test-window trade counts are 49-174 - small enough that "consistent Sharpe" could still be luck, not proof. This is still the same 60-day yfinance sample split two ways, not independent data. Real validation needs the longer IB history + proper walk-forward (multiple independent test windows, not one 70/30 split). Treat "session filter" and "regime+confirm2" as the current best leads to test further, not as validated.

## NQ/MNQ comparison test (2026-09-16)
User said the MA-cross strategy is actually proven on NQ/MNQ (not gold - gold was always the unproven experiment). Ran the same grid sweep on NQ 60d 5min data to compare.
- Baseline sweep (no session filter, stop grid 15/25/40pt scaled to NQ's ~23pt median 5min range): **5/45 profitable, median Sharpe -4.76.** Worse than gold's 10/45.
- Added NY regular session filter (9:30am-4pm ET, per user's description of their real filter): **1/45 profitable, median Sharpe -4.04.** Still bad, slightly less bad.
- **Conclusion: this simple mechanical translation (SMA cross + close-past-MA entry + fixed point stop/TP) does not reproduce a working NQ/MNQ strategy**, despite user's real-world experience that one exists. Most likely explanation: the user said "it's mainly about risk management after that" - i.e. the actual edge likely lives in discretionary trade management (moving stop to breakeven, trailing, cutting losers early, letting winners run past a fixed TP, or selective entries not just every cross) that a fixed-stop/fixed-TP backtest structurally cannot capture. This is a translation gap, not proof the real strategy doesn't work - just proof this particular code doesn't represent it.
- Not pursued further without more detail on the actual risk-management rules from the user.
