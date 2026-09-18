"""Can the NQ/MNQ breakeven+trail strategy be made to work by searching the parameter space?

BACKGROUND (don't re-derive, see RESEARCH_LOG 2026-09-16 entry). The first attempt at codifying the
user's real risk management - breakeven at 1R, then trail behind the MA - went 0/30 profitable. The
diagnosis was mechanical, not statistical: a stop parked exactly on a 5-20 period MA on 5-min bars
gets crossed by ordinary noise, so winners are converted into scratches before they can develop, and
there are no offsetting big winners because the same trail cuts those short on any pullback.

If that diagnosis is right, the fix is slack: the stop should sit some distance *behind* the MA, and
/or behind a slower MA, and the breakeven trigger shouldn't necessarily be 1R. This run widens the
search along exactly those axes.

HYPOTHESIS (single, falsifiable)
  H: the 2026-09-16 failure was a parameterization failure, not a strategy failure. Somewhere in
     {breakeven trigger} x {trail slack} x {trail MA speed} x {initial stop} x {entry MA} there is a
     configuration that is profitable across multiple independent windows, and its profitability is
     a property of the configuration rather than of which window/grid-cell happened to win.

Predictions and the control each one has to survive (this repo has twice been burned by skipping
these - see the session-filter rotation control and the 0.5pt stop-width knife edge):
  P1  Some configs are profitable over 6 independent non-overlapping windows. If ~none are, H dies
      immediately and no control is needed.
  P2  CONTROL, the load-bearing one - out-of-sample parameter *selection*. Split the windows into
      train/test at several points; pick the grid's best config on train and look at its test P&L.
      Compare against the whole grid's test distribution, and measure the rank correlation between
      train and test P&L across all configs. If picking the in-sample winner does no better than
      picking at random, then "the best config" is a window artifact - exactly the shape of the
      already-falsified 8pt stop.
  P3  CONTROL, neighbourhood. Perturb the winner one grid step in each axis. A real edge has a
      plateau; noise has a knife edge (the 8pt stop swung $3,560 on a 0.5pt change).
  P4  CONTROL, window placement. Re-score the top configs on a second window set offset by half a
      window, so the boundaries are different. Ranking should survive.
  P5  CONTROL, engine timing. The pre-2026-09-18 trail updated the stop from the current bar's close
      and then checked it against that same bar's range (an intrabar peek), and could also park a
      long's stop above the market. Both are fixed; everything here runs on the corrected engine
      (trail_timing="next_bar"). The top configs are re-scored under the legacy timing to show how
      much of any result is an engine artifact in either direction.
  P6  Cost sensitivity on the top configs (the gold run's whole edge died going 0.3 -> 0.6 pts).

MECHANISM CHECK (reported before the P&L, on purpose): does the buffer actually do what it is
supposed to do - stop trades from being scratched instantly? Exit-reason mix and holding time by
buffer size answer that independently of whether P&L improves.

ENGINE NOTE. The first run of this script surfaced two fill bugs in backtest.py's ma_trail, both now
fixed (details in backtest.py and RESEARCH_LOG): the trail could park a long's stop above the market
and "fill" it at a price that never traded, and the trail level was applied to the same bar's range
it was computed from. All numbers below come from the corrected engine. The pre-fix 2026-09-16
ma_trail numbers are void.

Data: yfinance NQ=F 5min, 60d. MNQ sizing ($2/pt), 1.0pt round-trip cost. Same standing caveat as
everything else in this repo: 60 days, ~10 days per window. Directional evidence only.
"""
import itertools
import numpy as np
import pandas as pd
from backtest import load_data, run_backtest

DATA = "data/nq_5m.csv"
CONTRACT, COST = "MNQ", 1.0
ATR_PERIOD = 14
N_WINDOWS = 6

# grid axes
BE_R = [0.5, 1.0, 1.5, 2.0]            # breakeven trigger, in R
BUF_ATR = [0.0, 0.5, 1.0, 2.0, 3.0]    # trail slack as a multiple of ATR(14); 0.0 = original hug
TRAIL_MA = [None, 50, 200]             # None = trail on the entry MA (original behavior)
STOP = [15.0, 25.0, 40.0, 60.0]        # initial stop, pts (NQ ATR14 median ~24pt)
MA = [20, 50]                          # entry MA


