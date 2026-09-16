# Gold Algo Trading (Paper Only)

MA-cross 5min strategy, adapted from an NQ/MNQ setup, being tested on gold futures (GC/MGC). **Not validated yet — see status.**

## Status (2026-09-16)
- Baseline backtest (yfinance, 60d, GC=F): positive but cherry-picked-looking (+$1,727 on ma20/stop8/rr2).
- Grid sweep across ma/stop/rr (45 configs, same 60d): **only 10/45 profitable, median Sharpe -1.47.** Edge is fragile / param-sensitive on this sample. Overfitting risk.
- Next: pull 1-2yr 5min history via IB (`scripts/ib_fetch_data.py`, needs IB Gateway running on paper acct) and run `scripts/walk_forward.py` (proper train/test split) before trusting any config.
- **Do not paper trade live until walk-forward shows OOS Sharpe holds up.**

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
