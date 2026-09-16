# Gold Algo Trading (Paper Only)

MA-cross 5min strategy, adapted from an NQ/MNQ setup, being tested on gold futures (GC/MGC). **Not validated yet — see status.**

## Status (2026-09-16)
- Baseline backtest (yfinance, 60d, GC=F): positive but cherry-picked-looking (+$1,727 on ma20/stop8/rr2).
- Grid sweep across ma/stop/rr (45 configs, same 60d): **only 10/45 profitable, median Sharpe -1.47.** Edge is fragile / param-sensitive on this sample. Overfitting risk.
- Experiment batch (train/test split, see RESEARCH_LOG.md): session-hours filter and regime+confirm_bars combo look most consistent train->test, but small sample (49-174 OOS trades), not proof.
- **Paper trading IS live** (user decision, running anyway since it's fake money) — `scripts/paper_trade.py` runs every 5min via GitHub Actions (`.github/workflows/paper_trade.yml`), still on the unvalidated baseline config (ma20/stop8/rr2, no filters). Runs independent of any local machine.
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
