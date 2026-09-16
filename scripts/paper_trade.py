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
    state = load_state()
    cfg = state["config"]
    mult = CONTRACT_MULT[cfg["contract"]]

    df = fetch_recent()
    df["sma"] = df["close"].rolling(cfg["ma_period"]).mean()
    df = df.dropna(subset=["sma"])
    if len(df) < 2:
        print("Not enough bars yet.")
        return

    last_ts = str(df.index[-1])
    if state["last_processed_bar"] == last_ts:
        print(f"No new bar since {last_ts}. Nothing to do.")
        return

    row = df.iloc[-1]
    prev = df.iloc[-2]
    c, h, l = row["close"], row["high"], row["low"]
    pos = state["position"]

    # manage open position: stop/tp
    if pos is not None:
        if pos["side"] == "long":
            if l <= pos["stop"]:
                pnl = (pos["stop"] - pos["entry_price"]) * mult * pos["contracts"] - cfg["cost_pts"] * mult * pos["contracts"]
                state["capital"] += pnl
                state["trades"].append({**pos, "exit_ts": last_ts, "exit_price": pos["stop"], "reason": "stop", "pnl": pnl})
                state["position"] = None
                print(f"STOP hit long @ {pos['stop']}, pnl ${pnl:.2f}")
            elif h >= pos["tp"]:
                pnl = (pos["tp"] - pos["entry_price"]) * mult * pos["contracts"] - cfg["cost_pts"] * mult * pos["contracts"]
                state["capital"] += pnl
                state["trades"].append({**pos, "exit_ts": last_ts, "exit_price": pos["tp"], "reason": "tp", "pnl": pnl})
                state["position"] = None
                print(f"TP hit long @ {pos['tp']}, pnl ${pnl:.2f}")
        elif pos["side"] == "short":
            if h >= pos["stop"]:
                pnl = (pos["entry_price"] - pos["stop"]) * mult * pos["contracts"] - cfg["cost_pts"] * mult * pos["contracts"]
                state["capital"] += pnl
                state["trades"].append({**pos, "exit_ts": last_ts, "exit_price": pos["stop"], "reason": "stop", "pnl": pnl})
                state["position"] = None
                print(f"STOP hit short @ {pos['stop']}, pnl ${pnl:.2f}")
            elif l <= pos["tp"]:
                pnl = (pos["entry_price"] - pos["tp"]) * mult * pos["contracts"] - cfg["cost_pts"] * mult * pos["contracts"]
                state["capital"] += pnl
                state["trades"].append({**pos, "exit_ts": last_ts, "exit_price": pos["tp"], "reason": "tp", "pnl": pnl})
                state["position"] = None
                print(f"TP hit short @ {pos['tp']}, pnl ${pnl:.2f}")

    # entry: cross and close past sma, only if flat
    if state["position"] is None:
        crossed_up = prev["close"] <= prev["sma"] and c > row["sma"]
        crossed_dn = prev["close"] >= prev["sma"] and c < row["sma"]
        if crossed_up:
            state["position"] = {
                "side": "long", "entry_ts": last_ts, "entry_price": float(c),
                "stop": float(c - cfg["stop_pts"]), "tp": float(c + cfg["stop_pts"] * cfg["rr"]),
                "contracts": cfg["contracts"],
            }
            print(f"ENTER long @ {c:.2f}, stop {state['position']['stop']:.2f}, tp {state['position']['tp']:.2f}")
        elif crossed_dn:
            state["position"] = {
                "side": "short", "entry_ts": last_ts, "entry_price": float(c),
                "stop": float(c + cfg["stop_pts"]), "tp": float(c - cfg["stop_pts"] * cfg["rr"]),
                "contracts": cfg["contracts"],
            }
            print(f"ENTER short @ {c:.2f}, stop {state['position']['stop']:.2f}, tp {state['position']['tp']:.2f}")
        else:
            print(f"No signal. close={c:.2f} sma={row['sma']:.2f}")
    else:
        print(f"Holding {state['position']['side']} @ {state['position']['entry_price']}. close={c:.2f}")

    state["last_processed_bar"] = last_ts
    if not dry_run:
        save_state(state)

    closed = [t for t in state["trades"]]
    n_trades = len(closed)
    total_pnl = sum(t["pnl"] for t in closed)
    print(f"Capital: ${state['capital']:,.2f}  Trades: {n_trades}  Total P&L: ${total_pnl:,.2f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="don't save state, just show what would happen")
    args = ap.parse_args()
    run_once(dry_run=args.dry_run)
