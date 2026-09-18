"""Screen several ENTRY-signal families for forward edge, with no exit rule at all.

Why this exists. Every experiment in this repo before 2026-09-18 varied the *exit* on top of one
fixed entry ("SMA(20) cross"), and `nq_entry_edge.py` then showed that entry has no measurable edge
over randomly timed entries on NQ - which is why every exit search failed. This script reuses that
exact screen (`nq_entry_edge.screen_signal`: signed forward move vs a random-entry control with the
same side sequence, MFE/MAE race vs the same control, per-window sign consistency) but makes the
*signal generator* pluggable, so genuinely different entry families can be screened before anyone
spends time building exit logic around them.

Deliberately spans two opposite hypothesis shapes:
  - continuation  (donchian breakout, ROC momentum, opening-range breakout, volume-spike thrust)
  - mean reversion (z-score of deviation from a rolling mean, deviation from session VWAP)
Everything tried in this repo so far has been continuation-shaped, so the reversion families are the
genuinely new information.

Note the screen is TWO-SIDED. `sides` encodes each family's own hypothesis, so a strongly NEGATIVE
result for a continuation family is not merely "no edge" - it is a positive result for the opposite
(reversion) trade on the same trigger, and is flagged as such. Only results sitting inside the
random-entry control band are actually uninformative.

Usage:
    python scripts/entry_screen.py data/gold_5m.csv --label gold
    python scripts/entry_screen.py data/nq_5m.csv   --label nq
"""
import argparse

import numpy as np
import pandas as pd
from backtest import load_data
from nq_entry_edge import (HORIZONS, N_WINDOWS, N_BOOT, fwd_moves, random_idx, screen_signal,
                           signals as ma_cross_signals, winsor_t)

SESSION_OPEN = (9, 30)   # ET; both GC=F and NQ=F bars come back from yfinance in US/Eastern


# ---------------------------------------------------------------- helpers

def first_of_run(cond):
    """Bar where a boolean condition turns True - so a 20-bar-long breakout is one signal, not 20."""
    c = np.asarray(cond, dtype=bool)
    prev = np.concatenate(([False], c[:-1]))
    return c & ~prev


def pack(up, dn, warmup):
    """Combine two boolean arrays into (idx, sides). If both fire on a bar, drop it (ambiguous)."""
    up, dn = np.asarray(up, bool), np.asarray(dn, bool)
    both = up & dn
    up, dn = up & ~both, dn & ~both
    side = np.zeros(len(up), dtype=int)
    side[up] = 1
    side[dn] = -1
    side[:warmup] = 0
    idx = np.flatnonzero(side != 0)
    return idx, side[idx]


def dedupe(idx, sides, min_gap):
    """Keep only signals at least `min_gap` bars apart.

    Signals cluster (one thrust can fire several bars), so forward windows overlap and the
    observations feeding the t-stat are not independent - which inflates |t| AND narrows the
    random-entry control band (the control draws independently). Re-running with min_gap >= the
    horizon makes the forward windows non-overlapping, which is the honest test.
    """
    keep, last = [], -10 ** 9
    for k, i in enumerate(idx):
        if i - last >= min_gap:
            keep.append(k)
            last = i
    keep = np.array(keep, dtype=int)
    return idx[keep], sides[keep]


