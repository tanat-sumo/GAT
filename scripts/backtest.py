"""MA-cross backtest, 5min gold futures. Long+short, MGC-sized (10oz, $10/point).
Entry: close crosses and closes past SMA(period). Exit: opposite cross, stop loss, or take profit.
"""
import argparse
import pandas as pd
import numpy as np

CONTRACT_MULT = {"MGC": 10, "GC": 100, "NQ": 20, "MNQ": 2}  # $ per point per contract


def load_data(path="data/gold_5m.csv"):
    df = pd.read_csv(path, index_col=0, parse_dates=True, header=0, skiprows=[1, 2])
    df.columns = ["close", "high", "low", "open", "volume"]
    return df[["open", "high", "low", "close", "volume"]].dropna()


def run_backtest(df, ma_period=20, stop_pts=8.0, tp_pts=None, rr=2.0,
                  contract="MGC", contracts=1, cost_pts=0.3, start_cap=50000,
                  regime_ma=None, session_hours=None, atr_period=None, atr_min_pts=None,
                  confirm_bars=1, trail_mode="fixed", breakeven_r=1.0):
    """
    regime_ma: if set (e.g. 100), only take longs when close > SMA(regime_ma), shorts when close < it
    session_hours: if set, tuple (start_hour, end_hour) in the df's tz - only trade entries inside this window
    atr_period/atr_min_pts: if set, skip entries when ATR(atr_period) < atr_min_pts (too quiet/choppy)
    confirm_bars: require this many consecutive closes past sma before entry (1 = original behavior)
    trail_mode: "fixed" (original: fixed stop + fixed tp) or "ma_trail" (move stop to breakeven at
      breakeven_r * stop_pts favorable move, then trail stop behind the MA itself, no fixed tp - exit
      only when price genuinely trails back through the MA)
    """
    df = df.copy()
    df["sma"] = df["close"].rolling(ma_period).mean()
    if regime_ma:
        df["regime_sma"] = df["close"].rolling(regime_ma).mean()
    if atr_period:
        tr = pd.concat([
            df["high"] - df["low"],
            (df["high"] - df["close"].shift()).abs(),
            (df["low"] - df["close"].shift()).abs(),
        ], axis=1).max(axis=1)
        df["atr"] = tr.rolling(atr_period).mean()
    dropcols = ["sma"] + (["regime_sma"] if regime_ma else []) + (["atr"] if atr_period else [])
    df = df.dropna(subset=dropcols)

    mult = CONTRACT_MULT[contract]
    if tp_pts is None:
        tp_pts = stop_pts * rr

    position = 0  # 1 long, -1 short, 0 flat
    entry_price = None
    stop_price = None
    tp_price = None
    risk_pts = None
    breakeven_hit = False
    equity = start_cap
    trades = []
    equity_curve = []

    prev_close = None
    prev_sma = None
    pending_side = None  # confirm_bars tracking: side awaiting confirmation since the raw cross
    pending_count = 0

    for ts, row in df.iterrows():
        c, h, l = row["close"], row["high"], row["low"]

        # manage open position: trail (if enabled) then check stop/tp intrabar
        if position != 0 and trail_mode == "ma_trail":
            if position == 1:
                if not breakeven_hit and c >= entry_price + breakeven_r * risk_pts:
                    breakeven_hit = True
                    stop_price = max(stop_price, entry_price)
                if breakeven_hit:
                    stop_price = max(stop_price, row["sma"])
            elif position == -1:
                if not breakeven_hit and c <= entry_price - breakeven_r * risk_pts:
                    breakeven_hit = True
                    stop_price = min(stop_price, entry_price)
                if breakeven_hit:
                    stop_price = min(stop_price, row["sma"])

        if position != 0:
            if position == 1:
                if l <= stop_price:
                    pnl = (stop_price - entry_price) * mult * contracts - cost_pts * mult * contracts
                    equity += pnl
                    reason = "trail_stop" if (trail_mode == "ma_trail" and breakeven_hit) else "stop"
                    trades.append({"exit_ts": ts, "side": "long", "reason": reason, "pnl": pnl})
                    position = 0
                elif trail_mode == "fixed" and h >= tp_price:
                    pnl = (tp_price - entry_price) * mult * contracts - cost_pts * mult * contracts
                    equity += pnl
                    trades.append({"exit_ts": ts, "side": "long", "reason": "tp", "pnl": pnl})
                    position = 0
            elif position == -1:
                if h >= stop_price:
                    pnl = (entry_price - stop_price) * mult * contracts - cost_pts * mult * contracts
                    equity += pnl
                    reason = "trail_stop" if (trail_mode == "ma_trail" and breakeven_hit) else "stop"
                    trades.append({"exit_ts": ts, "side": "short", "reason": reason, "pnl": pnl})
                    position = 0
                elif trail_mode == "fixed" and l <= tp_price:
                    pnl = (entry_price - tp_price) * mult * contracts - cost_pts * mult * contracts
                    equity += pnl
                    trades.append({"exit_ts": ts, "side": "short", "reason": "tp", "pnl": pnl})
                    position = 0

        # confirm_bars: track a pending cross and require it to hold for N consecutive bars
        crossed_up = crossed_dn = False
        if prev_close is not None:
            raw_up = prev_close <= prev_sma and c > row["sma"]
            raw_dn = prev_close >= prev_sma and c < row["sma"]
            if raw_up:
                pending_side, pending_count = "up", 1
            elif raw_dn:
                pending_side, pending_count = "dn", 1
            elif pending_side == "up" and c > row["sma"]:
                pending_count += 1
            elif pending_side == "dn" and c < row["sma"]:
                pending_count += 1
            else:
                pending_side, pending_count = None, 0

            if pending_side == "up" and pending_count >= confirm_bars:
                crossed_up = True
                pending_side, pending_count = None, 0
            elif pending_side == "dn" and pending_count >= confirm_bars:
                crossed_dn = True
                pending_side, pending_count = None, 0

        # signal: cross and close past sma, optionally confirmed + filtered
        if prev_close is not None and position == 0:

            if crossed_up and regime_ma and c <= row["regime_sma"]:
                crossed_up = False
            if crossed_dn and regime_ma and c >= row["regime_sma"]:
                crossed_dn = False
            if (crossed_up or crossed_dn) and session_hours:
                # each bound is hour or (hour, minute); compares by minute-of-day for precision
                def _mins(x):
                    return x * 60 if isinstance(x, (int, float)) else x[0] * 60 + x[1]
                now_min = ts.hour * 60 + ts.minute
                start_m, end_m = _mins(session_hours[0]), _mins(session_hours[1])
                in_session = (start_m <= now_min < end_m) if start_m < end_m else (now_min >= start_m or now_min < end_m)
                if not in_session:
                    crossed_up = crossed_dn = False
            if (crossed_up or crossed_dn) and atr_period and row["atr"] < atr_min_pts:
                crossed_up = crossed_dn = False

            if crossed_up:
                position = 1
                entry_price = c
                stop_price = c - stop_pts
                tp_price = c + tp_pts
                risk_pts = stop_pts
                breakeven_hit = False
                trades.append({"entry_ts": ts, "side": "long", "entry_price": c})
            elif crossed_dn:
                position = -1
                entry_price = c
                stop_price = c + stop_pts
                tp_price = c - tp_pts
                risk_pts = stop_pts
                breakeven_hit = False
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
    ap.add_argument("--contract", default="MGC", choices=["MGC", "GC", "NQ", "MNQ"])
    ap.add_argument("--data", default="data/gold_5m.csv")
    ap.add_argument("--contracts", type=int, default=1)
    ap.add_argument("--cost", type=float, default=0.3, help="round-trip cost in points (spread+comm)")
    args = ap.parse_args()

    df = load_data(args.data)
    eq_df, closed, final = run_backtest(
        df, ma_period=args.ma, stop_pts=args.stop, rr=args.rr,
        contract=args.contract, contracts=args.contracts, cost_pts=args.cost,
    )
    print(f"MA={args.ma} stop={args.stop}pts rr={args.rr} contract={args.contract}x{args.contracts} cost={args.cost}pts")
    stats(eq_df, closed, start_cap=50000)
    closed.to_csv("data/backtest_trades.csv", index=False)
    eq_df.to_csv("data/backtest_equity.csv")
