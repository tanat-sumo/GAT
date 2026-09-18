"""Is there anything for ANY exit rule to harvest? Forward-return edge of the MA-cross entry on NQ.

Why this exists. Everything tested on NQ so far varies the *exit* (fixed stop/TP, breakeven+MA trail,
now buffered trails). If the entry signal has no directional edge in raw forward returns, then no
exit rule can produce a positive expectancy from it, and the whole parameter search is guaranteed to
be a search over noise. That is a much stronger and cheaper thing to establish than any grid.

Two exit-rule-free measurements, each with a control:
  A) Mean signed forward move (entry-direction) at horizons 3..96 bars, vs a control of randomly
     chosen entry timestamps carrying the SAME sequence of long/short sides. The control absorbs any
     market drift over the sample, so only timing skill can show up as a difference.
  B) The MFE/MAE race: from each entry, does price reach +X points before -X points? A profitable
     stop-and-target system needs this to beat 50% (for symmetric X), and a trend/trail system needs
     the winners' favourable excursion to be materially bigger than the losers' adverse one. Same
     random-entry control.

Also reports per-window sign consistency, because a single full-sample number is exactly the kind of
thing this repo has been burned by.
"""
import sys

import numpy as np
import pandas as pd
from backtest import load_data

DATA = sys.argv[1] if len(sys.argv) > 1 else "data/nq_5m.csv"
HORIZONS = [3, 6, 12, 24, 48, 96]      # 5-min bars: 15min .. 8h
RACE_X = [10, 20, 40, 60]              # points, symmetric race thresholds
N_BOOT = 200
MA_PERIODS = [10, 20, 50]
N_WINDOWS = 6
RNG = np.random.default_rng(20260918)


def signals(df, ma_period):
    sma = df["close"].rolling(ma_period).mean()
    c, pc, ps = df["close"], df["close"].shift(), sma.shift()
    up = (pc <= ps) & (c > sma)
    dn = (pc >= ps) & (c < sma)
    side = pd.Series(0, index=df.index, dtype=int)
    side[up] = 1
    side[dn] = -1
    idx = np.flatnonzero(side.values != 0)
    return idx, side.values[idx]


def fwd_moves(close, idx, sides, h):
    """Signed forward move in points at horizon h, dropping entries too close to the end."""
    ok = idx + h < len(close)
    i, s = idx[ok], sides[ok]
    return (close[i + h] - close[i]) * s


def race(high, low, close, idx, sides, x, max_bars=96):
    """+x before -x? 1 win, 0 loss, nan undecided within max_bars."""
    out = np.full(len(idx), np.nan)
    for k, (i, s) in enumerate(zip(idx, sides)):
        e = close[i]
        hi = high[i + 1:i + 1 + max_bars]
        lo = low[i + 1:i + 1 + max_bars]
        if len(hi) == 0:
            continue
        if s == 1:
            up = np.flatnonzero(hi >= e + x)
            dn = np.flatnonzero(lo <= e - x)
        else:
            up = np.flatnonzero(lo <= e - x)
            dn = np.flatnonzero(hi >= e + x)
        fu = up[0] if len(up) else np.inf
        fd = dn[0] if len(dn) else np.inf
        if fu == np.inf and fd == np.inf:
            continue
        out[k] = 1.0 if fu < fd else 0.0  # ties (same bar) resolved against, conservative
    return out


def random_idx(n, lo, hi):
    return RNG.integers(lo, hi, size=n)


def winsor_t(v, p=0.01):
    """t-stat after clipping the most extreme p tails, i.e. with outlier bars defanged.

    A mean driven by a handful of huge moves is not a tradeable edge, it is a lottery ticket that
    happened to be in the sample. If t and t_wins disagree badly, believe t_wins.
    """
    if len(v) < 20:
        return np.nan
    lo, hi = np.percentile(v, [100 * p, 100 * (1 - p)])
    w = np.clip(v, lo, hi)
    s = w.std()
    return np.nan if s == 0 else w.mean() / (s / np.sqrt(len(w)))


