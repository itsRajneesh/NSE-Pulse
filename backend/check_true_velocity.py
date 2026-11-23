from pathlib import Path
import pandas as pd

from app.v13_engine import _true_velocity, _session_dates

DATA_DIR = Path("data")

files = list(DATA_DIR.glob("*.csv"))

print(f"CSV files found: {len(files)}")

for path in files[:5]:
    print(f"\n--- {path.name} ---")

    try:
        df = pd.read_csv(path)

        # Common OHLCV column normalisation
        rename_map = {}
        for col in df.columns:
            key = str(col).strip().lower()
            if key == "datetime":
                rename_map[col] = "Datetime"
            elif key == "date":
                rename_map[col] = "Datetime"
            elif key == "open":
                rename_map[col] = "Open"
            elif key == "high":
                rename_map[col] = "High"
            elif key == "low":
                rename_map[col] = "Low"
            elif key == "close":
                rename_map[col] = "Close"
            elif key == "volume":
                rename_map[col] = "Volume"

        df = df.rename(columns=rename_map)

        if "Datetime" not in df.columns:
            print("  SKIP: no Datetime column")
            continue

        df["Datetime"] = pd.to_datetime(df["Datetime"], errors="coerce")
        df = df.dropna(subset=["Datetime"])
        df = df.set_index("Datetime").sort_index()

        required = ["Open", "High", "Low", "Close", "Volume"]
        if not all(col in df.columns for col in required):
            print("  SKIP: missing OHLCV columns")
            continue

        dates = _session_dates(df)

        velocity = _true_velocity(df)

        print(f"  Rows       : {len(df)}")
        print(f"  Sessions   : {len(dates)}")
        print(f"  First date : {dates[0] if len(dates) else 'N/A'}")
        print(f"  Last date  : {dates[-1] if len(dates) else 'N/A'}")
        print(f"  Velocity   : {velocity}")

    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}")
