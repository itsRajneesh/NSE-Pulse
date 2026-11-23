import yfinance as yf

from app.backtest_nifty500_v6 import extract_ticker_df
from app.v13_engine import _true_velocity, _session_dates

symbol = "RELIANCE"

print(f"Downloading {symbol}...")

downloaded = yf.download(
    tickers=[f"{symbol}.NS"],
    period="60d",
    interval="15m",
    group_by="ticker",
    auto_adjust=False,
    progress=False,
    threads=False,
)

df = extract_ticker_df(downloaded, symbol)

if df is None or df.empty:
    print("ERROR: No stock data")
    raise SystemExit(1)

dates = _session_dates(df)
velocity = _true_velocity(df)

print()
print("========== B2 DIAGNOSTIC ==========")
print(f"Rows       : {len(df)}")
print(f"Sessions   : {len(dates)}")
print(f"First date : {dates[0] if dates else 'N/A'}")
print(f"Last date  : {dates[-1] if dates else 'N/A'}")
print(f"Velocity   : {velocity}")
print("====================================")
