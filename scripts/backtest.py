"""MA-cross backtest, 5min gold futures. Long+short, MGC-sized (10oz, $10/point).
Entry: close crosses and closes past SMA(period). Exit: opposite cross, stop loss, or take profit.
"""
import argparse
import pandas as pd
import numpy as np

CONTRACT_MULT = {"MGC": 10, "GC": 100, "NQ": 20, "MNQ": 2}  # $ per point per contract


def _mins_of_day(x):
    """Accept an hour (int/float) or an (hour, minute) tuple; return minutes since midnight."""
    return x * 60 if isinstance(x, (int, float)) else x[0] * 60 + x[1]


def _crossed_time(prev_min, now_min, target_min):
    """True if the clock time `target_min` falls in (prev_min, now_min], wrapping at midnight.

    Edge-triggered on purpose: the forced session exit must fire once, on the first bar at or after
    the cutoff, not on every bar for the rest of the day (which would silently double as an entry
    filter and would break for session windows that wrap midnight).
    """
    if prev_min is None:
        return False
    if prev_min <= now_min:
        return prev_min < target_min <= now_min
    return target_min > prev_min or target_min <= now_min


def load_data(path="data/gold_5m.csv"):
    # NOTE: previously passed skiprows=[1, 2] (left over from raw 3-row yfinance MultiIndex
    # headers). Both saved CSVs have a single header row, so that silently discarded the first
    # two real bars of every backtest. Harmless in magnitude (2 of ~13,700) but wrong; removed.
    df = pd.read_csv(path, index_col=0, parse_dates=True, header=0)
    df.columns = ["close", "high", "low", "open", "volume"]
    return df[["open", "high", "low", "close", "volume"]].dropna()


