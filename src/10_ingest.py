"""阶段 1：宽表转长表，导出 CSV 供 LOAD DATA 使用"""
import pandas as pd
from config import DATA, CSV

N_DAYS = 1941
DIM = ["id", "item_id", "dept_id", "cat_id", "store_id", "state_id"]
DCOLS = [f"d_{i}" for i in range(1, N_DAYS + 1)]

# --- 1. 读宽表（d 列用 int16，30k×1941 只占约 120MB）---
dtype = {c: "int16" for c in DCOLS}
wide = pd.read_csv(DATA / "sales_train_evaluation.csv",
                   usecols=DIM + DCOLS, dtype=dtype)

# --- 2. 只保留 CA_1 门店的 FOODS 品类 ---
wide = wide[(wide.store_id == "CA_1") & (wide.cat_id == "FOODS")].copy()
print("SKU 数:", len(wide), "（应为 1437）")

# --- 3. 宽转长 ---
long = wide.melt(
    id_vars=["item_id", "dept_id", "cat_id", "store_id", "state_id"],
    value_vars=DCOLS,
    var_name="d",
    value_name="units_sold",
)
long["d"] = long["d"].str.replace("d_", "", regex=False).astype("int16")
long["units_sold"] = long["units_sold"].astype("int32").astype("int16")
print("长表行数:", len(long), "（应为 2789217）")

# --- 4. 挂上真实日期 ---
cal = pd.read_csv(DATA / "calendar.csv", usecols=["date", "d"])
cal["d"] = cal["d"].str.replace("d_", "", regex=False).astype("int16")
cal = cal.rename(columns={"date": "sale_date"})
long = long.merge(cal, on="d", how="left")
assert long.sale_date.notna().all(), "有日期没匹配上"

# --- 5. 导出（列顺序固定，给 LOAD DATA 用）---
out_cols = ["store_id", "item_id", "dept_id", "cat_id",
            "state_id", "sale_date", "units_sold"]
path = CSV / "sales_long.csv"
long[out_cols].to_csv(path, index=False, header=True)
print("已写出:", path, path.stat().st_size / 1e6, "MB")