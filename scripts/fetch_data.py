"""Pull 5min gold futures bars for backtest (yfinance continuous contract GC=F)."""
import yfinance as yf
import pandas as pd

def fetch_gold_5m(period="60d"):
    df = yf.download("GC=F", period=period, interval="5m", auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.index.name = "datetime"
    return df

if __name__ == "__main__":
    df = fetch_gold_5m()
    out = "data/gold_5m.csv"
    df.to_csv(out)
    print(f"{len(df)} bars -> {out}")
    print(df.head())
    print(df.tail())