def metrics(eq, closed):
    if closed.empty:
        return dict(n=0, pnl=0.0, win_rate=np.nan, sharpe=np.nan)
    ret = eq["equity"].pct_change().dropna()
    sharpe = ret.mean() / ret.std() * np.sqrt(288 * 252) if ret.std() > 0 else np.nan
    return dict(n=len(closed), pnl=float(closed.pnl.sum()),
                win_rate=float((closed.pnl > 0).mean()), sharpe=float(sharpe))


def windows(df, n=N_WINDOWS, offset=0.0):
    """n non-overlapping windows. offset (0..1 of a window width) shifts every boundary."""
    w = len(df) / n
    start = int(offset * w)
    bounds = [int(start + i * w) for i in range(n + 1)]
    bounds[-1] = min(bounds[-1], len(df))
    return [df.iloc[bounds[i]:bounds[i + 1]] for i in range(n) if bounds[i + 1] > bounds[i]]


def run_cfg(wins, cfg, **extra):
    """One config over every window -> per-window metrics."""
    kw = dict(contract=CONTRACT, cost_pts=COST, trail_mode="ma_trail", atr_period=ATR_PERIOD,
              ma_period=cfg["ma"], stop_pts=cfg["stop"], breakeven_r=cfg["be_r"],
              trail_buffer_atr=(cfg["buf_atr"] or None), trail_ma_period=cfg["trail_ma"])
    kw.update(extra)
    return [metrics(*run_backtest(w, **kw)[:2]) for w in wins]


def agg(rows):
    pnls = [r["pnl"] for r in rows]
    n = sum(r["n"] for r in rows)
    return dict(trades=int(n), prof_windows=int(sum(p > 0 for p in pnls)),
                total_pnl=float(sum(pnls)), median_sharpe=float(np.nanmedian([r["sharpe"] for r in rows])),
                win_rate=float(np.nansum([r["win_rate"] * r["n"] for r in rows]) / max(n, 1)),
                pnls=pnls)


def label(c):
    return (f"ma{c['ma']} stop{c['stop']:g} be{c['be_r']:g}R buf{c['buf_atr']:g}xATR "
            f"trailma{c['trail_ma'] or 'entry'}")


def mechanism_check(df):
    """Does slack actually stop trades being scratched? Exit mix + hold time by buffer."""
    out = []
    for buf in BUF_ATR:
        eq, closed, _ = run_backtest(
            df, contract=CONTRACT, cost_pts=COST, trail_mode="ma_trail", atr_period=ATR_PERIOD,
            ma_period=20, stop_pts=25.0, breakeven_r=1.0,
            trail_buffer_atr=(buf or None))
        if closed.empty:
            continue
        closed = closed.copy()
        hold = (pd.to_datetime(closed.exit_ts) - pd.to_datetime(closed.entry_ts)).dt.total_seconds() / 300
        mult = 2  # MNQ $/pt; "scratch" = exited within 2 points of entry, i.e. a whipsawed-out trade
        scratch = (closed.pnl + COST * mult).abs() <= 2 * mult
        out.append(dict(buf_atr=buf, trades=len(closed),
                        pct_trail_exit=float((closed.reason == "trail_stop").mean()),
                        pct_scratch=float(scratch.mean()),
                        median_hold_bars=float(hold.median()),
                        p90_hold_bars=float(hold.quantile(.9)),
                        avg_win=float(closed[closed.pnl > 0].pnl.mean()) if (closed.pnl > 0).any() else np.nan,
                        avg_loss=float(closed[closed.pnl <= 0].pnl.mean()),
                        win_rate=float((closed.pnl > 0).mean()), pnl=float(closed.pnl.sum())))
    return pd.DataFrame(out)


