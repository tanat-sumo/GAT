"""Local paper trading sim, no broker account. Poll yfinance GC=F 5min bars,
run same MA-cross+stop/TP logic as backtest.py, track state in paper_trade/state.json.
NOT OOS-validated yet (see README) - defaults match backtest.py's baseline config.
Run this every 5min (manually or via scheduled task) during market hours.
"""
import json
import argparse
from pathlib import Path
from datetime import datetime, timezone
import yfinance as yf
import pandas as pd

STATE_PATH = Path("paper_trade/state.json")
CONTRACT_MULT = {"MGC": 10, "GC": 100}

DEFAULTS = dict(ma_period=20, stop_pts=8.0, rr=2.0, contract="MGC", contracts=1,
                cost_pts=0.3, start_cap=50000.0)


def load_state():
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {
        "capital": DEFAULTS["start_cap"],
        "position": None,
        "trades": [],
        "last_processed_bar": None,
        "config": DEFAULTS,
    }


def save_state(state):
    STATE_PATH.parent.mkdir(exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, default=str))


def fetch_recent(period="5d"):
    df = yf.download("GC=F", period=period, interval="5m", auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.lower() for c in df.columns]
    return df.dropna()


def run_once(dry_run=False):
    """Walks every new bar since last_processed_bar in order, not just the latest one.
    The 5min GH Actions cron isn't reliable (observed 5-18min gaps, up to 62min) - if we only
    ever looked at df.iloc[-1], a missed bar's stop/tp touch would silently vanish (price could
    recover by the next poll, so the loss never gets booked) and entries on skipped bars would
    never fire. yfinance's rolling fetch window still has that OHLC data, so replay it instead.
    """
    state = load_state()
    cfg = state["config"]
    mult = CONTRACT_MULT[cfg["contract"]]

    df = fetch_recent()
    df["sma"] = df["close"].rolling(cfg["ma_period"]).mean()
    df = df.dropna(subset=["sma"])
    if len(df) < 2:
        print("Not enough bars yet.")
        return

    last_seen = state["last_processed_bar"]
    if last_seen is not None:
        last_seen_ts = pd.Timestamp(last_seen)
        prior = df[df.index <= last_seen_ts]
        new_bars = df[df.index > last_seen_ts]
        if prior.empty:
            print(f"WARNING: last_processed_bar {last_seen} fell outside the current fetch "
                  f"window - bootstrapping cross-detection from the earliest available bar.")
            prev_close, prev_sma = df.iloc[0]["close"], df.iloc[0]["sma"]
            new_bars = df.iloc[1:]
        else:
            prev_close, prev_sma = prior.iloc[-1]["close"], prior.iloc[-1]["sma"]
    else:
        prev_close, prev_sma = df.iloc[0]["close"], df.iloc[0]["sma"]
        new_bars = df.iloc[1:]

    if new_bars.empty:
        print(f"No new bar since {last_seen}. Nothing to do.")
        return

    for ts, row in new_bars.iterrows():
        c, h, l = row["close"], row["high"], row["low"]
        pos = state["position"]

        # manage open position: stop/tp intrabar, checked on every bar in order
        if pos is not None:
            if pos["side"] == "long":
                if l <= pos["stop"]:
                    pnl = (pos["stop"] - pos["entry_price"]) * mult * pos["contracts"] - cfg["cost_pts"] * mult * pos["contracts"]
                    state["capital"] += pnl
                    state["trades"].append({**pos, "exit_ts": str(ts), "exit_price": pos["stop"], "reason": "stop", "pnl": pnl})
                    state["position"] = None
                    print(f"[{ts}] STOP hit long @ {pos['stop']}, pnl ${pnl:.2f}")
                elif h >= pos["tp"]:
                    pnl = (pos["tp"] - pos["entry_price"]) * mult * pos["contracts"] - cfg["cost_pts"] * mult * pos["contracts"]
                    state["capital"] += pnl
                    state["trades"].append({**pos, "exit_ts": str(ts), "exit_price": pos["tp"], "reason": "tp", "pnl": pnl})
                    state["position"] = None
                    print(f"[{ts}] TP hit long @ {pos['tp']}, pnl ${pnl:.2f}")
            elif pos["side"] == "short":
                if h >= pos["stop"]:
                    pnl = (pos["entry_price"] - pos["stop"]) * mult * pos["contracts"] - cfg["cost_pts"] * mult * pos["contracts"]
                    state["capital"] += pnl
                    state["trades"].append({**pos, "exit_ts": str(ts), "exit_price": pos["stop"], "reason": "stop", "pnl": pnl})
                    state["position"] = None
                    print(f"[{ts}] STOP hit short @ {pos['stop']}, pnl ${pnl:.2f}")
                elif l <= pos["tp"]:
                    pnl = (pos["entry_price"] - pos["tp"]) * mult * pos["contracts"] - cfg["cost_pts"] * mult * pos["contracts"]
                    state["capital"] += pnl
                    state["trades"].append({**pos, "exit_ts": str(ts), "exit_price": pos["tp"], "reason": "tp", "pnl": pnl})
                    state["position"] = None
                    print(f"[{ts}] TP hit short @ {pos['tp']}, pnl ${pnl:.2f}")

        # entry: cross and close past sma, only if flat
        if state["position"] is None:
            crossed_up = prev_close <= prev_sma and c > row["sma"]
            crossed_dn = prev_close >= prev_sma and c < row["sma"]
            if crossed_up:
                state["position"] = {
                    "side": "long", "entry_ts": str(ts), "entry_price": float(c),
                    "stop": float(c - cfg["stop_pts"]), "tp": float(c + cfg["stop_pts"] * cfg["rr"]),
                    "contracts": cfg["contracts"],
                }
                print(f"[{ts}] ENTER long @ {c:.2f}, stop {state['position']['stop']:.2f}, tp {state['position']['tp']:.2f}")
            elif crossed_dn:
                state["position"] = {
                    "side": "short", "entry_ts": str(ts), "entry_price": float(c),
                    "stop": float(c + cfg["stop_pts"]), "tp": float(c - cfg["stop_pts"] * cfg["rr"]),
                    "contracts": cfg["contracts"],
                }
                print(f"[{ts}] ENTER short @ {c:.2f}, stop {state['position']['stop']:.2f}, tp {state['position']['tp']:.2f}")

        prev_close, prev_sma = c, row["sma"]

    state["last_processed_bar"] = str(new_bars.index[-1])
    if not dry_run:
        save_state(state)

    closed = [t for t in state["trades"]]
    n_trades = len(closed)
    total_pnl = sum(t["pnl"] for t in closed)
    print(f"Processed {len(new_bars)} new bar(s). Capital: ${state['capital']:,.2f}  Trades: {n_trades}  Total P&L: ${total_pnl:,.2f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="don't save state, just show what would happen")
    args = ap.parse_args()
    run_once(dry_run=args.dry_run)