def run_backtest(df, ma_period=20, stop_pts=8.0, tp_pts=None, rr=2.0,
                  contract="MGC", contracts=1, cost_pts=0.3, start_cap=50000,
                  regime_ma=None, session_hours=None, atr_period=None, atr_min_pts=None,
                  confirm_bars=1, trail_mode="fixed", breakeven_r=1.0,
                  stop_mode="fixed", atr_stop_mult=None, atr_series=None,
                  trail_buffer_pts=0.0, trail_buffer_atr=None, trail_ma_period=None,
                  trail_timing="next_bar", flat_by=None):
    """
    regime_ma: if set (e.g. 100), only take longs when close > SMA(regime_ma), shorts when close < it
    session_hours: if set, tuple (start_hour, end_hour) in the df's tz - only trade entries inside this window
    atr_period/atr_min_pts: if set, skip entries when ATR(atr_period) < atr_min_pts (too quiet/choppy)
      (atr_period alone just computes ATR; the filter only applies when atr_min_pts is also set)
    stop_mode: "fixed" (stop_pts points) or "atr" (stop = atr_stop_mult * ATR(atr_period) measured at
      the entry bar, target = rr * that distance). ATR mode sizes risk to current volatility instead
      of a constant point distance; requires atr_period and atr_stop_mult.
    confirm_bars: require this many consecutive closes past sma before entry (1 = original behavior)
    trail_mode: "fixed" (original: fixed stop + fixed tp) or "ma_trail" (move stop to breakeven at
      breakeven_r * stop_pts favorable move, then trail stop behind the MA itself, no fixed tp - exit
      only when price genuinely trails back through the MA)
    trail_buffer_pts / trail_buffer_atr: slack between the trailing stop and the MA line, so the stop
      does not sit exactly on the indicator (the 2026-09-16 ma_trail failure was attributed to price
      whipsawing through a stop parked on a fast MA). Buffer = trail_buffer_pts +
      trail_buffer_atr * ATR(atr_period) at the current bar; long stop = MA - buffer, short stop =
      MA + buffer. Defaults (0.0 / None) reproduce the original hug-the-MA behavior exactly.
    trail_ma_period: MA used for the *trail* only, leaving the entry MA (ma_period) untouched. This
      separates the "slower trail" axis from the "different entries" axis, which would otherwise be
      confounded. Computed with min_periods=1 so the bar set is identical for every trail period.
      None = trail on the entry MA (original behavior).
    trail_timing: "next_bar" (default) applies each trail update only from the following bar onward,
      so the stop is never moved using information from inside the bar it is then checked against.
      "close" is the original behavior - update from this bar's close, then test that same bar's
      high/low - kept only to reproduce pre-2026-09-18 runs; it peeks and should not be used for
      new results.
    flat_by: if set (hour or (hour, minute), in the df's tz), force-close any open position at the
      close of the first bar at or after that time of day, and do not open a new one on that bar.
      Stop/TP are still checked first on that bar, so a level that was already hit wins. This makes
      "be flat by <time>" an actual exit rule rather than just an entry filter - session_hours only
      ever gated entries, so a trade opened inside the window could previously run for days.
      None = original behavior (no time-based exit).

    NOTE 2026-09-18: two fill bugs were fixed here, both of which made every pre-fix ma_trail number
    optimistic (see RESEARCH_LOG). (1) The MA trail could set a long's stop ABOVE the market (or a
    short's below it) whenever the trail MA sat on the wrong side of price; the stop then "filled"
    instantly at a price that never traded, manufacturing hundreds of points of phantom profit.
    (2) Stops and targets always filled exactly at their level, even when the bar opened straight
    through it; fills now happen at the open in that case.
    """
    if stop_mode == "atr" and not (atr_period and atr_stop_mult):
        raise ValueError("stop_mode='atr' requires atr_period and atr_stop_mult")
    if trail_buffer_atr and not atr_period:
        raise ValueError("trail_buffer_atr requires atr_period")
    if trail_timing not in ("close", "next_bar"):
        raise ValueError("trail_timing must be 'close' or 'next_bar'")

    df = df.copy()
    df["sma"] = df["close"].rolling(ma_period).mean()
    if trail_ma_period:
        # min_periods=1 on purpose: keeps the bar set identical across trail periods so a
        # slow-vs-fast trail comparison is not confounded by different numbers of dropped bars
        df["trail_sma"] = df["close"].rolling(trail_ma_period, min_periods=1).mean()
    if regime_ma:
        df["regime_sma"] = df["close"].rolling(regime_ma).mean()
    if atr_period:
        tr = pd.concat([
            df["high"] - df["low"],
            (df["high"] - df["close"].shift()).abs(),
            (df["low"] - df["close"].shift()).abs(),
        ], axis=1).max(axis=1)
        df["atr"] = tr.rolling(atr_period).mean()
    if atr_series is not None:
        # control hook: inject an ATR series (e.g. a time-shifted copy) so stop widths keep the same
        # distribution but are decoupled from the volatility actually present at the entry bar
        df["atr"] = atr_series.reindex(df.index)
    dropcols = ["sma"] + (["regime_sma"] if regime_ma else []) + (["atr"] if atr_period else [])
    df = df.dropna(subset=dropcols)

    mult = CONTRACT_MULT[contract]
    if tp_pts is None:
        tp_pts = stop_pts * rr

    position = 0  # 1 long, -1 short, 0 flat
    entry_price = None
    entry_ts = None
    stop_price = None
    tp_price = None
    risk_pts = None
    breakeven_hit = False
    equity = start_cap
    trades = []
    equity_curve = []

    prev_close = None
    prev_sma = None
    pending_side = None  # confirm_bars tracking: side awaiting confirmation since the raw cross
    pending_count = 0
    prev_min_of_day = None  # for the edge-triggered flat_by cutoff

    trail_col = "trail_sma" if trail_ma_period else "sma"

    def _trail_update(row, c):
        """Breakeven then buffered MA trail. Returns the new stop (never loosened)."""
        nonlocal stop_price, breakeven_hit
        buf = trail_buffer_pts
        if trail_buffer_atr:
            buf += trail_buffer_atr * row["atr"]
        if position == 1:
            if not breakeven_hit and c >= entry_price + breakeven_r * risk_pts:
                breakeven_hit = True
                stop_price = max(stop_price, min(entry_price, c))
            if breakeven_hit:
                lvl = row[trail_col] - buf
                # BUGFIX 2026-09-18: a long's stop can never sit ABOVE the market. Without this
                # guard, trailing on an MA that is above price (routine with a slow trail MA)
                # set stop > close, the l <= stop test fired immediately, and the trade was
                # booked at a price that never traded - phantom profits of hundreds of points.
                if lvl < c:
                    stop_price = max(stop_price, lvl)
        elif position == -1:
            if not breakeven_hit and c <= entry_price - breakeven_r * risk_pts:
                breakeven_hit = True
                stop_price = min(stop_price, max(entry_price, c))
            if breakeven_hit:
                lvl = row[trail_col] + buf
                if lvl > c:
                    stop_price = min(stop_price, lvl)

    for ts, row in df.iterrows():
        c, h, l = row["close"], row["high"], row["low"]

        # manage open position: trail (if enabled) then check stop/tp intrabar
        if position != 0 and trail_mode == "ma_trail" and trail_timing == "close":
            _trail_update(row, c)

        if position != 0:
            # gap-aware fill: a level set BEFORE this bar fills at the open when the bar opens
            # through it (worse than the level for a stop, better for a tp). Only applies when the
            # level predates the bar - under the legacy trail_timing="close" the trail level is
            # derived from this same bar's close, so pairing it with this bar's open is meaningless
            # and the level itself is used.
            level_predates_bar = not (trail_mode == "ma_trail" and trail_timing == "close"
                                      and breakeven_hit)
            o = row["open"]
            if position == 1:
                if l <= stop_price:
                    fill = min(stop_price, o) if level_predates_bar else stop_price
                    pnl = (fill - entry_price) * mult * contracts - cost_pts * mult * contracts
                    equity += pnl
                    reason = "trail_stop" if (trail_mode == "ma_trail" and breakeven_hit) else "stop"
                    trades.append({"exit_ts": ts, "entry_ts": entry_ts, "entry_price": entry_price, "side": "long", "reason": reason, "pnl": pnl, "stop_dist": risk_pts})
                    position = 0
                elif trail_mode == "fixed" and h >= tp_price:
                    fill = max(tp_price, o)
                    pnl = (fill - entry_price) * mult * contracts - cost_pts * mult * contracts
                    equity += pnl
                    trades.append({"exit_ts": ts, "entry_ts": entry_ts, "entry_price": entry_price, "side": "long", "reason": "tp", "pnl": pnl, "stop_dist": risk_pts})
                    position = 0
            elif position == -1:
                if h >= stop_price:
                    fill = max(stop_price, o) if level_predates_bar else stop_price
                    pnl = (entry_price - fill) * mult * contracts - cost_pts * mult * contracts
                    equity += pnl
                    reason = "trail_stop" if (trail_mode == "ma_trail" and breakeven_hit) else "stop"
                    trades.append({"exit_ts": ts, "entry_ts": entry_ts, "entry_price": entry_price, "side": "short", "reason": reason, "pnl": pnl, "stop_dist": risk_pts})
                    position = 0
                elif trail_mode == "fixed" and l <= tp_price:
                    fill = min(tp_price, o)
                    pnl = (entry_price - fill) * mult * contracts - cost_pts * mult * contracts
                    equity += pnl
                    trades.append({"exit_ts": ts, "entry_ts": entry_ts, "entry_price": entry_price, "side": "short", "reason": "tp", "pnl": pnl, "stop_dist": risk_pts})
                    position = 0

        # "be flat by <time>": time-based exit at this bar's close, checked AFTER stop/tp so an
        # already-touched level wins. Blocks a new entry on the same bar (you are going flat, not
        # re-entering one bar before the cutoff).
        flat_bar = False
        if flat_by is not None:
            now_min = ts.hour * 60 + ts.minute
            if _crossed_time(prev_min_of_day, now_min, _mins_of_day(flat_by)):
                flat_bar = True
                if position != 0:
                    sgn = 1 if position == 1 else -1
                    pnl = (c - entry_price) * sgn * mult * contracts - cost_pts * mult * contracts
                    equity += pnl
                    trades.append({"exit_ts": ts, "entry_ts": entry_ts, "entry_price": entry_price,
                                   "side": "long" if position == 1 else "short",
                                   "reason": "session_flat", "pnl": pnl, "stop_dist": risk_pts})
                    position = 0

        # confirm_bars: track a pending cross and require it to hold for N consecutive bars
        crossed_up = crossed_dn = False
        if prev_close is not None:
            raw_up = prev_close <= prev_sma and c > row["sma"]
            raw_dn = prev_close >= prev_sma and c < row["sma"]
            if raw_up:
                pending_side, pending_count = "up", 1
            elif raw_dn:
                pending_side, pending_count = "dn", 1
            elif pending_side == "up" and c > row["sma"]:
                pending_count += 1
            elif pending_side == "dn" and c < row["sma"]:
                pending_count += 1
            else:
                pending_side, pending_count = None, 0

            if pending_side == "up" and pending_count >= confirm_bars:
                crossed_up = True
                pending_side, pending_count = None, 0
            elif pending_side == "dn" and pending_count >= confirm_bars:
                crossed_dn = True
                pending_side, pending_count = None, 0

        # signal: cross and close past sma, optionally confirmed + filtered
        if prev_close is not None and position == 0 and not flat_bar:

            if crossed_up and regime_ma and c <= row["regime_sma"]:
                crossed_up = False
            if crossed_dn and regime_ma and c >= row["regime_sma"]:
                crossed_dn = False
            if (crossed_up or crossed_dn) and session_hours:
                # each bound is hour or (hour, minute); compares by minute-of-day for precision
                def _mins(x):
                    return x * 60 if isinstance(x, (int, float)) else x[0] * 60 + x[1]
                now_min = ts.hour * 60 + ts.minute
                start_m, end_m = _mins(session_hours[0]), _mins(session_hours[1])
                in_session = (start_m <= now_min < end_m) if start_m < end_m else (now_min >= start_m or now_min < end_m)
                if not in_session:
                    crossed_up = crossed_dn = False
            if (crossed_up or crossed_dn) and atr_period and atr_min_pts is not None \
                    and row["atr"] < atr_min_pts:
                crossed_up = crossed_dn = False

            if crossed_up or crossed_dn:
                # risk distance for THIS trade: constant, or scaled to volatility at the entry bar
                if stop_mode == "atr":
                    this_stop = atr_stop_mult * row["atr"]
                    this_tp = this_stop * rr
                else:
                    this_stop, this_tp = stop_pts, tp_pts

            if crossed_up:
                position = 1
                entry_price = c
                entry_ts = ts
                stop_price = c - this_stop
                tp_price = c + this_tp
                risk_pts = this_stop
                breakeven_hit = False
                trades.append({"entry_ts": ts, "side": "long", "entry_price": c})
            elif crossed_dn:
                position = -1
                entry_price = c
                entry_ts = ts
                stop_price = c + this_stop
                tp_price = c - this_tp
                risk_pts = this_stop
                breakeven_hit = False
                trades.append({"entry_ts": ts, "side": "short", "entry_price": c})

        # "next_bar" timing: the trail computed from this bar's close only takes effect on the NEXT
        # bar, so the stop is never moved using information from inside the bar it is checked against
        if position != 0 and trail_mode == "ma_trail" and trail_timing == "next_bar":
            _trail_update(row, c)

        prev_close, prev_sma = c, row["sma"]
        prev_min_of_day = ts.hour * 60 + ts.minute
        equity_curve.append({"ts": ts, "equity": equity})

    eq_df = pd.DataFrame(equity_curve).set_index("ts")
    trade_df = pd.DataFrame(trades)
    closed = trade_df[trade_df.get("pnl").notna()] if "pnl" in trade_df.columns else pd.DataFrame()
    return eq_df, closed, equity


