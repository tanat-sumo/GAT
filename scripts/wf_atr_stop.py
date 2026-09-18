"""Hypothesis test: is the baseline's FIXED 8-point stop the thing that's broken?

Motivation. Every filter tried so far (session, regime, confirm_bars) is the same shape: it throws
entries away, which shrinks trade count, which shrinks variance, which can masquerade as an edge.
The 2026-09-18 rotation control killed the session filter for exactly that reason. So this run tests
something with a different shape: keep every entry, change only the *risk geometry*.

HYPOTHESIS (single, falsifiable)
  H: the 8-point stop is a constant point distance applied to an instrument whose 5-min volatility
     varies a lot over the sample. Sizing the stop to volatility instead - stop = k * ATR(14) at the
     entry bar, target = rr * that - produces a stable improvement over fixed-8 across multiple
     independent windows, AND that improvement comes from *adapting to volatility*, not merely from
     the average stop happening to be wider.

Predictions, each with its own control:
  P1  ATR-sized stops beat fixed-8 across 6 independent non-overlapping windows (not one split).
  P2  CONTROL - matched width. For each k, a FIXED stop set at that k's median realized distance
      must do materially worse. If matched-width fixed ~= ATR-adaptive, then only width mattered and
      "adaptivity" is an illusion -> H falsified in the only form that's interesting.
  P3  CONTROL - decoupled volatility (the direct analogue of the session rotation control). Re-run
      each k with the ATR series circularly time-shifted, so stop widths keep an identical
      distribution but no longer correspond to the volatility actually present at the entry bar. If
      real-ATR ~= shifted-ATR, the adaptivity carries no information -> H falsified.
  P4  CONTROL - neutral width sweep. Fixed stops across 3..24 pts over the same 6 windows, to see
      whether any width is genuinely special or the whole width axis is noise (and where 8 sits).

Premise check first: does ATR at entry predict trade outcome at all under the current fixed stop?
If not, H is unlikely to survive and we should say so up front rather than after the fact.

Same standing caveat as everything else here: 60-day yfinance GC=F 5min sample, ~10 days per window,
tens of trades per window. Directional evidence only.
"""
import numpy as np
import pandas as pd
from backtest import load_data, run_backtest

N_WINDOWS = 6
ATR_PERIOD = 14
K_VALUES = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0]
FIXED_WIDTHS = [3, 4, 5, 6, 8, 10, 12, 16, 20, 24]
SHIFTS = [2000, 4000, 6000, 8000, 10000]  # bars; circular shifts for the decoupling control
RR = 2.0
BASE = dict(ma_period=20, rr=RR)


def atr_full(df, period=ATR_PERIOD):
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift()).abs(),
        (df["low"] - df["close"].shift()).abs(),
    ], axis=1).max(axis=1)
    # bfill the leading NaNs so injected and shifted series cover identical bars (no bar-set drift
    # between the test arm and its controls)
    return tr.rolling(period).mean().bfill()


def metrics(eq_df, closed):
    if closed.empty:
        return dict(n=0, win_rate=float("nan"), pnl=0.0, sharpe=float("nan"),
                    med_stop=float("nan"))
    ret = eq_df["equity"].pct_change().dropna()
    sharpe = ret.mean() / ret.std() * np.sqrt(288 * 252) if ret.std() > 0 else float("nan")
    return dict(n=len(closed), win_rate=(closed.pnl > 0).mean(), pnl=closed.pnl.sum(),
                sharpe=sharpe, med_stop=closed.stop_dist.median())


def windows(df, n=N_WINDOWS):
    b = np.linspace(0, len(df), n + 1).astype(int)
    return [df.iloc[b[i]:b[i + 1]] for i in range(n)]


def run_over_windows(wins, atr=None, **cfg):
    """Run one fixed config over every window; return per-window metric dicts."""
    out = []
    for w in wins:
        kw = dict(cfg)
        if atr is not None:
            kw["atr_series"] = atr
            kw["atr_period"] = ATR_PERIOD
        eq, closed, _ = run_backtest(w, **BASE, **kw)
        out.append(metrics(eq, closed))
    return out


def agg(rows, label):
    pnls = [r["pnl"] for r in rows]
    return dict(config=label, trades=int(sum(r["n"] for r in rows)),
                prof_windows=int(sum(p > 0 for p in pnls)), total_pnl=float(sum(pnls)),
                median_sharpe=float(np.nanmedian([r["sharpe"] for r in rows])),
                win_rate=float(np.nansum([r["win_rate"] * r["n"] for r in rows])
                               / max(sum(r["n"] for r in rows), 1)),
                med_stop=float(np.nanmedian([r["med_stop"] for r in rows])))


