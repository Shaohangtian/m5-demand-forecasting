import pandas as pd
from config import DATA
from db import engine, q

# ---------- calendar ----------
cal = pd.read_csv(DATA / "calendar.csv")
cal = cal.rename(columns={"date": "sale_date"})
cal["d"] = cal["d"].str.replace("d_", "", regex=False).astype(int)
cal = cal[cal.d <= 1941].copy()

cal["sale_date"] = pd.to_datetime(cal["sale_date"])
cal["day"] = cal["sale_date"].dt.day          # ← 手册漏了这行，原数据中没有day列，必须补
cal["sale_date"] = cal["sale_date"].dt.date

cal = cal[["sale_date", "d", "wm_yr_wk", "weekday", "wday", "month",
           "year", "day", "event_name_1", "event_type_1",
           "event_name_2", "event_type_2", "snap_CA", "snap_TX", "snap_WI"]]
print("calendar 行数:", len(cal), "（应为 1941）")
cal.to_sql("calendar", engine(), if_exists="replace", index=False)

# ---------- sell_prices：只保留 CA_1 且属于 1437 个 SKU 的 ----------
skus = set(q("SELECT DISTINCT item_id FROM sales")["item_id"])
parts = []
for chunk in pd.read_csv(DATA / "sell_prices.csv", chunksize=1_000_000):
    sub = chunk[(chunk.store_id == "CA_1") & chunk.item_id.isin(skus)]
    if len(sub):
        parts.append(sub)
sp = pd.concat(parts, ignore_index=True)
print("sell_prices 行数:", len(sp))
sp.to_sql("sell_prices", engine(), if_exists="replace",
          index=False, chunksize=50_000, method="multi")