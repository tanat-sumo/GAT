"""Test the *specific* pre-market -> noon session filter described by a real NQ/MNQ MA-cross trader.

Source of the hypothesis (r/algotrading, OP's own words in a post about taking their first loss):
"5 minute timeframe NY session, pre market and a bit after opening bell. NEVER 24/7!!!!
 ... I try to be done and flat by 12pm EST."

This is NOT the window already falsified on 2026-09-18 (09:30-16:00 ET, full NY RTH). It is earlier
and narrower, and it carries an *exit* rule ("flat by 12pm") that a pure entry filter does not
capture - so `flat_by` was added to `backtest.py` (opt-in, regression-tested as behavior-preserving
when unset) and both readings are tested:
  - entry-filter only  (enter only inside the window, hold to stop/tp/opposite-cross as usual)
  - entry-filter + flat (same entries, but force-close at 12:00 ET)

"Pre-market and a bit after the opening bell" is not a clock time, so a small set of plausible start
times is tested rather than one guess.

Rigor bar is the one this repo already established in `wf_session.py`, and it is mandatory here:
  1. 6 independent non-overlapping windows, FIXED configs, no per-window refitting.
  2. A ROTATION CONTROL - the same window LENGTH rotated through all 24 start hours. A session
     filter cannot create edge; it can only cut trade count (less variance, and in-sample luck about
     which hours get dodged). If the candidate window does not stand out from 24 arbitrary windows
     of identical width, there is nothing here.
  3. Trade-count confound check, parameter-neighbourhood check, per-window sign consistency.

Standing context that should colour every positive-looking number below: `scripts/nq_entry_edge.py`
found the MA cross entry has NO forward edge vs randomly timed entries on NQ at any horizon
15min-8h, and `scripts/entry_screen.py` found the same on gold across five signal families. A filter
on an entry with no aggregate edge can only subset noise.

Both instruments are tested because the real-world source of this filter trades NQ/MNQ, while the
live paper bot here trades gold.
"""
import argparse

import numpy as np
import pandas as pd

from backtest import load_data, run_backtest

N_WINDOWS = 6

INSTRUMENTS = {
    "gold": dict(path="data/gold_5m.csv",
                 base=dict(ma_period=20, stop_pts=8.0, rr=2.0, contract="MGC", cost_pts=0.3)),
    "nq": dict(path="data/nq_5m.csv",
               base=dict(ma_period=20, stop_pts=25.0, rr=2.0, contract="MNQ", cost_pts=1.0)),
}

# (label, start (h,m), end (h,m)) - all end at the OP's stated 12:00 ET cutoff
CANDIDATES = [
    ("04:00-12:00 ET (globex/London -> noon, 8.0h)", (4, 0), (12, 0)),
    ("06:00-12:00 ET (early pre-market -> noon, 6.0h)", (6, 0), (12, 0)),
    ("07:00-12:00 ET (pre-market -> noon, 5.0h)", (7, 0), (12, 0)),
    ("08:00-12:00 ET (late pre-market -> noon, 4.0h)", (8, 0), (12, 0)),
    ("09:30-12:00 ET (bell -> noon only, 2.5h)", (9, 30), (12, 0)),
]


def _m(t):
    return t[0] * 60 + t[1]


