# Gold Algo Trading (Paper Only)

MA-cross 5min strategy, adapted from an NQ/MNQ setup, being tested on gold futures (GC/MGC). **Not validated yet — see status.**

## Status (2026-09-18)
- Baseline backtest (yfinance, 60d, GC=F): positive but cherry-picked-looking (+$1,727 on ma20/stop8/rr2).
- Grid sweep across ma/stop/rr (45 configs, same 60d): **only 10/45 profitable, median Sharpe -1.47.** Edge is fragile / param-sensitive on this sample. Overfitting risk.
- **Session filter DISCARDED (2026-09-18).** Multi-window walk-forward (`scripts/wf_session.py`, 6 independent windows, fixed configs): baseline is profitable in only **2/6** windows — its whole +$933 is two good weeks in late July/early Aug. The session filter's apparent advantage does not survive a control test: rotating the same 8h window through all 24 start hours puts 13-21 ET **9th of 24**, with 17/24 rotations positive and a -$1,354..+$2,398 spread across arbitrary start hours. Per-hour P&L correlates **-0.34** train vs test. No stable time-of-day effect exists in this data. See RESEARCH_LOG.md.
- **Two bugs found and fixed:** the filter logged as "NY session, 13-21 UTC" was actually 13-21 **ET** (yfinance returns US/Eastern); `load_data` was silently dropping the first 2 bars of every backtest.
- **Live paper bot is not faithfully running the strategy.** `scripts/paper_trade.py` only inspects the latest bar per poll, and GH Actions `*/5` cron is not honoured (5-18 min intervals, one 62-min gap) — **225 runs vs 443 bars, ~51% coverage**. Half of all signals are skipped, and stops touched on skipped bars are never booked, which biases live results optimistically. Same-window backtest: -$285 / 26.7% WR vs live +$47 / 36.4%. **The live +$47 is not evidence of anything.** Fix (iterate all bars after `last_processed_bar`) not applied — awaiting user go-ahead, since it changes the running strategy.
- Edge margin for scale: payoff is $157 win / -$83 loss ⇒ breakeven win rate **34.6%** vs measured **35.5%**. The entire claimed edge is ~1pp of win rate.
- Still open: pull longer history (1-2yr) for real walk-forward before trusting any config or switching the live config off baseline.

## Backlog / might try later
- Pull free long-history data from Dukascopy (tick data, no account needed, years back) as a faster proxy for walk-forward testing than waiting on IB signup. Caveat: spot XAUUSD not futures GC/MGC — good enough to validate strategy logic, but final numbers need confirming against real futures data before trusting exact P&L.
- IB Gateway setup (`scripts/ib_fetch_data.py`) — exact contract match, needed eventually regardless of Dukascopy detour.

## Setup
```bash
python -m pip install -r requirements.txt
```

## Scripts
- `scripts/fetch_data.py` — yfinance 5min GC=F, ~60d only (quick sanity check)
- `scripts/ib_fetch_data.py` — IB historical bars, long history, needs IB Gateway/TWS running + paper account (see below)
- `scripts/backtest.py` — MA-cross backtest engine w/ stop/TP risk management
- `scripts/sweep.py` — param grid sweep (in-sample only, don't trust alone)
- `scripts/walk_forward.py` — proper train/test split validation

## IB Paper Trading Setup (required for live-history data + eventual live paper execution)
1. Create IB paper account: interactivebrokers.com
2. Install IB Gateway: ibkr.com/gateway
3. Launch, log in w/ paper account, Configure > Settings > enable API (ActiveX and Socket Clients), note port (default paper: 4002)
4. Leave running, then: `python scripts/ib_fetch_data.py --symbol MGC --duration "2 Y"`

## Known risk (flagged, not resolved)
User previously pushed back on "gold-scalping AI, self-overfitting" as an idea due to overfit risk (see prior buffett-analysis project — H1/1-day horizon there went Sharpe-negative at realistic cost too). Current sweep result is a concrete instance of that risk. Treat any single "great" backtest config with suspicion until it survives walk-forward + a longer sample.