def screen_signal(df, idx, sides, label, horizons=HORIZONS, race_x=RACE_X,
                  n_boot=N_BOOT, n_windows=N_WINDOWS, warmup=0, verbose=True):
    """The exit-rule-free entry screen. Signal-family agnostic: hand it entry bar indices and sides.

    idx    : integer positions of the entry bars (signal evaluated at that bar's close)
    sides  : +1 long / -1 short, same length as idx, encoding the family's own hypothesis
    warmup : first bar index the control is allowed to draw from (a family's lookback)

    Returns (fwd_df, race_df, window_df). This is the machinery validated in the 2026-09-18 NQ run;
    new signal families should reuse it rather than re-implementing the controls.
    """
    close, high, low = df["close"].values, df["high"].values, df["low"].values
    if verbose:
        print(f"\n================ {label}: {len(idx)} signals "
              f"({(sides == 1).mean() if len(idx) else float('nan'):.0%} long) ================")
    if len(idx) < 20:
        if verbose:
            print("   too few signals to screen (<20) - skipped")
        return None, None, None

    rows = []
    for h in horizons:
        real = fwd_moves(close, idx, sides, h)
        boots = []
        for _ in range(n_boot):
            ridx = random_idx(len(idx), warmup + 1, len(close) - max(horizons) - 1)
            boots.append(fwd_moves(close, ridx, sides, h).mean())
        boots = np.array(boots)
        pct = float((boots < real.mean()).mean())
        rows.append(dict(horizon_bars=h, n=len(real), mean_move_pts=real.mean(),
                         median_move_pts=np.median(real),
                         t_stat=real.mean() / (real.std() / np.sqrt(len(real))),
                         t_wins1pct=winsor_t(real),
                         ctrl_mean=boots.mean(), ctrl_p5=np.percentile(boots, 5),
                         ctrl_p95=np.percentile(boots, 95), pctile_vs_ctrl=pct))
    fwd = pd.DataFrame(rows)
    if verbose:
        print("\n-- A) signed forward move vs random-entry control (same side sequence) --")
        print(fwd.to_string(index=False, float_format=lambda x: f"{x:,.3f}"))

    rrows = []
    for x in race_x:
        r = race(high, low, close, idx, sides, x)
        ridx = random_idx(len(idx), warmup + 1, len(close) - 97)
        rc = race(high, low, close, ridx, sides, x)
        rrows.append(dict(x_pts=x, decided=int(np.isfinite(r).sum()),
                          win_rate=np.nanmean(r), ctrl_win_rate=np.nanmean(rc),
                          edge_pp=100 * (np.nanmean(r) - np.nanmean(rc))))
    races = pd.DataFrame(rrows)
    if verbose:
        print("\n-- B) MFE/MAE race: reaches +x before -x within 96 bars --")
        print(races.to_string(index=False, float_format=lambda x: f"{x:,.3f}"))

    # per-window sign consistency at the mid horizon
    h = 24
    bounds = np.linspace(0, len(df), n_windows + 1).astype(int)
    wr = []
    for i in range(n_windows):
        m = (idx >= bounds[i]) & (idx < bounds[i + 1])
        v = fwd_moves(close, idx[m], sides[m], h)
        wr.append(dict(window=i + 1, n=len(v), mean_move_pts=v.mean() if len(v) else np.nan))
    w = pd.DataFrame(wr)
    if verbose:
        print(f"\n-- per-window mean signed move at h={h} bars (2h) --")
        print(w.to_string(index=False, float_format=lambda x: f"{x:,.3f}"))
        print(f"   windows with positive mean move: {(w.mean_move_pts > 0).sum()}/{n_windows}")
    return fwd, races, w


def main():
    pd.set_option("display.width", 220)
    df = load_data(DATA)
    print(f"Data: {len(df)} bars {df.index[0]} -> {df.index[-1]}")
    for ma in MA_PERIODS:
        idx, sides = signals(df, ma)
        screen_signal(df, idx, sides, f"MA{ma} cross", warmup=ma)


if __name__ == "__main__":
    main()
