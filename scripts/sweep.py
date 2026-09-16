"""Param sweep to check robustness of MA-cross edge (not just one lucky config)."""
import pandas as pd
import numpy as np
from backtest import load_data, run_backtest

df = load_data()
results = []
for ma in [10, 15, 20, 30, 50]:
    for stop in [5, 8, 12]:
        for rr in [1.5, 2, 3]:
            eq_df, closed, final = run_backtest(df, ma_period=ma, stop_pts=stop, rr=rr, cost_pts=0.3)
            if closed.empty:
                continue
            n = len(closed)
            wins = closed[closed.pnl > 0]
            win_rate = len(wins) / n
            total_pnl = closed.pnl.sum()
            ret = eq_df["equity"].pct_change().dropna()
            sharpe = ret.mean() / ret.std() * np.sqrt(288 * 252) if ret.std() > 0 else float("nan")
            running_max = eq_df["equity"].cummax()
            max_dd = ((eq_df["equity"] - running_max) / running_max).min() * 100
            results.append(dict(ma=ma, stop=stop, rr=rr, n=n, win_rate=win_rate,
                                 pnl=total_pnl, sharpe=sharpe, max_dd=max_dd))

res = pd.DataFrame(results).sort_values("sharpe", ascending=False)
pd.set_option("display.width", 140)
print(res.to_string(index=False))
print(f"\nProfitable configs: {(res.pnl > 0).sum()}/{len(res)}")
print(f"Median Sharpe: {res.sharpe.median():.2f}  Median PnL: ${res.pnl.median():.0f}")
res.to_csv("data/sweep_results.csv", index=False)
