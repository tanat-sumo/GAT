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

## NQ/MNQ with breakeven+MA-trail exit (2026-09-16)
User confirmed real risk management = move stop to breakeven, then trail (delegated exact params to me). Implemented `trail_mode="ma_trail"` in backtest.py: breakeven at 1R favorable move, then stop trails behind the MA itself (never loosens), no fixed take-profit.
- Swept ma[10,15,20,30,50] x stop[15,25,40] x session[24h, NY-hours], 30 configs on NQ/MNQ.
- **Result: 0/30 profitable. Median Sharpe -11.26, some drawdowns past -45%. Worse than the fixed-stop version, not better.**
- Why: trailing tightly against a fast 5-20 period MA on 5min bars means price constantly whipsaws through it in normal chop - stop gets hit almost immediately after breakeven on most trades, converting what should be winners into scratches/small losses, with no offsetting big winners since the MA trail cuts them short too on any pullback.
- **Conclusion: "trail behind the MA itself" was my guess at implementing your breakeven+trail description, and it's a bad guess.** Real discretionary trailing (behind swing lows/highs, ATR-multiple distance, or manual judgment) is looser and likely much more forgiving of normal noise than literally hugging the indicator line. This is a real limit of mechanically codifying a discretionary rule from a one-line description - further guessing has diminishing returns without a more specific, codifiable trailing rule from the user (e.g. "X points behind the most recent swing low" or "N x ATR behind price").

## Multi-window walk-forward: is the "session filter" edge real? (2026-09-18)

**Hypothesis (single, falsifiable):** the NY-session filter flagged in the 09:56 batch as the best
candidate has a genuine time-of-day edge that survives *multiple independent* out-of-sample windows,
not just the one 70/30 split that produced it.

Data: refreshed yfinance GC=F 5min, 13,690 bars, 2026-07-09 -> 2026-09-17 22:35 ET (still a 60-day
sample; each of the 6 windows is only ~10 calendar days / 15-95 trades). New script:
`scripts/wf_session.py`. Method: 6 sequential non-overlapping windows, **fixed configs, no
per-window refitting**, so there is no config-selection bias to explain the result away.

### Correction 1 - timezone labelling bug (the "NY session" was never the NY session)
yfinance returns GC=F bars in **US/Eastern**, not UTC. `scripts/experiment.py` passed
`session_hours=(13, 21)` and logged it as "NY session only, 13-21 UTC". Because `backtest.py`
compares against `ts.hour` in the dataframe's own tz, that filter actually selected
**13:00-21:00 ET** (17:00-01:00 UTC) - NY afternoon into the Asia open, not the NY session.
`scripts/sweep_nq_session.py` got this right for NQ (`((9,30),(16,0))` ET, with a comment saying so);
only the gold experiment batch was mislabelled. Every prior log entry naming "13-21 UTC" should be
read as 13-21 ET. Both windows are tested below.

### Correction 2 - `load_data` silently dropped 2 bars
`load_data` passed `skiprows=[1, 2]`, left over from raw yfinance 3-row MultiIndex headers. Both
saved CSVs have a single header row, so it discarded the first two real bars of every backtest ever
run here. Fixed. Magnitude is negligible (2 of ~13,700, conclusions unchanged on re-run) but it was
wrong.

### Result - 6 independent windows, fixed configs
| Config | trades | profitable windows | total P&L | median window Sharpe |
|---|---|---|---|---|
| baseline (ma20/stop8/rr2) | 489 | **2/6** | +$933 | -1.59 |
| session 13-21 ET (the as-coded "best candidate") | 140 | 4/6 | +$620 | +2.23 |
| session 09:30-16:00 ET (true NY RTH) | 186 | 4/6 | +$402 | +1.67 |
| regime100 + confirm2 | 354 | 4/6 | +$1,098 | +2.18 |

First real finding: **baseline is profitable in only 2 of 6 windows.** Its whole +$933 comes from
two consecutive windows in late-July/early-August (+$1,666 and +$2,480); the other four lose. The
single 70/30 split hid this because the split boundary happened to put the good stretch in train and
a mildly-negative stretch in test, which read as "small positive OOS = KEEP". It is not a stable
edge, it is two good weeks.

### Falsification control - all 24 rotations of the same 8h window
If 13-21 ET captures a real time-of-day effect it should stand out from the other 23 rotations of an
identically-wide session filter on identical data. It does not:
- 13-21 ET ranks **9th of 24** by total P&L.
- **10 of 24** rotations also get >=4/6 profitable windows.
- **17 of 24** rotations have positive total P&L.
- Spread across rotations runs from **-$1,354 (01-09 ET) to +$2,398 (09-17 ET)** - a $3,752 range
  produced purely by shifting an arbitrary window start hour, i.e. **four times larger than the
  entire baseline edge ($933) it is supposed to be improving.**

