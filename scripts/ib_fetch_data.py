"""Pull long-history 5min GC/MGC bars from IB (requires IB Gateway/TWS running, paper acct).
Run scripts/ib_fetch_data.py after IB Gateway is up and logged into paper trading.
"""
import argparse
from ib_insync import IB, Future
import pandas as pd


def connect(port=4002, client_id=7):
    ib = IB()
    ib.connect("127.0.0.1", port, clientId=client_id)
    return ib


def fetch_bars(ib, symbol="MGC", exchange="COMEX", duration="2 Y", bar_size="5 mins"):
    contract = Future(symbol=symbol, exchange=exchange, currency="USD")
    details = ib.reqContractDetails(contract)
    if not details:
        raise RuntimeError(f"No contract found for {symbol} on {exchange} - check symbol/exchange")
    # use the front-month/nearest active contract
    contract = details[0].contract
    bars = ib.reqHistoricalData(
        contract,
        endDateTime="",
        durationStr=duration,
        barSizeSetting=bar_size,
        whatToShow="TRADES",
        useRTH=False,
        formatDate=1,
    )
    df = pd.DataFrame([{
        "datetime": b.date, "open": b.open, "high": b.high,
        "low": b.low, "close": b.close, "volume": b.volume,
    } for b in bars]).set_index("datetime")
    return df


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="MGC")
    ap.add_argument("--exchange", default="COMEX")
    ap.add_argument("--duration", default="2 Y")
    ap.add_argument("--port", type=int, default=4002)
    args = ap.parse_args()

    ib = connect(port=args.port)
    df = fetch_bars(ib, symbol=args.symbol, exchange=args.exchange, duration=args.duration)
    out = "data/gold_5m_ib.csv"
    df.to_csv(out)
    print(f"{len(df)} bars -> {out}")
    print(df.head())
    print(df.tail())
    ib.disconnect()
