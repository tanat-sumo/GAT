"""Walk-forward validation: pick best config on train window, test unseen window, repeat.
Avoids the in-sample overfitting trap the first sweep fell into.
"""
import argparse
import pandas as pd
import numpy as np
from backtest import run_backtest

GRID = [(ma, stop, rr) for ma in [10, 15, 20, 30, 50]
                        for stop in [5, 8, 12]
                        for rr in [1.5, 2, 3]]


def sharpe_of(df, ma, stop, rr, cost_pts=0.3):
    eq_df, closed, _ = run_backtest(df, ma_period=ma, stop_pts=stop, rr=rr, cost_pts=cost_pts)
    if closed.empty or len(closed) < 10:
        return -999, 0
    ret = eq_df["equity"].pct_change().dropna()
    sharpe = ret.mean() / ret.std() * np.sqrt(288 * 252) if ret.std() > 0 else -999
    return sharpe, closed.pnl.sum()


def walk_forward(df, n_splits=5, train_frac=0.7):
    n = len(df)
    fold_size = n // n_splits
    results = []
    for i in range(n_splits):
        start = i * fold_size
        end = start + fold_size if i < n_splits - 1 else n
        fold = df.iloc[start:end]
        split = int(len(fold) * train_frac)
        train, test = fold.iloc[:split], fold.iloc[split:]
        if len(train) < 200 or len(test) < 50:
            continue

        best_cfg, best_sharpe = None, -999
        for ma, stop, rr in GRID:
            s, _ = sharpe_of(train, ma, stop, rr)
            if s > best_sharpe:
                best_sharpe, best_cfg = s, (ma, stop, rr)

        test_sharpe, test_pnl = sharpe_of(test, *best_cfg)
        results.append(dict(fold=i, best_cfg=best_cfg, train_sharpe=best_sharpe,
                             test_sharpe=test_sharpe, test_pnl=test_pnl))
    return pd.DataFrame(results)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/gold_5m_ib.csv")
    ap.add_argument("--splits", type=int, default=5)
    args = ap.parse_args()

    df = pd.read_csv(args.data, index_col=0, parse_dates=True)
    res = walk_forward(df, n_splits=args.splits)
    print(res.to_string(index=False))
    print(f"\nOut-of-sample profitable folds: {(res.test_pnl > 0).sum()}/{len(res)}")
    print(f"Mean OOS Sharpe: {res.test_sharpe.mean():.2f}  Mean train Sharpe: {res.train_sharpe.mean():.2f}")
    print("(train >> test Sharpe gap = overfitting)")
