"""Trade-count-matched control for the pre-market->noon session filter.

The rotation control in `wf_reddit_session.py` asks "is this window special among windows of the
same width?". This asks the narrower, more direct question the standing finding demands:

  **does selecting these particular hours beat selecting an equal number of the SAME strategy's
  trades at random?**

A session filter's only mechanical effect on a zero-edge entry is to shrink the trade count, which
shrinks variance and, in one sample, lets luck about *which* trades got dropped read as "edge". So:
take the unfiltered 24/7 baseline trade set inside each of the 6 independent windows, draw a random
subsample the same size as the candidate's trade count in that window, sum, repeat. If the candidate
sits inside that distribution it is a coin-flip subset, not a time-of-day effect.

Caveat stated up front: session-filtered trades are not a strict subset of the baseline trades
(skipping an entry changes which later crosses the strategy is flat for), so this is an
approximation - a very good one for the trade-count question, not an exact permutation test. The
rotation control remains the load-bearing evidence.
"""
import argparse

import numpy as np
import pandas as pd

from backtest import load_data, run_backtest
from wf_reddit_session import (CANDIDATES, INSTRUMENTS, N_WINDOWS, _fmt, run_config, window_bounds)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instruments", nargs="*", default=list(INSTRUMENTS))
    ap.add_argument("--draws", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    rng = np.random.default_rng(args.seed)
    out = []

    for inst in args.instruments:
        spec = INSTRUMENTS[inst]
        df = load_data(spec["path"])
        base = spec["base"]
        print("=" * 96)
        print(f"TRADE-COUNT-MATCHED CONTROL - {inst.upper()}  ({args.draws} draws)")
        print("=" * 96)

        # baseline 24/7 trade P&Ls, per window
        per_window_pnls = []
        for a, b in window_bounds(df, N_WINDOWS):
            _, closed, _ = run_backtest(df.iloc[a:b], **base)
            per_window_pnls.append(closed.pnl.values if not closed.empty else np.array([]))
        print(f"baseline 24/7 trades per window: {[len(p) for p in per_window_pnls]} "
              f"(total {sum(len(p) for p in per_window_pnls)}), "
              f"total P&L ${sum(p.sum() for p in per_window_pnls):,.0f}")

        for flat in (False, True):
            mode = "entry-filter + flat@12:00" if flat else "entry-filter only"
            for label, s, e in CANDIDATES:
                # per-window trade counts for the candidate
                counts, cand_pnls = [], []
                cfg = dict(base, session_hours=(s, e))
                if flat:
                    cfg["flat_by"] = e
                for a, b in window_bounds(df, N_WINDOWS):
                    _, closed, _ = run_backtest(df.iloc[a:b], **cfg)
                    counts.append(len(closed))
                    cand_pnls.append(closed.pnl.sum() if not closed.empty else 0.0)
                cand_total = float(sum(cand_pnls))

                draws = np.empty(args.draws)
                for d in range(args.draws):
                    tot = 0.0
                    for pool, k in zip(per_window_pnls, counts):
                        if k and len(pool):
                            k_eff = min(k, len(pool))
                            tot += rng.choice(pool, size=k_eff, replace=False).sum()
                    draws[d] = tot
                pct = float((draws < cand_total).mean())
                out.append(dict(instrument=inst, mode=mode, candidate=label,
                                trades=int(sum(counts)), cand_pnl=cand_total,
                                ctrl_mean=float(draws.mean()), ctrl_p5=float(np.percentile(draws, 5)),
                                ctrl_p95=float(np.percentile(draws, 95)), percentile=pct))
                print(f"[{mode:26s}] {label.split(' (')[0]:12s} "
                      f"n={sum(counts):4d}  candidate ${cand_total:>8,.0f}  "
                      f"random-subset mean ${draws.mean():>8,.0f} "
                      f"[p5 ${np.percentile(draws,5):>8,.0f}, p95 ${np.percentile(draws,95):>8,.0f}]  "
                      f"percentile {pct:.3f}"
                      f"{'   <-- outside band' if pct < 0.05 or pct > 0.95 else ''}")

    res = pd.DataFrame(out)
    res.to_csv("data/wf_reddit_session_bootstrap.csv", index=False)
    print("\nwrote data/wf_reddit_session_bootstrap.csv")
    print("Reading: percentile is the fraction of equal-sized RANDOM trade subsets the candidate "
          "beats. ~0.5 = the window is an ordinary subset of the same noise. >0.95 would be the "
          "minimum bar for 'these hours are special', and even that is one of many tests run here.")


if __name__ == "__main__":
    main()