def atr(df, n=14):
    h, l, c = df["high"], df["low"], df["close"].shift()
    tr = pd.concat([h - l, (h - c).abs(), (l - c).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


# ---------------------------------------------------------------- signal families
# Each returns (idx, sides, warmup). `sides` carries the family's OWN hypothesis:
# +1 = "expect price up from here", -1 = "expect price down from here".

def sig_donchian(df, n=20):
    """CONTINUATION. Close makes a new n-bar extreme (channel breakout) -> expect follow-through.
    Different mechanism from an MA cross: reacts to the extreme of the range, not to an average."""
    hi = df["high"].rolling(n).max().shift(1).values
    lo = df["low"].rolling(n).min().shift(1).values
    c = df["close"].values
    return (*pack(first_of_run(c > hi), first_of_run(c < lo), n + 1), n + 1)


def sig_roc(df, n=12, k=1.5, sd_win=500):
    """CONTINUATION. n-bar return exceeds k rolling std devs of that same return -> expect the
    thrust to continue. Threshold is in sigma units so it is comparable across instruments."""
    r = df["close"].pct_change(n)
    sd = r.rolling(sd_win).std()
    up, dn = (r > k * sd).values, (r < -k * sd).values
    w = n + sd_win + 1
    return (*pack(first_of_run(up), first_of_run(dn), w), w)


def sig_revert_z(df, n=48, k=2.0):
    """MEAN REVERSION (opposite hypothesis shape from everything else in this repo). Price k std
    devs above its own n-bar mean -> SHORT (expect reversion), k below -> LONG."""
    m = df["close"].rolling(n).mean()
    s = df["close"].rolling(n).std()
    z = ((df["close"] - m) / s).values
    stretched_up = first_of_run(z > k)     # too high -> expect down
    stretched_dn = first_of_run(z < -k)
    return (*pack(stretched_dn, stretched_up, n + 1), n + 1)


def sig_vwap_dev(df, k=2.0, min_bars=12):
    """MEAN REVERSION against a reference traders actually watch. Session (calendar-day, ET) VWAP,
    z = (close - vwap) / running std of that deviation. z > k -> SHORT, z < -k -> LONG."""
    d = df.copy()
    day = d.index.date
    pv = (d["close"] * d["volume"]).groupby(day).cumsum()
    vv = d["volume"].groupby(day).cumsum()
    bars = pd.Series(1, index=d.index).groupby(day).cumsum()
    # bars with zero volume (yfinance reports plenty) would freeze VWAP; fall back to a running
    # mean of close on any day whose cumulative volume is still zero.
    cmean = d["close"].groupby(day).expanding().mean().reset_index(level=0, drop=True)
    vwap = np.where(vv.values > 0, pv.values / np.where(vv.values == 0, 1, vv.values), cmean.values)
    dev = d["close"].values - vwap
    sd = pd.Series(dev, index=d.index).groupby(day).expanding().std().reset_index(level=0, drop=True).values
    with np.errstate(invalid="ignore", divide="ignore"):
        z = np.where((sd > 0) & (bars.values >= min_bars), dev / np.where(sd == 0, np.nan, sd), np.nan)
    z = np.nan_to_num(z, nan=0.0)
    return (*pack(first_of_run(z < -k), first_of_run(z > k), 2), 2)


def sig_vol_spike(df, k=3.0, win=96, body_atr=0.5):
    """CONTINUATION, participation-confirmed. Volume >= k x its rolling median AND the bar has a
    real directional body (>= body_atr x ATR14) -> trade in the bar's direction."""
    v = df["volume"].values
    med = df["volume"].rolling(win).median().shift(1).values
    body = (df["close"] - df["open"]).values
    a = atr(df).values
    spike = (med > 0) & (v >= k * med) & (np.abs(body) >= body_atr * a)
    return (*pack(spike & (body > 0), spike & (body < 0), win + 15), win + 15)


def sig_orb(df, or_minutes=30, bar_minutes=5):
    """CONTINUATION. Opening-range breakout: the first `or_minutes` after the 09:30 ET open define a
    range; the first close beyond it (per side, per day) is the signal. Time-anchored, so it is a
    genuinely different mechanism from the rolling-window families - and the only family here whose
    signal count is bounded by the number of trading days."""
    n_or = max(1, or_minutes // bar_minutes)
    idx_list, side_list = [], []
    pos = {ts: i for i, ts in enumerate(df.index)}
    for _, day in df.groupby(df.index.date):
        mins = day.index.hour * 60 + day.index.minute
        opening = day[mins >= SESSION_OPEN[0] * 60 + SESSION_OPEN[1]]
        if len(opening) < n_or + 4:
            continue
        rng = opening.iloc[:n_or]
        hi, lo = rng["high"].max(), rng["low"].min()
        rest = opening.iloc[n_or:]
        rest = rest[(rest.index.hour * 60 + rest.index.minute) <= 16 * 60]
        for s, hit in ((1, rest[rest["close"] > hi]), (-1, rest[rest["close"] < lo])):
            if len(hit):
                idx_list.append(pos[hit.index[0]])
                side_list.append(s)
    order = np.argsort(idx_list)
    return (np.array(idx_list, int)[order], np.array(side_list, int)[order], 2)


def sig_ma_cross(df, ma_period=20):
    """CONTINUATION. The repo's incumbent entry, re-run here purely as a calibration reference."""
    idx, sides = ma_cross_signals(df, ma_period)
    return idx, sides, ma_period + 1


FAMILIES = [
    # (label, hypothesis shape, fn, kwargs)
    ("MA20 cross (reference, already screened)", "continuation", sig_ma_cross, dict(ma_period=20)),
    ("Donchian 20-bar breakout", "continuation", sig_donchian, dict(n=20)),
    ("Donchian 60-bar breakout", "continuation", sig_donchian, dict(n=60)),
    ("ROC 12-bar > 1.5 sigma", "continuation", sig_roc, dict(n=12, k=1.5)),
    ("ROC 24-bar > 2.0 sigma", "continuation", sig_roc, dict(n=24, k=2.0)),
    ("ROC 48-bar > 1.5 sigma", "continuation", sig_roc, dict(n=48, k=1.5)),
    ("Mean-revert z(48) 2.0 sigma", "reversion", sig_revert_z, dict(n=48, k=2.0)),
    ("Mean-revert z(96) 2.5 sigma", "reversion", sig_revert_z, dict(n=96, k=2.5)),
    ("Session VWAP deviation 2.0 sigma", "reversion", sig_vwap_dev, dict(k=2.0)),
    ("Volume spike 3x + directional body", "continuation", sig_vol_spike, dict(k=3.0)),
    ("Opening-range breakout 30min", "continuation", sig_orb, dict(or_minutes=30)),
    ("Opening-range breakout 60min", "continuation", sig_orb, dict(or_minutes=60)),
]


# ---------------------------------------------------------------- driver

def verdict(fwd, win, atr_pts):
    """Mechanical first-pass flag. Deliberately strict; a human reads the tables anyway.

    PROMISING needs all of: >=3 of 6 horizons with the real mean outside the random-entry control's
    5-95 band in the SAME direction, that direction consistent in >=5 of 6 windows, a |t| >= 2 at
    >=2 horizons that survives 1% winsorizing, and an effect worth more than ~0.25 ATR (i.e. big
    enough to pay costs). Anything outside the band in the opposite direction to the family's
    hypothesis is reported as REVERSED, since that is a live lead for the mirrored trade.
    """
    out = fwd.mean_move_pts > fwd.ctrl_p95
    under = fwd.mean_move_pts < fwd.ctrl_p5
    n_out, n_under = int(out.sum()), int(under.sum())
    strong = int(((fwd.t_stat.abs() >= 2) & (fwd.t_wins1pct.abs() >= 2)
                  & (np.sign(fwd.t_stat) == np.sign(fwd.t_wins1pct))).sum())
    pos_w = int((win.mean_move_pts > 0).sum())
    big = float(fwd.mean_move_pts.abs().max()) >= 0.25 * atr_pts
    if n_out >= 3 and strong >= 2 and pos_w >= 5 and big:
        return "PROMISING", n_out, n_under, strong, pos_w
    if n_under >= 3 and strong >= 2 and pos_w <= 1 and big:
        return "REVERSED (mirror it)", n_out, n_under, strong, pos_w
    return "NO EDGE", n_out, n_under, strong, pos_w


SCAN_GRID = (
    [(f"ROC n={n} k={k}", sig_roc, dict(n=n, k=k)) for n in (12, 24, 48) for k in (1.5, 2.0, 2.5)]
    + [(f"revert z n={n} k={k}", sig_revert_z, dict(n=n, k=k)) for n in (48, 96, 192) for k in (2.0, 2.5, 3.0)]
    + [(f"vwap dev k={k}", sig_vwap_dev, dict(k=k)) for k in (1.5, 2.0, 2.5, 3.0)]
)


def scan(df, label, h=24, n_boot=N_BOOT):
    """Neighbourhood + concentration control for anything the main screen flags.

    Two failure modes this repo keeps hitting: (1) a parameter spike whose neighbours all die, and
    (2) an effect that is really one or two good windows. Both are checked here, at one horizon,
    for a grid around the interesting families. `top2_window_share` is the fraction of the total
    signed move contributed by the two best windows - 1/3 is what an evenly spread effect gives.
    """
    close = df["close"].values
    bounds = np.linspace(0, len(df), N_WINDOWS + 1).astype(int)
    rows = []
    for name, fn, kw in SCAN_GRID:
        idx, sides, warmup = fn(df, **kw)
        if len(idx) < 40:
            rows.append(dict(family=name, n=len(idx), note="too few"))
            continue
        real = fwd_moves(close, idx, sides, h)
        boots = np.array([fwd_moves(close, random_idx(len(idx), warmup + 1, len(close) - max(HORIZONS) - 1),
                                    sides, h).mean() for _ in range(n_boot)])
        wsum, wpos = [], 0
        for i in range(N_WINDOWS):
            m = (idx >= bounds[i]) & (idx < bounds[i + 1])
            v = fwd_moves(close, idx[m], sides[m], h)
            wsum.append(v.sum() if len(v) else 0.0)
            wpos += int(len(v) > 0 and v.mean() > 0)
        wsum = np.array(wsum)
        tot = real.sum()
        share = float(np.sort(np.abs(wsum))[-2:].sum() / abs(tot)) if tot != 0 else np.nan
        rows.append(dict(family=name, n=len(idx), mean=real.mean(), median=np.median(real),
                         t=real.mean() / (real.std() / np.sqrt(len(real))), t_wins=winsor_t(real),
                         ctrl_p5=np.percentile(boots, 5), ctrl_p95=np.percentile(boots, 95),
                         pctile=float((boots < real.mean()).mean()), pos_windows=wpos,
                         top2_window_share=share))
    out = pd.DataFrame(rows)
    print(f"\n=== NEIGHBOURHOOD SCAN [{label}] at h={h} bars ({h * 5}min) ===")
    print(out.to_string(index=False, float_format=lambda x: f"{x:,.3f}"))
    out.to_csv(f"data/entry_scan_{label}.csv", index=False)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data", nargs="?", default="data/gold_5m.csv")
    ap.add_argument("--label", default=None)
    ap.add_argument("--scan", action="store_true",
                    help="run only the parameter-neighbourhood / window-concentration control")
    args = ap.parse_args()
    label = args.label or args.data.split("/")[-1].split("_")[0]

    pd.set_option("display.width", 220)
    df = load_data(args.data)
    med_atr = float(atr(df).median())
    # race thresholds in ATR units so gold (~4pt ATR) and NQ (~24pt ATR) are compared like for like
    race_x = [round(m * med_atr, 1) for m in (0.5, 1, 2, 4)]
    print(f"=== ENTRY SCREEN [{label}] ===")
    print(f"Data: {len(df)} bars {df.index[0]} -> {df.index[-1]}")
    print(f"Median ATR(14) = {med_atr:.2f} pts; race thresholds (0.5/1/2/4 ATR) = {race_x}")

    if args.scan:
        for h in (12, 24, 48):
            scan(df, f"{label}_h{h}", h=h)
        return

    summary = []
    for name, shape, fn, kw in FAMILIES:
        idx, sides, warmup = fn(df, **kw)
        f, r, w = screen_signal(df, idx, sides, f"{name} [{shape}]", race_x=race_x, warmup=warmup)
        if f is None:
            summary.append(dict(instrument=label, family=name, shape=shape, n=len(idx),
                                verdict="TOO FEW SIGNALS"))
            continue
        v, n_out, n_under, strong, pos_w = verdict(f, w, med_atr)
        print(f"   >> {v}  (horizons above ctrl p95: {n_out}/6, below p5: {n_under}/6, "
              f"|t|>=2 robust: {strong}/6, positive windows: {pos_w}/6)")
        summary.append(dict(
            instrument=label, family=name, shape=shape, n=len(idx),
            mean_h3=f.mean_move_pts[0], mean_h24=f.mean_move_pts[3], mean_h96=f.mean_move_pts[5],
            best_abs_t=f.t_stat.abs().max(), best_abs_t_wins=f.t_wins1pct.abs().max(),
            horizons_above_p95=n_out, horizons_below_p5=n_under, robust_t2=strong,
            positive_windows=pos_w, race_edge_pp_1atr=r.edge_pp[1],
            mean_h24_in_atr=f.mean_move_pts[3] / med_atr, verdict=v))

    s = pd.DataFrame(summary)
    out = f"data/entry_screen_{label}.csv"
    s.to_csv(out, index=False)
    print(f"\n\n=============== SUMMARY [{label}] (written to {out}) ===============")
    print(s.to_string(index=False, float_format=lambda x: f"{x:,.3f}"))
    n_tests = len([x for x in summary if x.get("verdict") != "TOO FEW SIGNALS"]) * len(HORIZONS)
    print(f"\nMultiple-comparison context: {n_tests} mean-move tests on this instrument. "
          f"At |t|>=2, ~{0.0455 * n_tests:.1f} false positives are expected by chance alone.")
    print(f"Windows: {N_WINDOWS} non-overlapping, ~10 calendar days each (60-day yfinance sample).")


if __name__ == "__main__":
    main()
