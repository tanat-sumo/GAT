"""Pull free historical tick data from Dukascopy's public feed (no account/API key needed),
resample to 5min OHLC. XAUUSD (spot gold) - a proxy for GC/MGC futures, not exact, but free
and goes back years vs yfinance's 60-day cap on intraday data.

Dukascopy serves one compressed (LZMA) binary file per instrument per hour:
https://datafeed.dukascopy.com/datafeed/XAUUSD/YYYY/MM(0-indexed)/DD/HHh_ticks.bi5
Each tick record is 20 bytes, big-endian: uint32 ms-offset, uint32 bid*scale, uint32 ask*scale,
float32 bid_vol, float32 ask_vol. Empty response = no ticks that hour (weekend/holiday/quiet).
"""
import argparse
import struct
import lzma
from datetime import datetime, timedelta, timezone
import requests
import pandas as pd

BASE = "https://datafeed.dukascopy.com/datafeed"
POINT_SCALE = 1000.0  # XAUUSD: raw int / 1000 = price in USD (verified against known price range)


def fetch_hour(symbol, dt):
    url = f"{BASE}/{symbol}/{dt.year}/{dt.month-1:02d}/{dt.day:02d}/{dt.hour:02d}h_ticks.bi5"
    r = requests.get(url, timeout=15)
    if r.status_code != 200 or len(r.content) == 0:
        return []
    try:
        raw = lzma.decompress(r.content)
    except lzma.LZMAError:
        return []
    ticks = []
    for i in range(0, len(raw), 20):
        chunk = raw[i:i+20]
        if len(chunk) < 20:
            break
        ms_off, bid_raw, ask_raw, bid_vol, ask_vol = struct.unpack(">IIIff", chunk)
        ts = dt + timedelta(milliseconds=ms_off)
        ticks.append((ts, bid_raw / POINT_SCALE, ask_raw / POINT_SCALE))
    return ticks


def fetch_range(symbol, start, end):
    all_ticks = []
    cur = start
    hours_tried, hours_with_data = 0, 0
    while cur < end:
        t = fetch_hour(symbol, cur)
        hours_tried += 1
        if t:
            hours_with_data += 1
            all_ticks.extend(t)
        cur += timedelta(hours=1)
    print(f"{symbol}: {hours_with_data}/{hours_tried} hours had data, {len(all_ticks)} ticks")
    return all_ticks


def ticks_to_5m_ohlc(ticks):
    df = pd.DataFrame(ticks, columns=["ts", "bid", "ask"])
    df["mid"] = (df["bid"] + df["ask"]) / 2
    df = df.set_index("ts")
    ohlc = df["mid"].resample("5min").ohlc()
    ohlc["volume"] = df["mid"].resample("5min").count()
    ohlc = ohlc.dropna(subset=["open"])
    return ohlc


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--start", required=True, help="YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD")
    ap.add_argument("--out", default="data/xauusd_5m_dukascopy.csv")
    args = ap.parse_args()

    start = datetime.strptime(args.start, "%Y-%m-%d")
    end = datetime.strptime(args.end, "%Y-%m-%d")
    ticks = fetch_range(args.symbol, start, end)
    if not ticks:
        print("No ticks fetched - check symbol/date range/connectivity.")
        exit(1)
    df = ticks_to_5m_ohlc(ticks)
    df.to_csv(args.out)
    print(f"{len(df)} 5min bars -> {args.out}")
    print(df.head())
    print(df.tail())
