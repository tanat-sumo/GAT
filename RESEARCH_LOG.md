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

**Fixed 2026-09-18** (user approved): `paper_trade.py` now walks every bar strictly after
`last_processed_bar` in order (stop/tp check then entry check per bar, same semantics as
`backtest.py`'s loop) instead of only looking at `df.iloc[-1]`. yfinance's rolling fetch window
still holds bars from a missed poll (observed gaps up to 62min, well under the window), so a
skipped stop-out now gets booked correctly instead of silently vanishing. Dry-run tested against
the live state before pushing (cleanly replayed 3 missed bars, no discrepancy). Does not retroactively
correct trades already recorded before the fix - those stay as they were logged, only forward
behavior changes. GH Actions cron timing itself is still not fixed (still jittery/unreliable as a
*trigger*), but no longer matters for correctness now that every bar gets replayed regardless of
when the poll actually fires.

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

## Volatility-normalized stops: is the fixed 8pt stop the broken part? (2026-09-18, run 2)

**Why this and not another filter.** Every idea tested here so far (session, regime, confirm_bars)
has the same shape: throw entries away -> fewer trades -> less variance -> looks like an edge. The
rotation control killed the session filter for exactly that reason. This run deliberately picks a
hypothesis of a *different* shape: keep every entry, change only the risk geometry, so the
trade-count-reduction confound cannot produce the result.

**Hypothesis (single, falsifiable):** the 8-point stop is a constant point distance applied to an
instrument whose 5-min volatility varies widely over the sample. Sizing risk to volatility instead
(stop = k * ATR(14) at the entry bar, target = rr * that) gives a stable improvement across multiple
independent windows, **and** that improvement comes from adapting to volatility rather than from the
average stop merely being wider.

New code: `stop_mode="atr"` / `atr_stop_mult` / `atr_series` in `backtest.py` (regression-tested
against the pre-change engine on 4 configs - identical trade counts and P&L, so the refactor is
behavior-preserving for every existing result), and `scripts/wf_atr_stop.py`.
Data: refreshed yfinance GC=F 5min, 13,700 bars, 2026-07-09 -> 2026-09-17 23:25 ET. 6 non-overlapping
windows, fixed configs, no per-window refitting. ATR(14) over the sample: median **4.33 pts**, 10th
pct 2.80, 90th pct 7.48, max 26.08 - so the live 8pt stop is ~1.85x median ATR.

### Premise check (done first, on purpose)
Does volatility at entry predict anything at all under the current fixed stop? Baseline trades
bucketed into ATR quintiles at entry:

| ATR quintile at entry | n | win rate | total P&L |
|---|---|---|---|
| Q1 (1.9-3.6 pts) | 100 | 31.0% | -$860 |
| Q2 (3.7-4.5) | 99 | 39.4% | +$1,143 |
| Q3 (4.5-5.7) | 99 | 39.4% | +$1,143 |
| Q4 (5.7-7.4) | 99 | 32.3% | -$537 |
| Q5 (7.4-23.2) | 100 | 36.0% | +$340 |

Non-monotone, and **corr(ATR at entry, trade P&L) = 0.011**. Volatility at entry carries essentially
no information about outcome in this sample. That already makes H unlikely; reported before the
result rather than after it.

### P1 - main test, 6 independent windows
| Config | trades | profitable windows | total P&L | median window Sharpe | win rate |
|---|---|---|---|---|---|
| **FIXED 8pt (baseline / live config)** | 491 | 3/6 | **+$1,487** | -0.12 | 36% |
| ATR k=0.5 (~2.1pt) | 1492 | 0/6 | -$4,877 | -4.80 | 33% |
| ATR k=0.75 (~3.3pt) | 1207 | 1/6 | -$2,496 | -3.44 | 35% |
| ATR k=1.0 (~4.5pt) | 894 | 2/6 | -$49 | -1.49 | 36% |
| ATR k=1.25 (~5.5pt) | 682 | 2/6 | +$197 | -0.29 | 36% |
| ATR k=1.5 (~6.7pt) | 531 | 3/6 | -$2,940 | -1.05 | 33% |
| ATR k=2.0 (~10.0pt) | 342 | 2/6 | -$4,337 | -3.85 | 31% |
| ATR k=2.5 (~12.8pt) | 224 | 1/6 | -$3,785 | -3.19 | 30% |
| ATR k=3.0 (~15.8pt) | 172 | 2/6 | -$7,291 | -0.93 | 27% |

**Not one ATR multiple beats fixed-8.** Best is k=1.25 at +$197 on 2/6 windows vs +$1,487 on 3/6.
P1 fails outright.

### P2 control - matched width (does *adaptivity* add anything?)
For each k, a fixed stop set at that k's median realized distance, same windows:

| k | median stop | ATR-adaptive | fixed at same width | adaptivity advantage | windows ATR better |
|---|---|---|---|---|---|
| 0.5 | 2.1pt | -$4,877 | -$3,554 | **-$1,323** | 1/6 |
| 0.75 | 3.3pt | -$2,496 | -$3,188 | +$692 | 4/6 |
| 1.0 | 4.5pt | -$49 | -$433 | +$384 | 3/6 |
| 1.25 | 5.5pt | +$197 | +$204 | -$7 | 2/6 |
| 1.5 | 6.7pt | -$2,940 | -$81 | **-$2,860** | 3/6 |
| 2.0 | 10.0pt | -$4,337 | -$2,424 | -$1,912 | 2/6 |
| 2.5 | 12.8pt | -$3,785 | -$6,197 | +$2,412 | 3/6 |
| 3.0 | 15.8pt | -$7,291 | -$4,906 | -$2,384 | 2/6 |

Adaptivity wins in **3/8** k values; mean advantage **-$625**, median **-$665**. Sign-flipping,
centred on zero. No adaptivity effect.

### P3 control - decoupled volatility (direct analogue of the session rotation control)
Re-ran each k with the ATR series circularly time-shifted by 2k/4k/6k/8k/10k bars, so stop widths
keep an identical distribution but no longer match the volatility actually present at the entry bar.
If real ATR carried information, real should beat its own shifted copies.

| k | real ATR | shifted mean | shifted min..max | real beats shifted |
|---|---|---|---|---|
| 0.5 | -$4,877 | -$4,714 | -$5,210..-$4,357 | 2/5 |
| 0.75 | -$2,496 | -$3,433 | -$6,100..-$1,989 | 4/5 |
| 1.0 | -$49 | -$1,406 | -$4,795..+$1,266 | 3/5 |
| 1.25 | +$197 | +$13 | -$1,645..+$1,439 | 3/5 |
| 1.5 | -$2,940 | -$1,881 | -$3,648..-$835 | 1/5 |
| 2.0 | -$4,337 | +$631 | -$1,606..+$4,534 | **0/5** |
| 2.5 | -$3,785 | +$578 | -$1,704..+$2,666 | **0/5** |
| 3.0 | -$7,291 | -$3,940 | -$5,398..+$197 | **0/5** |

Real-ATR P&L sits inside the range of its own shifted controls in 5/8 cases, and for k>=2 the real
series is **worse than all five** decoupled controls. Knowing the current volatility is worth nothing
here - arbitrarily mismatched stop widths do as well or better.

**Verdict: DISCARD volatility-normalized stops. Hypothesis falsified on all three predictions**
(no improvement, no adaptivity effect vs matched width, no information vs decoupled controls), and
the premise check said so in advance (corr 0.011).

### P4/P5 - the genuinely uncomfortable finding: the stop width itself is noise
Neutral fixed-width sweep, same 6 windows:

| stop | trades | profitable windows | total P&L |
|---|---|---|---|
| 3pt | 1261 | 3/6 | -$2,913 |
| 4pt | 1048 | 2/6 | -$1,384 |
| 5pt | 826 | 3/6 | +$772 |
| 6pt | 690 | 2/6 | +$630 |
| **8pt (live)** | 491 | 3/6 | **+$1,487** |
| 10pt | 376 | 2/6 | -$2,428 |
| 12pt | 295 | 2/6 | -$4,245 |
| 16pt | 209 | 2/6 | -$5,267 |
| 20pt | 156 | 1/6 | -$2,268 |
| 24pt | 117 | 2/6 | -$351 |

Only **3/10** widths are profitable; spread **-$5,267..+$1,487**. The live 8pt ranks **1/10** - but
that is a selection artifact, not evidence: `data/sweep_results.csv` shows stop was swept over
{5, 8, 12} on this *same* 60-day sample and 8 won. Being the best value of a parameter that was
chosen on this data is exactly what you would expect whether or not there is an edge.

Finer grid around it (+/-1.5pt), same windows:

| stop | 6.5 | 7.0 | 7.5 | **8.0** | 8.5 | 9.0 | 9.5 |
|---|---|---|---|---|---|---|---|
| total P&L | +$2,645 | -$915 | +$441 | **+$1,487** | +$724 | -$915 | -$2,079 |
| profitable windows | 4/6 | 2/6 | 2/6 | 3/6 | 2/6 | 2/6 | 2/6 |

**A 0.5-point change in the stop swings P&L by up to $3,560 and flips its sign repeatedly.** There is
no plateau around 8pt - it is a knife edge in a $4,700-wide neighbourhood, on a config whose whole
claimed edge is $1,487. This is the same diagnosis the session rotation control gave, now for a
second, independent nuisance parameter: **the P&L surface across arbitrary parameter choices is
several times wider than the entire claimed edge.**

Cost sensitivity, same windows:

| round-trip cost | stop 8pt | stop 5pt |
|---|---|---|
| 0.00 pt | +$2,960 (3/6) | +$3,250 (4/6) |
| 0.15 pt | +$2,224 (3/6) | +$2,011 (3/6) |
| 0.30 pt (assumed) | +$1,487 (3/6) | +$772 (3/6) |
| 0.60 pt | +$14 (2/6) | -$1,706 (3/6) |

**The entire measured result is consumed by doubling the cost assumption from 0.3 to 0.6 pts.** 0.3pt
on MGC is $3 round-trip; that is a reasonable-to-optimistic estimate, not a conservative one. So the
config P&L is robust to neither its stop width nor its cost assumption.

### What this means / what not to do next
- Vol-normalized stops: dead, with controls. Do not revisit without a genuinely different mechanism
  (e.g. vol measured over a different horizon AND a reason to expect it to matter).
- Two independent nuisance parameters (session hours, stop width) have now each been shown to produce
  a P&L spread 3-4x larger than the strategy claimed edge on this sample. That is the central fact
  about this dataset: **60 days of 5-min gold cannot distinguish this strategy edge from parameter
  noise, and more parameter search on it will keep producing false positives.**
- Concrete implication: further hypothesis testing on this 60-day yfinance sample has low expected
  value regardless of how well controlled each test is. The binding constraint is data, not ideas.
  The highest-value next step is the backlog item already noted in README - pull multi-year history
  (Dukascopy spot XAUUSD as a fast proxy, IB for exact contract) so windows can be measured in
  years rather than 10-day slices.
- Live config untouched this run, per instruction: `paper_trade.py` was not modified.
- Live paper state re-checked at start of run: unchanged from the previous entry (11 closed trades,
  4W/7L, +$47, one short open from 2026-09-17 21:30 ET). Nothing new has closed since the
  bar-coverage fix, so there is still zero trustworthy live data to reconcile against.

### Standing caveats (unchanged)
60-day yfinance sample; 6 windows of ~10 days; tens of trades per window. Payoff $157 win /-$83 loss
=> breakeven win rate 34.6% vs measured ~36%. Everything above is directional evidence about *this
sample*, and the main thing it establishes is how little this sample can establish.

## NQ/MNQ breakeven+trail, widened parameter search (2026-09-18, run 3)

**Why.** The 2026-09-16 breakeven+MA-trail attempt went 0/30 with one fixed setting (breakeven_r=1.0,
trail hugging the raw MA, no slack). That is one point in a parameter space, not a test of the idea.
This run widens the search along the axes implied by *why* it was thought to fail (a stop parked on a
fast MA is inside normal 5-min noise): the breakeven trigger, slack between the stop and the MA, the
speed of the trailing MA, the initial stop, and the entry MA.

New code: `trail_buffer_pts` / `trail_buffer_atr` / `trail_ma_period` / `trail_timing` in
`backtest.py`, and `scripts/wf_nq_trail.py` (grid + controls), `scripts/nq_entry_edge.py` (entry
diagnostic). Data: refreshed yfinance NQ=F 5min, 13,663 bars, 2026-07-09 -> 2026-09-17 23:45 ET.
MNQ sizing ($2/pt), 1.0pt round-trip cost, 6 non-overlapping windows (~10 days each), fixed configs,
no per-window refitting.

### Two engine bugs found first, both in the trail logic (all pre-fix ma_trail numbers are void)

The first grid run produced a "+$35,225, 6/6 windows, Sharpe 18" config. That is not a finding, it is
a symptom, and chasing it found two real bugs:

1. **Phantom fills.** The trail did `stop = max(stop, trail_MA)` for longs with no check that the
   level was below the market. Whenever the trail MA sat *above* price (routine with a slow trail
   MA), the long's stop was set above the close, the `low <= stop` test fired on that same bar, and
   the trade was booked at that stop price. Concrete case: a long entered at 28,096.00 on
   2026-07-27 12:20 ET "exited" 5 minutes later at 28,579.26 for +$964 - on a bar whose **high was
   28,204.50**. 375 points of profit at a price that never traded. Fixed: the trail only ratchets to
   a level on the correct side of the current close.
2. **Intrabar peek in the trail timing.** The trail was updated from bar *t*'s close and then checked
   against bar *t*'s own high/low - i.e. the stop was moved using the end of a bar and then applied
   to price action that had already happened earlier in that same bar. This manufactures stop-outs.
   Fixed by defaulting to `trail_timing="next_bar"` (a trail level computed at a bar's close only
   applies from the next bar on); the old behavior is kept as `trail_timing="close"` for archaeology
   only.

Also fixed while in there: stops and targets always filled exactly at their level even when a bar
opened straight through them; fills now happen at the open in that case (matters at session gaps).

Impact, same data, old engine vs new (full-sample P&L):

| case | old | new | delta |
|---|---|---|---|
| gold baseline ma20/stop8/rr2 (fixed mode) | +$1,229 | +$1,026 | -$203 |
| gold regime100+confirm2 (fixed mode) | +$638 | +$232 | -$406 |
| NQ fixed ma20/stop25/rr2 | -$5,606 | -$5,060 | +$546 |
| NQ ma_trail ma20/stop25/be1R | -$15,356 | -$5,235 | **+$10,120** |
| NQ ma_trail ma10/stop15/be1R | -$25,634 | -$8,418 | **+$17,216** |
| gold ma_trail ma20/stop8/be1R | +$805 | +$3,938 | +$3,133 |

Decomposition on the NQ case: phantom fills were worth +$1,221 (optimistic, as expected), the
intrabar peek was worth **-$11,342** (pessimistic). **The 2026-09-16 "0/30 profitable, median Sharpe
-11.26" result was produced by an engine that manufactured much of the whipsaw it then diagnosed.**
The standing explanation in this log - "trailing tight against a fast MA whipsaws constantly" - was
substantially a backtester artifact, not a fact about the market. Those numbers should not be cited
again. Fixed-mode (non-trail) numbers move only slightly, so earlier non-trail conclusions stand.

### Mechanism check (before the P&L): does slack do what it is supposed to?
ma20 / stop25 / be1.0R, full sample, buffer as a multiple of ATR(14) (NQ ATR14 median ~24pt):

| buffer | trades | median hold (bars) | p90 hold | avg win | avg loss | win rate | P&L |
|---|---|---|---|---|---|---|---|
| 0.0x (hug the MA) | 1094 | 4 | 22 | $121 | -$44 | 23.9% | -$5,235 |
| 0.5x | 987 | 4 | 25 | $148 | -$42 | 18.7% | -$6,159 |
| 1.0x | 889 | 4 | 27 | $168 | -$41 | 16.6% | -$5,272 |
| 2.0x | 763 | 4 | 34 | $219 | -$39 | 12.5% | -$4,941 |
| 3.0x | 704 | 4 | 37 | $265 | -$38 | 9.5% | -$6,245 |

The buffer does mechanically what it was supposed to do - winners run ~2x further and trades are held
~70% longer at the 90th percentile - and it **still doesn't help**, because win rate falls in almost
exact proportion. The trade-off is flat. That is the shape of a strategy with no edge to redistribute.

### P1 - full grid, 480 configs x 6 independent windows
Axes: breakeven_r {0.5, 1, 1.5, 2} x trail buffer {0, 0.5, 1, 2, 3} x ATR14 x trail MA
{entry MA, 50, 200} x initial stop {15, 25, 40, 60} x entry MA {20, 50}.

- **Profitable over the 6 windows: 7 of 480.** Median config -$4,462, spread -$12,311 .. +$2,596.
- Distribution of profitable windows per config: 0 windows: 52, 1: 166, 2: 165, 3: 87, 4: 7, 5: 3,
  **6: none**. If each window were a coin flip you would expect ~165 of 480 configs to reach >=4/6;
  **10 do.** The grid sits far below a zero-edge null - this is a negative-drift system, not a
  hidden-edge one.
- Best config: `ma20 stop60 be1R buf0xATR trailma50`, +$2,596 over 355 trades = **+$7.31/trade**,
  against a 1.0pt ($2) assumed round-trip cost.
- Marginal effect of each axis (mean P&L, averaging over the others) is negative everywhere and flat:
  breakeven_r -$4,162..-$5,291, buffer -$4,285..-$4,832, trail MA -$4,461..-$4,890, stop
  -$3,103..-$5,279, entry MA -$3,835..-$5,394. No axis has a direction, let alone an optimum.

### P2 CONTROL (the load-bearing one) - does in-sample selection transfer?
Split the 6 windows train/test at 4 points, pick the grid's best config on train, score it on test:

| train/test windows | picked config | train P&L | test P&L | grid test median | picked's percentile in grid | Spearman(train, test) |
|---|---|---|---|---|---|---|
| 2 / 4 | ma20 stop25 be2R buf0.5xATR trailma50 | +$3,829 | -$4,953 | -$3,301 | **0.25** | **-0.25** |
| 3 / 3 | ma20 stop40 be1R buf0xATR trailma50 | +$3,106 | -$2,448 | -$1,946 | **0.32** | **-0.06** |
| 4 / 2 | ma20 stop40 be1R buf1xATR trailma200 | +$3,102 | -$1,970 | -$943 | **0.20** | **-0.28** |
| 5 / 1 | ma20 stop40 be1.5R buf0xATR trailma50 | +$2,063 | -$1,055 | +$408 | **0.08** | **-0.24** |

Every in-sample winner loses money out of sample, and lands **below the median config** - at the
8th-32nd percentile of the grid it was picked from. Train/test rank correlation is negative at all
four splits. Choosing these parameters on past windows is not merely worthless here, it is slightly
worse than choosing at random. Same verdict the session-rotation and stop-width controls gave, now
for the trail parameters.

### P3 CONTROL - neighbourhood of the grid winner
One step along each axis from `ma20 stop60 be1R buf0xATR trailma50` (+$2,596):

| perturbation | P&L | perturbation | P&L |
|---|---|---|---|
| be_r 0.5 | -$5,074 | buffer 1.0xATR | -$8,071 |
| be_r 1.5 | -$4,212 | buffer 2.0xATR | -$6,864 |
| be_r 2.0 | -$5,357 | buffer 3.0xATR | -$9,316 |
| buffer 0.5xATR | -$4,598 | trail MA = entry MA | -$3,994 |
| stop 15 | -$8,441 | trail MA 200 | -$7,022 |
| stop 25 | -$4,238 | entry MA 50 | -$7,685 |
| stop 40 | +$658 | | |

**13 of 14 one-step neighbours lose money**; the neighbourhood spans -$9,316..+$2,596, a range ~4.5x
the winner's entire P&L. Same knife edge as the gold 8pt stop. No plateau, no edge.

### P4/P5/P6 CONTROLS - window placement, engine timing, cost (top 8 configs)
| config | base | windows offset by half | legacy trail timing | cost 2.0pt |
|---|---|---|---|---|
| ma20 stop60 be1R buf0 trailma50 | +$2,596 (5/6) | +$2,060 (3/6) | +$731 | +$1,886 |
| ma20 stop40 be1R buf1xATR trailma200 | +$1,133 (5/6) | -$2,090 (3/6) | -$3,026 | +$413 |
| ma20 stop40 be1.5R buf0 trailma50 | +$1,009 (4/6) | +$1,618 (4/6) | -$2,542 | +$101 |
| ma20 stop40 be1R buf0 trailma50 | +$658 (4/6) | -$1,720 (3/6) | -$3,622 | -$398 |
| ma50 stop25 be1R buf1xATR trailma200 | +$620 (3/6) | -$203 (3/6) | -$8,483 | -$210 |
| ma20 stop40 be1R buf0.5xATR trailma200 | +$382 (5/6) | -$1,070 (3/6) | -$1,736 | -$378 |
| ma20 stop25 be2R buf3xATR trailma50 | +$100 (3/6) | -$424 (3/6) | -$1,253 | -$894 |
| ma50 stop25 be0.5R buf1xATR trailma200 | -$48 (2/6) | -$1,059 (3/6) | -$12,594 | -$1,014 |

**6 of 8 flip negative** when the window boundaries move by half a window; **5 of 8** die at a 2.0pt
cost assumption. Only the top config survives all three - which is what the single best of 480 draws
from a noisy distribution does by construction, and its own neighbourhood (P3) says it is a spike.

Reference points on the same windows: fixed stop/TP ma20/stop25 -$4,945 (3/6), fixed ma50/stop40
+$761 (3/6), original hug-the-MA trail -$5,053 (2/6).

### The decisive test: the entries have no edge for ANY exit rule to harvest
`scripts/nq_entry_edge.py` measures the MA cross itself, with no exit rule at all, against a control
of randomly chosen entry timestamps carrying the same long/short sequence (so sample drift cancels).

Mean signed forward move after an MA20 cross, in points: **-1.40** (3 bars), -0.42 (6), -1.47 (12),
-1.00 (24), -1.67 (48), -0.54 (96). Every horizon negative, every |t| < 1.7, every value inside the
random-entry control band (percentile 0.06-0.43). MA10 and MA50 give the same picture (MA50: -0.75,
+0.43, -1.16, -1.55, -2.13, +0.46).

MFE/MAE race - does price reach +x before -x within 96 bars, vs the random-entry control?

| x (pts) | MA20 signals | random control | edge |
|---|---|---|---|
| 10 | 40.7% | 39.8% | +0.9pp |
| 20 | 47.3% | 49.4% | -2.0pp |
| 40 | 48.0% | 48.5% | -0.5pp |
| 60 | 49.5% | 50.1% | -0.6pp |

Per-window mean signed move at a 2h horizon is positive in **1 of 6** windows for both MA20 and MA50.

**An MA cross on NQ 5-min bars is not distinguishable from a randomly timed entry.** Expectancy
before costs is zero-to-negative at every horizon from 15 minutes to 8 hours. No stop, target,
breakeven rule or trail can create positive expectancy from a signal that has none - exit rules only
redistribute a zero-sum pool and then pay costs out of it. That is why the buffer sweep shows a flat
trade-off (bigger winners bought with proportionally fewer of them), and why the 480-config grid is
7/480 rather than the ~165/480 chance alone would give.

### Verdict
**H falsified.** The 2026-09-16 failure was not a parameterization failure. Widening the search to 480
configs across breakeven trigger, trail slack, trail-MA speed, stop width and entry MA does not
produce a config that survives out-of-sample parameter selection (negative rank correlation at all
four splits; winners land below the grid median), a one-step neighbourhood check (13/14 neighbours
negative), a half-window shift (6/8 flip), or a doubled cost assumption (5/8 die). Underneath all of
it, the entry signal has no measurable forward edge versus randomly timed entries.

Two engine bugs were fixed in the process, and the previously logged reason for the 2026-09-16
failure ("the MA trail whipsaws") was substantially a backtester artifact. The corrected engine makes
the trail *much* less bad (-$15,356 -> -$5,235 on the reference config) - but "much less bad" is the
whole of it.

**What this does and does not say.** It says this mechanical translation - SMA cross entry plus a
breakeven-and-trail exit, in any of 480 parameterizations - has no edge on 60 days of NQ 5-min. It
does not say the user's discretionary NQ/MNQ approach has no edge; it says the edge, if it exists, is
not in this entry signal, so no amount of exit-rule search will recover it. **Any further NQ work
should start at the entry, not the exit.** `nq_entry_edge.py` is a ~30-second screen for any
candidate entry rule and should be run *before* any grid: a signal that fails it cannot be rescued
downstream.

### Standing caveats
Same as every other entry here: 60 days, ~10 days per window, one instrument, yfinance continuous
front-month (NQ=F) rather than a properly rolled contract. The entry-edge null is the robust part
(2,442 / 1,713 / 1,020 signals, with controls); the individual grid P&Ls are noise by construction and
should not be quoted as estimates of anything.

### Addendum - the same entry screen on gold (GC=F), since the live bot depends on it

Ran `scripts/nq_entry_edge.py data/gold_5m.csv` (same 13,700-bar sample the gold work uses). Gold is
not as bad as NQ, but it is not distinguishable from random either:

- MA20 cross, mean signed forward move (pts): +0.02 (3 bars), +0.10 (6), -0.03 (12), +0.24 (24),
  +0.12 (48), +0.03 (96). All |t| <= 0.53, all inside the random-entry control band (percentiles
  0.46-0.73). MA10 is the same, centred on zero.
- MFE/MAE race vs random-entry control: +2.8pp at x=10, +2.0pp at 20, **-0.5pp at 40**, +5.1pp at 60
  (only 323 decided). Non-monotone and smaller than the control's own sampling spread.
- Per-window mean 2h move is positive in 5/6 windows for MA20 - the most encouraging number in this
  addendum - but the magnitudes (+0.08 to +0.71 pts) are a fraction of the 0.3pt round-trip cost.

So the gold entry signal is a weak coin-flip rather than NQ's negative one: consistent with the
gold baseline's ~1pp-of-win-rate claimed edge, and with the repeated finding that this edge is
smaller than any nuisance parameter's P&L spread. It does not change the live bot's status (paper
only, untouched this run), and it is one more reason the data problem, not the exit logic, is the
binding constraint.