def premise_check(df, atr):
    """Does volatility at entry predict anything under the CURRENT fixed 8pt stop?"""
    _, closed, _ = run_backtest(df, **BASE, stop_pts=8.0)
    closed = closed.copy()
    closed["atr_at_entry"] = pd.to_datetime(closed["entry_ts"]).map(atr)
    closed["q"] = pd.qcut(closed["atr_at_entry"], 5, labels=[1, 2, 3, 4, 5])
    g = closed.groupby("q", observed=True).agg(
        n=("pnl", "size"), atr_lo=("atr_at_entry", "min"), atr_hi=("atr_at_entry", "max"),
        win_rate=("pnl", lambda s: (s > 0).mean()), pnl=("pnl", "sum"),
        avg_pnl=("pnl", "mean"))
    corr = closed["atr_at_entry"].corr(closed["pnl"])
    return g, corr, closed


def main():
    df = load_data()
    atr = atr_full(df)
    wins = windows(df)
    pd.set_option("display.width", 200)
    print(f"Data: {len(df)} bars, {df.index[0]} -> {df.index[-1]} (tz={df.index.tz})")
    print(f"ATR({ATR_PERIOD}) over sample: median {atr.median():.2f} pts, "
          f"10th pct {atr.quantile(.1):.2f}, 90th pct {atr.quantile(.9):.2f}, "
          f"max {atr.max():.2f}  -> fixed 8pt stop = {8 / atr.median():.2f}x median ATR")
    print(f"Windows: {N_WINDOWS} non-overlapping, "
          + ", ".join(f"{w.index[0].date()}..{w.index[-1].date()}" for w in wins) + "\n")

    # --- premise check -------------------------------------------------------------------
    print("=== Premise: ATR at entry vs outcome, baseline fixed 8pt stop (full sample) ===")
    g, corr, base_closed = premise_check(df, atr)
    print(g.to_string())
    print(f"corr(ATR at entry, trade P&L) = {corr:.3f}\n")

    rows = []

    # --- P1: main test -------------------------------------------------------------------
    fixed8 = run_over_windows(wins, stop_pts=8.0)
    rows.append(agg(fixed8, "FIXED 8pt (baseline)"))
    atr_rows = {}
    for k in K_VALUES:
        r = run_over_windows(wins, atr=atr, stop_mode="atr", atr_stop_mult=k)
        atr_rows[k] = r
        rows.append(agg(r, f"ATR stop k={k}"))

    # --- P2: matched-width control -------------------------------------------------------
    matched = {}
    for k in K_VALUES:
        med = float(np.nanmedian([x["med_stop"] for x in atr_rows[k]]))
        r = run_over_windows(wins, stop_pts=med)
        matched[k] = (med, r)
        rows.append(agg(r, f"CONTROL fixed @ k={k} median ({med:.1f}pt)"))

    # --- P3: decoupled-volatility control ------------------------------------------------
    shifted = {}
    for k in K_VALUES:
        per_shift = []
        for s in SHIFTS:
            sh = pd.Series(np.roll(atr.values, s), index=atr.index)
            per_shift.append(agg(run_over_windows(wins, atr=sh, stop_mode="atr",
                                                  atr_stop_mult=k), f"shift{s}"))
        shifted[k] = per_shift

    # --- P4: neutral fixed-width sweep ---------------------------------------------------
    width_rows = []
    for wdt in FIXED_WIDTHS:
        width_rows.append(agg(run_over_windows(wins, stop_pts=float(wdt)), f"fixed {wdt}pt"))

    res = pd.DataFrame(rows)
    print("=== P1/P2: ATR-sized stops vs baseline vs matched-width fixed controls ===")
    print(res.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))
    res.to_csv("data/wf_atr_stop_results.csv", index=False)

    print("\n=== P2 detail: does adaptivity beat a fixed stop of the SAME typical width? ===")
    cmp_rows = []
    for k in K_VALUES:
        a = agg(atr_rows[k], "")
        med, mrows = matched[k]
        m = agg(mrows, "")
        per_win_diff = [x["pnl"] - y["pnl"] for x, y in zip(atr_rows[k], mrows)]
        cmp_rows.append(dict(k=k, med_stop_pts=round(med, 1),
                             atr_pnl=a["total_pnl"], fixed_matched_pnl=m["total_pnl"],
                             diff=a["total_pnl"] - m["total_pnl"],
                             windows_atr_better=int(sum(d > 0 for d in per_win_diff)),
                             atr_trades=a["trades"], fixed_trades=m["trades"]))
    cmp_df = pd.DataFrame(cmp_rows)
    print(cmp_df.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))
    print(f"\n  k values where ATR-adaptive beats matched-width fixed: "
          f"{(cmp_df['diff'] > 0).sum()}/{len(cmp_df)}")
    print(f"  mean advantage of adaptivity: ${cmp_df['diff'].mean():,.0f} "
          f"(median ${cmp_df['diff'].median():,.0f})")
    cmp_df.to_csv("data/wf_atr_stop_matched.csv", index=False)

    print("\n=== P3 control: real ATR vs the SAME ATR series time-shifted (vol decoupled) ===")
    p3 = []
    for k in K_VALUES:
        real = agg(atr_rows[k], "")
        sh_pnls = [s["total_pnl"] for s in shifted[k]]
        p3.append(dict(k=k, real_atr_pnl=real["total_pnl"],
                       shifted_mean=float(np.mean(sh_pnls)),
                       shifted_min=float(np.min(sh_pnls)), shifted_max=float(np.max(sh_pnls)),
                       real_beats_n_of_5=int(sum(real["total_pnl"] > p for p in sh_pnls))))
    p3_df = pd.DataFrame(p3)
    print(p3_df.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))
    inside = ((p3_df.real_atr_pnl >= p3_df.shifted_min) & (p3_df.real_atr_pnl <= p3_df.shifted_max)).sum()
    print(f"\n  k values where real-ATR P&L falls INSIDE the range of its own shifted controls: "
          f"{inside}/{len(p3_df)} (inside = adaptivity carries no information)")
    p3_df.to_csv("data/wf_atr_stop_shift_control.csv", index=False)

    print("\n=== P4 control: neutral fixed-width sweep over the same 6 windows ===")
    w_df = pd.DataFrame(width_rows)
    print(w_df.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))
    print(f"\n  widths with positive total P&L: {(w_df.total_pnl > 0).sum()}/{len(w_df)}")
    print(f"  spread across widths: ${w_df.total_pnl.min():,.0f} .. ${w_df.total_pnl.max():,.0f}")
    rank8 = int((w_df.total_pnl > w_df.loc[w_df.config == "fixed 8pt", "total_pnl"].iloc[0]).sum()) + 1
    print(f"  the live config's 8pt stop ranks {rank8}/{len(w_df)} by total P&L")
    print("  (NB: stop was swept over {5,8,12} on this SAME 60-day sample and 8 won - see "
          "data/sweep_results.csv - so rank 1 here is a selection artifact, not evidence)")
    w_df.to_csv("data/wf_atr_stop_width_sweep.csv", index=False)

    # --- P5: is 8pt a plateau or a knife edge? and how much of it survives cost? ----------
    print("\n=== P5a: fine grid around the live 8pt stop (same 6 windows) ===")
    fine = [agg(run_over_windows(wins, stop_pts=s), f"fixed {s}pt")
            for s in [6.5, 7.0, 7.5, 8.0, 8.5, 9.0, 9.5]]
    f_df = pd.DataFrame(fine)[["config", "trades", "prof_windows", "total_pnl"]]
    print(f_df.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))
    print(f"  spread over a +/-1.5pt neighbourhood: ${f_df.total_pnl.min():,.0f} .. "
          f"${f_df.total_pnl.max():,.0f} (a smooth edge would not do this)")
    f_df.to_csv("data/wf_atr_stop_fine_grid.csv", index=False)

    print("\n=== P5b: cost sensitivity, live stop (8pt) vs a tighter one (5pt) ===")
    cost_rows = []
    for cost in [0.0, 0.15, 0.3, 0.6]:
        for s in [8.0, 5.0]:
            a = agg(run_over_windows(wins, stop_pts=s, cost_pts=cost), "")
            cost_rows.append(dict(cost_pts=cost, stop_pts=s, total_pnl=a["total_pnl"],
                                  prof_windows=a["prof_windows"], trades=a["trades"]))
    c_df = pd.DataFrame(cost_rows)
    print(c_df.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))
    c_df.to_csv("data/wf_atr_stop_cost_sensitivity.csv", index=False)


if __name__ == "__main__":
    main()