def _hm(mins):
    mins %= 1440
    return (mins // 60, mins % 60)


def _fmt(t):
    return f"{t[0]:02d}:{t[1]:02d}"


def metrics(eq_df, closed):
    if closed.empty:
        return dict(n=0, win_rate=float("nan"), pnl=0.0, sharpe=float("nan"))
    ret = eq_df["equity"].pct_change().dropna()
    sharpe = ret.mean() / ret.std() * np.sqrt(288 * 252) if ret.std() > 0 else float("nan")
    return dict(n=len(closed), win_rate=(closed.pnl > 0).mean(),
                pnl=closed.pnl.sum(), sharpe=sharpe)


def window_bounds(df, n_windows=N_WINDOWS, offset=0.0):
    """Non-overlapping window edges; offset (in windows) shifts every boundary for the P4 control."""
    step = len(df) / n_windows
    shift = int(step * offset)
    return [(int(min(len(df), shift + i * step)), int(min(len(df), shift + (i + 1) * step)))
            for i in range(n_windows) if shift + i * step < len(df)]


def run_config(df, base, start=None, end=None, flat=False, n_windows=N_WINDOWS, offset=0.0):
    """Score one session config over independent windows. Returns aggregate + per-window P&L."""
    cfg = dict(base)
    if start is not None:
        cfg["session_hours"] = (start, end)
        if flat:
            cfg["flat_by"] = end
    pnls, sharpes, ns, wins = [], [], [], []
    for a, b in window_bounds(df, n_windows, offset):
        eq_df, closed, _ = run_backtest(df.iloc[a:b], **cfg)
        m = metrics(eq_df, closed)
        pnls.append(m["pnl"])
        sharpes.append(m["sharpe"])
        ns.append(m["n"])
        wins.append(m["win_rate"])
    trades = int(sum(ns))
    return dict(trades=trades,
                prof_windows=int(sum(p > 0 for p in pnls)),
                traded_windows=int(sum(n > 0 for n in ns)),
                total_pnl=float(sum(pnls)),
                pnl_per_trade=float(sum(pnls) / trades) if trades else float("nan"),
                median_sharpe=float(np.nanmedian(sharpes)),
                win_rate=float(np.nansum(np.array(wins) * np.array(ns)) / trades) if trades else float("nan"),
                window_pnls=[float(p) for p in pnls])


def rotation_control(df, base, width_min, flat, minute_offset, n_windows=N_WINDOWS):
    """The load-bearing control: same window WIDTH, all 24 whole-hour start times.

    Keeps the candidate's minute offset (so a 09:30 candidate is compared against 00:30, 01:30, ...)
    and, in flat mode, moves the forced-flat cutoff with the window so every rotation is the same
    rule at a different time of day.
    """
    rows = []
    for h in range(24):
        s_min = h * 60 + minute_offset
        e_min = s_min + width_min
        s, e = _hm(s_min), _hm(e_min)
        r = run_config(df, base, start=s, end=e, flat=flat, n_windows=n_windows)
        rows.append(dict(start=_fmt(s), end=_fmt(e), start_min=s_min % 1440, **r))
    return pd.DataFrame(rows)


def rank_of(rot, start_min):
    """Rank (1 = best) of the candidate among the rotations, ties counted as better."""
    row = rot[rot.start_min == start_min % 1440].iloc[0]
    return (int((rot.total_pnl > row.total_pnl).sum()) + 1,
            int((rot.pnl_per_trade > row.pnl_per_trade).sum()) + 1,
            row)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instruments", nargs="*", default=list(INSTRUMENTS))
    ap.add_argument("--windows", type=int, default=N_WINDOWS)
    args = ap.parse_args()

    pd.set_option("display.width", 200)
    all_main, all_rot = [], []

    for inst in args.instruments:
        spec = INSTRUMENTS[inst]
        df = load_data(spec["path"])
        base = spec["base"]
        print("=" * 100)
        print(f"INSTRUMENT: {inst.upper()}  ({spec['path']})")
        print(f"  {len(df)} bars, {df.index[0]} -> {df.index[-1]}  tz={df.index.tz}")
        print(f"  config {base}")
        print("=" * 100)

        bl = run_config(df, base, n_windows=args.windows)
        print(f"\nREFERENCE baseline 24/7, no session filter: trades={bl['trades']} "
              f"prof_windows={bl['prof_windows']}/{args.windows} total=${bl['total_pnl']:,.0f} "
              f"$/trade={bl['pnl_per_trade']:.2f} win_rate={bl['win_rate']:.1%} "
              f"median_sharpe={bl['median_sharpe']:.2f}")
        print(f"  per-window: {['%.0f' % p for p in bl['window_pnls']]}")
        all_main.append(dict(instrument=inst, candidate="BASELINE 24/7", mode="none", **bl))

        # ---- P1: the candidate windows, both readings of "flat by 12pm" ----
        for flat in (False, True):
            mode = "entry-filter + flat@12:00" if flat else "entry-filter only"
            print(f"\n--- P1 candidates, {mode} ---")
            rows = []
            for label, s, e in CANDIDATES:
                r = run_config(df, base, start=s, end=e, flat=flat, n_windows=args.windows)
                rows.append(dict(candidate=label, **{k: v for k, v in r.items() if k != "window_pnls"}))
                all_main.append(dict(instrument=inst, candidate=label, mode=mode, **r))
            print(pd.DataFrame(rows).to_string(index=False,
                  float_format=lambda x: f"{x:,.2f}"))

        # ---- P2: rotation control, per distinct width and mode ----
        for flat in (False, True):
            mode = "entry-filter + flat@12:00" if flat else "entry-filter only"
            widths = {}
            for label, s, e in CANDIDATES:
                w = (_m(e) - _m(s)) % 1440
                widths.setdefault((w, _m(s) % 60), []).append((label, s, e))
            for (w, moff), members in sorted(widths.items()):
                rot = rotation_control(df, base, w, flat, moff, n_windows=args.windows)
                rot.insert(0, "instrument", inst)
                rot.insert(1, "mode", mode)
                rot.insert(2, "width_h", w / 60)
                all_rot.append(rot)
                print(f"\n--- P2 ROTATION CONTROL: {w/60:.1f}h window at :{moff:02d}, "
                      f"all 24 start hours, {mode} ---")
                show = rot.drop(columns=["window_pnls", "instrument", "mode", "width_h"])
                print(show.sort_values("total_pnl", ascending=False).to_string(
                    index=False, float_format=lambda x: f"{x:,.2f}"))
                pos = int((rot.total_pnl > 0).sum())
                print(f"  rotations with positive total P&L: {pos}/24   "
                      f"spread ${rot.total_pnl.min():,.0f} .. ${rot.total_pnl.max():,.0f} "
                      f"(range ${rot.total_pnl.max() - rot.total_pnl.min():,.0f})")
                print(f"  rotations with >={args.windows - 2}/{args.windows} profitable windows: "
                      f"{int((rot.prof_windows >= args.windows - 2).sum())}/24")
                print(f"  corr(total_pnl, trades) across rotations: "
                      f"{rot.total_pnl.corr(rot.trades):.2f}   "
                      f"(a strongly negative/positive value means trade count, not timing, drives P&L)")
                for label, s, e in members:
                    rp, rpt, row = rank_of(rot, _m(s))
                    print(f"  >> CANDIDATE {label}: rank {rp}/24 by total P&L, "
                          f"{rpt}/24 by $/trade  (${row.total_pnl:,.0f}, {row.trades} trades, "
                          f"${row.pnl_per_trade:.2f}/trade, {row.prof_windows}/{args.windows} windows)")

        # ---- P3: neighbourhood of each candidate (start and end shifted +/-1h) ----
        print(f"\n--- P3 NEIGHBOURHOOD: shift each candidate's start/end by +/-1h "
              f"(a real time-of-day effect should not be a knife edge) ---")
        nb_rows = []
        for flat in (False, True):
            mode = "flat@end" if flat else "entry-only"
            for label, s, e in CANDIDATES:
                base_r = run_config(df, base, start=s, end=e, flat=flat, n_windows=args.windows)
                for ds, de in [(0, 0), (-60, 0), (60, 0), (0, -60), (0, 60), (-60, -60), (60, 60)]:
                    s2, e2 = _hm(_m(s) + ds), _hm(_m(e) + de)
                    if (_m(e2) - _m(s2)) % 1440 < 30:
                        continue
                    r = run_config(df, base, start=s2, end=e2, flat=flat, n_windows=args.windows)
                    nb_rows.append(dict(instrument=inst, mode=mode, anchor=label.split(" (")[0],
                                        window=f"{_fmt(s2)}-{_fmt(e2)}",
                                        shift=f"start{ds//60:+d}h end{de//60:+d}h",
                                        trades=r["trades"], pnl=r["total_pnl"],
                                        prof_windows=r["prof_windows"]))
        nb = pd.DataFrame(nb_rows)
        for mode in nb["mode"].unique():
            for anchor in nb["anchor"].unique():
                sub = nb[(nb["mode"] == mode) & (nb["anchor"] == anchor)]
                pnls = sub.pnl.values
                print(f"  [{mode}] {anchor}: "
                      + "  ".join(f"{r.shift}=${r.pnl:,.0f}" for r in sub.itertuples())
                      + f"   | span ${pnls.max() - pnls.min():,.0f}, "
                        f"{int((pnls > 0).sum())}/{len(pnls)} positive")
        nb.to_csv(f"data/wf_reddit_session_neighbourhood_{inst}.csv", index=False)

    md = pd.DataFrame(all_main)
    md["window_pnls"] = md["window_pnls"].apply(lambda v: ";".join(f"{x:.0f}" for x in v))
    md.to_csv("data/wf_reddit_session_results.csv", index=False)
    rd = pd.concat(all_rot, ignore_index=True)
    rd["window_pnls"] = rd["window_pnls"].apply(lambda v: ";".join(f"{x:.0f}" for x in v))
    rd.to_csv("data/wf_reddit_session_rotations.csv", index=False)
    print("\nwrote data/wf_reddit_session_results.csv, data/wf_reddit_session_rotations.csv, "
          "data/wf_reddit_session_neighbourhood_*.csv")


if __name__ == "__main__":
    main()
