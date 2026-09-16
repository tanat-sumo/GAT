"""MA-cross backtest, 5min gold futures. Long+short, MGC-sized (10oz, $10/point).
Entry: close crosses and closes past SMA(period). Exit: opposite cross, stop loss, or take profit.
"""
import argparse
import pandas as pd
import numpy as np

MGC_MULT = 10  # $ per point, Micro Gold futures
CONTRACT_MULT = {"MGC": 10, "GC": 100}


def load_data(path="data/gold_5m.csv"):
    df = pd.read_csv(path, index_col=0, parse_dates=True, header=0, skiprows=[1, 2])
    df.columns = ["close", "high", "low", "open", "volume"]
    return df[["open", "high", "low", "close", "volume"]].dropna()


def run_backtest(df, ma_period=20, stop_pts=8.0, tp_pts=None, rr=2.0,
                  contract="MGC", contracts=1, cost_pts=0.3, start_cap=50000):
    df = df.copy()
    df["sma"] = df["close"].rolling(ma_period).mean()
    df = df.dropna(subset=["sma"])

    mult = CONTRACT_MULT[contract]
    if tp_pts is None:
        tp_pts = stop_pts * rr

    position = 0  # 1 long, -1 short, 0 flat
    entry_price = None
    stop_price = None
    tp_price = None
    equity = start_cap
    trades = []
    equity_curve = []

    prev_close = None
    prev_sma = None

    for ts, row in df.iterrows():
        c, h, l = row["close"], row["high"], row["low"]

        # manage open position: check stop/tp intrabar first
        if position != 0:
            if position == 1:
                if l <= stop_price:
                    pnl = (stop_price - entry_price) * mult * contracts - cost_pts * mult * contracts
                    equity += pnl
                    trades.append({"exit_ts": ts, "side": "long", "reason": "stop", "pnl": pnl})
                    position = 0
                elif h >= tp_price:
                    pnl = (tp_price - entry_price) * mult * contracts - cost_pts * mult * contracts
                    equity += pnl
                    trades.append({"exit_ts": ts, "side": "long", "reason": "tp", "pnl": pnl})
                    position = 0
            elif position == -1:
                if h >= stop_price:
                    pnl = (entry_price - stop_price) * mult * contracts - cost_pts * mult * contracts
                    equity += pnl
                    trades.append({"exit_ts": ts, "side": "short", "reason": "stop", "pnl": pnl})
                    position = 0
                elif l <= tp_price:
                    pnl = (entry_price - tp_price) * mult * contracts - cost_pts * mult * contracts
                    equity += pnl
                    trades.append({"exit_ts": ts, "side": "short", "reason": "tp", "pnl": pnl})
                    position = 0

        # signal: cross and close past sma
        if prev_close is not None and position == 0:
            crossed_up = prev_close <= prev_sma and c > row["sma"]
            crossed_dn = prev_close >= prev_sma and c < row["sma"]
            if crossed_up:
                position = 1
                entry_price = c
                stop_price = c - stop_pts
                tp_price = c + tp_pts
                trades.append({"entry_ts": ts, "side": "long", "entry_price": c})
            elif crossed_dn:
                position = -1
                entry_price = c
                stop_price = c + stop_pts
                tp_price = c - tp_pts
                trades.append({"entry_ts": ts, "side": "short", "entry_price": c})

        prev_close, prev_sma = c, row["sma"]
        equity_curve.append({"ts": ts, "equity": equity})

    eq_df = pd.DataFrame(equity_curve).set_index("ts")
    trade_df = pd.DataFrame(trades)
    closed = trade_df[trade_df.get("pnl").notna()] if "pnl" in trade_df.columns else pd.DataFrame()
    return eq_df, closed, equity


def stats(eq_df, closed, start_cap):
    if closed.empty:
        print("No closed trades.")
        return
    n = len(closed)
    wins = closed[closed.pnl > 0]
    losses = closed[closed.pnl <= 0]
    win_rate = len(wins) / n
    avg_win = wins.pnl.mean() if len(wins) else 0
    avg_loss = losses.pnl.mean() if len(losses) else 0
    total_pnl = closed.pnl.sum()
    final_eq = start_cap + total_pnl
    ret_pct = total_pnl / start_cap * 100

    ret = eq_df["equity"].pct_change().dropna()
    bars_per_year = 288 * 252  # ~24h*12(5min)*252d futures approx; rough
    sharpe = ret.mean() / ret.std() * np.sqrt(bars_per_year) if ret.std() > 0 else float("nan")

    running_max = eq_df["equity"].cummax()
    dd = (eq_df["equity"] - running_max) / running_max
    max_dd = dd.min() * 100

    print(f"Trades: {n}  Win rate: {win_rate:.1%}")
    print(f"Avg win: ${avg_win:.2f}  Avg loss: ${avg_loss:.2f}  Payoff ratio: {abs(avg_win/avg_loss):.2f}" if avg_loss else "")
    print(f"Total P&L: ${total_pnl:,.2f}  Return: {ret_pct:.1f}%  Final equity: ${final_eq:,.2f}")
    print(f"Sharpe (rough, bar-freq annualized): {sharpe:.2f}")
    print(f"Max drawdown: {max_dd:.1f}%")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--ma", type=int, default=20)
    ap.add_argument("--stop", type=float, default=8.0)
    ap.add_argument("--rr", type=float, default=2.0)
    ap.add_argument("--contract", default="MGC", choices=["MGC", "GC"])
    ap.add_argument("--contracts", type=int, default=1)
    ap.add_argument("--cost", type=float, default=0.3, help="round-trip cost in points (spread+comm)")
    args = ap.parse_args()

    df = load_data()
    eq_df, closed, final = run_backtest(
        df, ma_period=args.ma, stop_pts=args.stop, rr=args.rr,
        contract=args.contract, contracts=args.contracts, cost_pts=args.cost,
    )
    print(f"MA={args.ma} stop={args.stop}pts rr={args.rr} contract={args.contract}x{args.contracts} cost={args.cost}pts")
    stats(eq_df, closed, start_cap=50000)
    closed.to_csv("data/backtest_trades.csv", index=False)
    eq_df.to_csv("data/backtest_equity.csv")
