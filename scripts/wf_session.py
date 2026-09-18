"""Multi-window walk-forward on FIXED configs (no per-window refitting, so no selection bias).

Hypothesis under test: the "session filter" flagged in RESEARCH_LOG as the best candidate has a
real edge that survives several independent out-of-sample windows, not just one 70/30 split.

Also corrects a labelling bug: yfinance GC=F bars come back in US/Eastern, so the filter previously
logged as "NY session only, 13-21 UTC" was actually filtering 13:00-21:00 **ET**. Both that
as-coded window and the genuine NY RTH window (09:30-16:00 ET) are tested here.

Still a 60-day yfinance sample - windows are ~10 calendar days each, trade counts per window are
small (tens). Directional evidence only.
"""
import numpy as np
import pandas as pd
from backtest import load_data, run_backtest

CONFIGS = {
    "baseline (ma20/stop8/rr2)": dict(ma_period=20, stop_pts=8.0, rr=2.0),
    "session 13-21 ET (as-coded 'best candidate')": dict(ma_period=20, stop_pts=8.0, rr=2.0,
                                                          session_hours=(13, 21)),
    "session 09:30-16:00 ET (true NY RTH)": dict(ma_period=20, stop_pts=8.0, rr=2.0,
                                                  session_hours=((9, 30), (16, 0))),
    "regime100 + confirm2": dict(ma_period=20, stop_pts=8.0, rr=2.0, regime_ma=100, confirm_bars=2),
}

N_WINDOWS = 6


def metrics(eq_df, closed):
    if closed.empty:
        return dict(n=0, win_rate=float("nan"), pnl=0.0, sharpe=float("nan"))
    ret = eq_df["equity"].pct_change().dropna()
    sharpe = ret.mean() / ret.std() * np.sqrt(288 * 252) if ret.std() > 0 else float("nan")
    return dict(n=len(closed), win_rate=(closed.pnl > 0).mean(),
                pnl=closed.pnl.sum(), sharpe=sharpe)


def walk_windows(df, n_windows=N_WINDOWS):
    bounds = np.linspace(0, len(df), n_windows + 1).astype(int)
    rows = []
    for name, cfg in CONFIGS.items():
        for w in range(n_windows):
            win = df.iloc[bounds[w]:bounds[w + 1]]
            eq_df, closed, _ = run_backtest(win, **cfg)
            m = metrics(eq_df, closed)
            rows.append(dict(config=name, window=w,
                             start=str(win.index[0].date()), end=str(win.index[-1].date()), **m))
    return pd.DataFrame(rows)


def hour_of_day(df):
    """Exploratory: baseline P&L by entry hour (ET), train (first 70%) vs test (last 30%)."""
    split = int(len(df) * 0.7)
    out = {}
    for label, part in [("train", df.iloc[:split]), ("test", df.iloc[split:])]:
        _, closed, _ = run_backtest(part, ma_period=20, stop_pts=8.0, rr=2.0)
        closed = closed.copy()
        closed["hour"] = pd.to_datetime(closed["entry_ts"]).dt.hour
        g = closed.groupby("hour").agg(n=("pnl", "size"), pnl=("pnl", "sum"),
                                       win_rate=("pnl", lambda s: (s > 0).mean()))
        out[label] = g
    return out


def rotation_test(df, width=8, n_windows=N_WINDOWS):
    """Falsification control: run the SAME 8h-wide session filter at all 24 start hours.

    If 13-21 ET genuinely captures a time-of-day edge it should stand out from the other 23
    rotations. If it sits mid-pack, its apparent advantage over baseline is just trade-count
    reduction (lower variance around a ~zero-expectancy process), not an edge.
    """
    bounds = np.linspace(0, len(df), n_windows + 1).astype(int)
    rows = []
    for start in range(24):
        end = (start + width) % 24
        pnls, sharpes, ns = [], [], []
        for w in range(n_windows):
            win = df.iloc[bounds[w]:bounds[w + 1]]
            eq_df, closed, _ = run_backtest(win, ma_period=20, stop_pts=8.0, rr=2.0,
                                            session_hours=(start, end))
            m = metrics(eq_df, closed)
            pnls.append(m["pnl"])
            sharpes.append(m["sharpe"])
            ns.append(m["n"])
        rows.append(dict(start_hour_et=start, end_hour_et=end, trades=int(sum(ns)),
                         prof_windows=int(sum(p > 0 for p in pnls)),
                         total_pnl=float(sum(pnls)),
                         median_sharpe=float(np.nanmedian(sharpes))))
    return pd.DataFrame(rows)


def main():
    df = load_data()
    print(f"Data: {len(df)} bars, {df.index[0]} -> {df.index[-1]} (tz={df.index.tz})\n")

    res = walk_windows(df)
    pd.set_option("display.width", 160)
    for name in CONFIGS:
        sub = res[res.config == name]
        print(f"--- {name} ---")
        print(sub[["window", "start", "end", "n", "win_rate", "pnl", "sharpe"]].to_string(index=False))
        prof = (sub.pnl > 0).sum()
        traded = (sub.n > 0).sum()
        print(f"  profitable windows: {prof}/{traded} traded ({N_WINDOWS} total)  "
              f"total pnl ${sub.pnl.sum():,.0f}  median window sharpe {sub.sharpe.median():.2f}\n")
    res.to_csv("data/wf_session_results.csv", index=False)

    print("=== Exploratory: baseline P&L by entry hour (ET) ===")
    hod = hour_of_day(df)
    joined = hod["train"].join(hod["test"], lsuffix="_train", rsuffix="_test", how="outer").fillna(0)
    print(joined.to_string())
    tr, te = joined["pnl_train"], joined["pnl_test"]
    both_pos = ((tr > 0) & (te > 0)).sum()
    print(f"\nHours profitable in BOTH train and test: {both_pos}/{len(joined)}")
    corr = tr.corr(te)
    print(f"Correlation of per-hour P&L, train vs test: {corr:.2f} "
          "(near 0 or negative = no stable time-of-day effect)")

    print("\n=== Falsification control: all 24 rotations of an 8h session window ===")
    rot = rotation_test(df)
    print(rot.sort_values("total_pnl", ascending=False).to_string(index=False))
    rot.to_csv("data/wf_session_rotations.csv", index=False)
    target = rot[rot.start_hour_et == 13].iloc[0]
    rank_pnl = int((rot.total_pnl > target.total_pnl).sum()) + 1
    rank_prof = int((rot.prof_windows > target.prof_windows).sum()) + 1
    print(f"\n13-21 ET rank by total P&L: {rank_pnl}/24   "
          f"rank by profitable windows: {rank_prof}/24 (ties counted as better)")
    print(f"Rotations with >=4/6 profitable windows: {(rot.prof_windows >= 4).sum()}/24")
    print(f"Rotations with positive total P&L: {(rot.total_pnl > 0).sum()}/24")


if __name__ == "__main__":
    main()