def stats(eq_df, closed, start_cap):
    if closed.empty:
        print("No closed trades.")
        return
    n = len(closed)
    wins = closed[closed.pnl > 0]
    losses = closed[closed.pnl <= 0]
    win_rate = len(wins) / n
    avg_win = wins.pnl.mean() if len(wins) else 0
    avg_loss = losses.pnl.mean() if len(losses) else 0
    total_pnl = closed.pnl.sum()
    final_eq = start_cap + total_pnl
    ret_pct = total_pnl / start_cap * 100

    ret = eq_df["equity"].pct_change().dropna()
    bars_per_year = 288 * 252  # ~24h*12(5min)*252d futures approx; rough
    sharpe = ret.mean() / ret.std() * np.sqrt(bars_per_year) if ret.std() > 0 else float("nan")

    running_max = eq_df["equity"].cummax()
    dd = (eq_df["equity"] - running_max) / running_max
    max_dd = dd.min() * 100

    print(f"Trades: {n}  Win rate: {win_rate:.1%}")
    print(f"Avg win: ${avg_win:.2f}  Avg loss: ${avg_loss:.2f}  Payoff ratio: {abs(avg_win/avg_loss):.2f}" if avg_loss else "")
    print(f"Total P&L: ${total_pnl:,.2f}  Return: {ret_pct:.1f}%  Final equity: ${final_eq:,.2f}")
    print(f"Sharpe (rough, bar-freq annualized): {sharpe:.2f}")
    print(f"Max drawdown: {max_dd:.1f}%")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--ma", type=int, default=20)
    ap.add_argument("--stop", type=float, default=8.0)
    ap.add_argument("--rr", type=float, default=2.0)
    ap.add_argument("--contract", default="MGC", choices=["MGC", "GC", "NQ", "MNQ"])
    ap.add_argument("--data", default="data/gold_5m.csv")
    ap.add_argument("--contracts", type=int, default=1)
    ap.add_argument("--cost", type=float, default=0.3, help="round-trip cost in points (spread+comm)")
    args = ap.parse_args()

    df = load_data(args.data)
    eq_df, closed, final = run_backtest(
        df, ma_period=args.ma, stop_pts=args.stop, rr=args.rr,
        contract=args.contract, contracts=args.contracts, cost_pts=args.cost,
    )
    print(f"MA={args.ma} stop={args.stop}pts rr={args.rr} contract={args.contract}x{args.contracts} cost={args.cost}pts")
    stats(eq_df, closed, start_cap=50000)
    closed.to_csv("data/backtest_trades.csv", index=False)
    eq_df.to_csv("data/backtest_equity.csv")