Supporting check: baseline P&L bucketed by entry hour (ET), train (first 70%) vs test (last 30%).
Only **6 of 23** hours are profitable in both halves, and per-hour P&L correlates **-0.34** between
them. There is no stable time-of-day structure in this data at all.

**Verdict: DISCARD "session filter" as an edge.** Hypothesis falsified. Restricting hours cuts trade
count ~70%, which lowers variance and, in this sample, happened to dodge the worst window - that is
what the 09:56 batch measured, not an edge. Its apparent superiority is indistinguishable from
picking any other 8 hours of the day. By the same argument the ranking in the 09:56 batch
("session filter = most consistent") is not evidence and should not be used to pick a live config.
`regime100 + confirm2` is subject to the same doubt (it too mostly just reduces trade count) and has
not been given its own control test yet.

### Live paper-trade reconciliation - the live bot is NOT running the backtested strategy
Live state as of 2026-09-17 22:30 ET: 11 closed trades, 4W/7L (36.4%), +$47, one short open.
Superficially this matches the backtest's ~36% win rate. It does not actually reconcile:

Running `backtest.py` on the *same bars over the same window* (2026-09-16 07:45 ET onward) gives
**15 trades, 26.7% win rate, -$285** vs live's 11 trades, 36.4%, +$47. Only the first two trades
match; from 2026-09-16 10:40 ET onward the two diverge completely (the backtest takes a 10:40 long
and a 12:00 short that the live bot never saw; live instead takes a 12:15 long).

Cause: `scripts/paper_trade.py` only ever inspects `df.iloc[-1]` and `df.iloc[-2]` at poll time, so
**any 5-min bar that is not the latest bar when the job happens to run is never evaluated at all** -
neither for crosses nor for stop/TP. The GitHub Actions `*/5 * * * *` cron is not honoured: observed
commit intervals over the live period are 5-18 minutes, with one 62-minute gap
(2026-09-17 21:18Z -> 22:20Z). **225 bot runs against 443 available bars: the bot saw ~51% of bars.**

Two consequences, one of them biased:
1. Roughly half of all entry signals are silently skipped, so the live trade set is a ~50% random
   subsample of the strategy - which is why P&L, trade count and sequencing all diverge.
2. Worse, exits are checked only on polled bars. A stop touched during a skipped bar is never
   booked; if price recovers before the next poll, that loss simply never happens. This biases live
   results **optimistically** relative to the real strategy, which is consistent with live (+$47)
   beating the same-window backtest (-$285).

So the "live roughly matches the backtest's 36% win rate" reading is a coincidence of small numbers,
not validation. **The live +$47 should not be treated as evidence for anything.**

Not fixed here: per standing instruction I did not modify the running strategy in `paper_trade.py`.
The fix is to iterate every bar after `last_processed_bar` instead of only the last one (and,
separately, to accept that GH Actions cron cannot be relied on for 5-min granularity). Flagging for
the user to approve.

### Market context (why 2026-09-16 was rough)
The FOMC on 2026-09-16 hiked 25bp to 3.75-4.00% with a hawkish dot plot (16 of 18 officials seeing
another hike in 2026). Gold spiked >1% to ~$4,365 intraday then reversed to close -1.2%. That
whipsaw is visible in the data (~$4,392 -> ~$4,304 inside the live window) and is exactly the shape
that punishes a 5-min MA-cross with a fixed 8pt stop: it produced a cluster of the live losses.
Sources: [Kitco](https://www.kitco.com/news/article/2026-09-16/gold-price-drops-4310oz-fed-votes-12-0-favor-25-bps-rate-hike-16-18),
[CNBC](https://www.cnbc.com/2026/09/16/gold-gains-with-fed-rate-decision-in-spotlight.html).
Caveat: this is one event explaining one bad stretch after the fact, not a tradeable finding.

### Standing caveats
60-day yfinance sample, 6 windows of ~10 days each, 15-95 trades per window. 4/6 profitable windows
has a ~34% chance of happening by coin-flip, so none of the "4/6" rows above are significant on
their own either - the rotation control is the load-bearing evidence, not the window counts. Payoff
is $157 win / -$83 loss, so breakeven win rate is **34.6%** against a measured ~35.5% - the entire
claimed edge is ~1 percentage point of win rate, well inside the noise of this sample.
