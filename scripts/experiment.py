"""Run strategy variants, evaluate on train/test split of available data, append results to RESEARCH_LOG.md.
Data is still only 60d (yfinance) - numbers here are directional, not final proof. Re-run once IB long history is in.
"""
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from backtest import load_data, run_backtest

LOG_PATH = "RESEARCH_LOG.md"


def eval_variant(df, **kwargs):
    eq_df, closed, _ = run_backtest(df, **kwargs)
    if closed.empty:
        return dict(n=0, win_rate=0, pnl=0, sharpe=float("nan"), max_dd=0)
    n = len(closed)
    win_rate = (closed.pnl > 0).mean()
    pnl = closed.pnl.sum()
    ret = eq_df["equity"].pct_change().dropna()
    sharpe = ret.mean() / ret.std() * np.sqrt(288 * 252) if ret.std() > 0 else float("nan")
    running_max = eq_df["equity"].cummax()
    max_dd = ((eq_df["equity"] - running_max) / running_max).min() * 100
    return dict(n=n, win_rate=win_rate, pnl=pnl, sharpe=sharpe, max_dd=max_dd)


def fmt(r):
    return f"trades={r['n']}, win_rate={r['win_rate']:.1%}, pnl=${r['pnl']:,.0f}, sharpe={r['sharpe']:.2f}, max_dd={r['max_dd']:.1f}%"


VARIANTS = {
    "baseline (ma20/stop8/rr2, no filters)": dict(ma_period=20, stop_pts=8.0, rr=2.0),
    "+ regime filter (SMA100 trend, only trade with it)": dict(ma_period=20, stop_pts=8.0, rr=2.0, regime_ma=100),
    "+ confirm_bars=2 (needs 2 closes past sma, cuts false crosses)": dict(ma_period=20, stop_pts=8.0, rr=2.0, confirm_bars=2),
    "+ session filter (NY session only, 13-21 UTC)": dict(ma_period=20, stop_pts=8.0, rr=2.0, session_hours=(13, 21)),
    "+ ATR volatility filter (skip quiet bars, atr14 >= 3pts)": dict(ma_period=20, stop_pts=8.0, rr=2.0, atr_period=14, atr_min_pts=3.0),
    "+ regime + confirm_bars=2 combined": dict(ma_period=20, stop_pts=8.0, rr=2.0, regime_ma=100, confirm_bars=2),
}


def main():
    df = load_data()
    split = int(len(df) * 0.7)
    train, test = df.iloc[:split], df.iloc[split:]

    lines = [f"\n## Experiment batch {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
             f"Data: yfinance GC=F 5min, {len(df)} bars ({df.index[0]} to {df.index[-1]}) - **60-day sample, not long-history, treat as directional only**",
             f"Split: train={len(train)} bars (first 70%), test={len(test)} bars (last 30%, out-of-sample)\n",
             "| Variant | Train | Test (OOS) | Verdict |",
             "|---|---|---|---|"]

    print(f"Train: {len(train)} bars, Test: {len(test)} bars\n")
    for name, cfg in VARIANTS.items():
        train_r = eval_variant(train, **cfg)
        test_r = eval_variant(test, **cfg)
        verdict = "KEEP - holds OOS" if (test_r["sharpe"] > 0 and test_r["pnl"] > 0) else "DISCARD - fails OOS"
        print(f"{name}\n  train: {fmt(train_r)}\n  test:  {fmt(test_r)}\n  -> {verdict}\n")
        lines.append(f"| {name} | {fmt(train_r)} | {fmt(test_r)} | {verdict} |")

    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Logged to {LOG_PATH}")


if __name__ == "__main__":
    main()