def selection_test(res, n_win):
    """P2: does picking the in-sample winner beat picking at random, out of sample?"""
    P = np.array(res["pnls"].tolist())  # configs x windows
    rows = []
    for s in range(2, n_win):
        tr, te = P[:, :s].sum(1), P[:, s:].sum(1)
        best = int(np.argmax(tr))
        pct = float((te < te[best]).mean())
        rows.append(dict(train_windows=s, test_windows=n_win - s,
                         picked=res.config.iloc[best], picked_train_pnl=tr[best],
                         picked_test_pnl=te[best], grid_test_mean=float(te.mean()),
                         grid_test_median=float(np.median(te)), grid_test_max=float(te.max()),
                         picked_test_pctile=pct,
                         spearman_train_test=float(pd.Series(tr).corr(pd.Series(te), method="spearman"))))
    return pd.DataFrame(rows)


def main():
    pd.set_option("display.width", 250)
    df = load_data(DATA)
    wins = windows(df)
    print(f"Data: {len(df)} bars {df.index[0]} -> {df.index[-1]} (tz={df.index.tz})")
    print(f"Windows: {len(wins)} non-overlapping, "
          + ", ".join(f"{w.index[0].date()}..{w.index[-1].date()}" for w in wins))

    print("\n=== MECHANISM CHECK: what does trail slack actually do? (ma20/stop25/be1.0R, full sample) ===")
    mech = mechanism_check(df)
    print(mech.to_string(index=False, float_format=lambda x: f"{x:,.3f}"))
    mech.to_csv("data/wf_nq_trail_mechanism.csv", index=False)

    print("\n=== P1: full grid over 6 independent windows ===")
    grid = [dict(ma=m, stop=s, be_r=b, buf_atr=f, trail_ma=t)
            for m, s, b, f, t in itertools.product(MA, STOP, BE_R, BUF_ATR, TRAIL_MA)]
    print(f"{len(grid)} configs x {len(wins)} windows ...")
    rows = []
    for i, c in enumerate(grid, 1):
        a = agg(run_cfg(wins, c))
        rows.append(dict(config=label(c), **c, **a))
        if i % 40 == 0:
            print(f"  ...{i}/{len(grid)}")
    res = pd.DataFrame(rows)
    res.drop(columns=["pnls"]).to_csv("data/wf_nq_trail_grid.csv", index=False)

    cols = ["config", "trades", "prof_windows", "total_pnl", "median_sharpe", "win_rate"]
    print(f"\nProfitable configs (total P&L > 0): {(res.total_pnl > 0).sum()}/{len(res)}")
    print(f"Configs profitable in >=4/6 windows: {(res.prof_windows >= 4).sum()}/{len(res)}")
    print(f"Total P&L spread: ${res.total_pnl.min():,.0f} .. ${res.total_pnl.max():,.0f}  "
          f"(median ${res.total_pnl.median():,.0f})")
    print("\nTop 12 by total P&L:")
    print(res.nlargest(12, "total_pnl")[cols].to_string(index=False, float_format=lambda x: f"{x:,.2f}"))
    print("\nBottom 5:")
    print(res.nsmallest(5, "total_pnl")[cols].to_string(index=False, float_format=lambda x: f"{x:,.2f}"))

    print("\n--- marginal effect of each axis (mean total P&L, all other axes averaged over) ---")
    for ax in ["be_r", "buf_atr", "trail_ma", "stop", "ma"]:
        g = res.groupby(res[ax].astype(str), dropna=False).total_pnl.agg(["mean", "median", "max",
                                                                          lambda s: (s > 0).sum()])
        g.columns = ["mean_pnl", "median_pnl", "max_pnl", "n_profitable"]
        print(f"\n{ax}:\n{g.to_string(float_format=lambda x: f'{x:,.0f}')}")

    print("\n=== P2 CONTROL: out-of-sample parameter selection ===")
    sel = selection_test(res, len(wins))
    print(sel.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))
    sel.to_csv("data/wf_nq_trail_selection.csv", index=False)
    print("  picked_test_pctile = fraction of the grid the in-sample winner beats out of sample.")
    print("  ~0.5 means in-sample selection is worth nothing; spearman ~0 means the ranking doesn't transfer.")

    top = res.nlargest(8, "total_pnl")
    if res.total_pnl.max() <= 0:
        print("\nNo config is profitable over the 6 windows -> P1 fails outright; "
              "P3-P6 controls are run anyway on the least-bad configs for completeness.")

    print("\n=== P3 CONTROL: neighbourhood of the grid winner ===")
    best_cfg = {k: res.loc[res.total_pnl.idxmax(), k] for k in ["ma", "stop", "be_r", "buf_atr", "trail_ma"]}
    best_cfg["trail_ma"] = None if pd.isna(best_cfg["trail_ma"]) else int(best_cfg["trail_ma"])
    nb = []
    axes = dict(be_r=BE_R, buf_atr=BUF_ATR, trail_ma=TRAIL_MA, stop=STOP, ma=MA)
    for ax, vals in axes.items():
        for v in vals:
            c = dict(best_cfg)
            c[ax] = v
            a = agg(run_cfg(wins, c))
            nb.append(dict(axis=ax, value=str(v), config=label(c), total_pnl=a["total_pnl"],
                           prof_windows=a["prof_windows"], trades=a["trades"]))
    nb_df = pd.DataFrame(nb).drop_duplicates(subset="config")
    print(f"winner = {label(best_cfg)}")
    print(nb_df.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))
    print(f"  neighbourhood spread: ${nb_df.total_pnl.min():,.0f} .. ${nb_df.total_pnl.max():,.0f} "
          f"vs winner's ${res.total_pnl.max():,.0f}")
    nb_df.to_csv("data/wf_nq_trail_neighbourhood.csv", index=False)

    print("\n=== P4/P5/P6 CONTROLS on the top 8 configs: offset windows, honest trail timing, cost ===")
    wins_off = windows(df, offset=0.5)
    ctrl = []
    for _, r in top.iterrows():
        c = dict(ma=int(r.ma), stop=float(r.stop), be_r=float(r.be_r), buf_atr=float(r.buf_atr),
                 trail_ma=(None if pd.isna(r.trail_ma) else int(r.trail_ma)))
        off = agg(run_cfg(wins_off, c))
        nxt = agg(run_cfg(wins, c, trail_timing="close"))
        c2 = agg(run_cfg(wins, c, cost_pts=2.0))
        c0 = agg(run_cfg(wins, c, cost_pts=0.5))
        ctrl.append(dict(config=r.config, base_pnl=r.total_pnl, base_windows=r.prof_windows,
                         offset_windows_pnl=off["total_pnl"], offset_prof_windows=off["prof_windows"],
                         legacy_timing_pnl=nxt["total_pnl"], legacy_timing_prof_windows=nxt["prof_windows"],
                         cost0_5_pnl=c0["total_pnl"], cost2_0_pnl=c2["total_pnl"]))
    ctrl_df = pd.DataFrame(ctrl)
    print(ctrl_df.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))
    ctrl_df.to_csv("data/wf_nq_trail_controls.csv", index=False)

    print("\n=== reference points on the same windows ===")
    refs = []
    for name, kw in [
        ("fixed stop/TP rr2 ma20 stop25", dict(trail_mode="fixed", ma_period=20, stop_pts=25.0, rr=2.0)),
        ("fixed stop/TP rr2 ma50 stop40", dict(trail_mode="fixed", ma_period=50, stop_pts=40.0, rr=2.0)),
        ("original ma_trail ma20 stop25 be1R buf0", dict(trail_mode="ma_trail", ma_period=20,
                                                        stop_pts=25.0, breakeven_r=1.0)),
    ]:
        rws = [metrics(*run_backtest(w, contract=CONTRACT, cost_pts=COST,
                                     atr_period=ATR_PERIOD, **kw)[:2]) for w in wins]
        a = agg(rws)
        refs.append(dict(ref=name, trades=a["trades"], prof_windows=a["prof_windows"],
                         total_pnl=a["total_pnl"], win_rate=a["win_rate"]))
    print(pd.DataFrame(refs).to_string(index=False, float_format=lambda x: f"{x:,.2f}"))


if __name__ == "__main__":
    main()
