# -*- coding: utf-8 -*-
"""第 5 章 特征工程 —— pandas 实现（替代 MySQL 窗口函数）

为什么不用手册里的 SQL
----------------------
MySQL 8 对每一种「窗口规范」（分区 + 排序 + 行帧）都要把 279 万行重新排一遍。
手册那条 SQL 含 4 种不同帧、16 个窗口函数，实测连续两次都跑满 30 分钟
（Workbench 报 Error 2013），加上 128 MB 的 buffer pool，排序还要落盘归并。

这里用 pandas 算完全等价的特征。已用 3 个商品 × 1941 天逐行对照过 MySQL
窗口函数的结果：ma_7 / mn_28 完全一致，其余仅差浮点末位。

输出
----
    outputs/csv/features.parquet   第 6 章直接读取

用法
----
    cd src
    py 13_build_features.py
"""
import time

import numpy as np
import pandas as pd

from config import CSV
from db import q

FEATURE_COLS = [
    "lag_1", "lag_7", "lag_14", "lag_28",
    "ma_7", "ma_28", "ma_56",
    "sd_7", "sd_28", "mx_28", "mn_28", "zero_days_28",
    "ma7_ma28_ratio", "price_vs_avg28", "price_delta",
]

t0 = time.time()

# ---------------------------------------------------------------------------
# 1. 读明细
# ---------------------------------------------------------------------------
print("1/4 读取明细 ...")
df = q("""
    SELECT item_id, sale_date, dept_id,
           units_sold                 AS y,
           sell_price,
           wday, `month`, `year`, snap_CA,
           (event_name_1 IS NOT NULL) AS is_event
    FROM v_sales_enriched
""")
print(f"    {len(df):,} 行  （{time.time() - t0:.1f}s）")

df["sale_date"] = pd.to_datetime(df["sale_date"])
df = df.sort_values(["item_id", "sale_date"], kind="stable").reset_index(drop=True)

for c in ("wday", "month", "year", "snap_CA", "is_event"):
    df[c] = df[c].astype("int16")
df["y"] = df["y"].astype("int32")
df["sell_price"] = df["sell_price"].astype("float32")

# ---------------------------------------------------------------------------
# 2. 特征
#    铁律：第 t 行只能用 t-1 及以前的数据 —— 全部先 shift(1) 再滚动
#    MySQL 的 "N PRECEDING AND 1 PRECEDING" ≡ 先 shift(1) 后 rolling(N)
# ---------------------------------------------------------------------------
print("2/4 计算特征 ...")
g = df.groupby("item_id", sort=False)
y_prev = g["y"].shift(1)


def rolled(series: pd.Series, window: int, how: str, **kw) -> pd.Series:
    """按商品分组做滚动窗口（窗口内不含当天）"""
    r = series.groupby(df["item_id"], sort=False).rolling(window, min_periods=1)
    out = getattr(r, how)(**kw)
    return out.droplevel(0).sort_index()


# 滞后
df["lag_1"] = g["y"].shift(1)
df["lag_7"] = g["y"].shift(7)
df["lag_14"] = g["y"].shift(14)
df["lag_28"] = g["y"].shift(28)

# 滚动均值
df["ma_7"] = rolled(y_prev, 6, "mean")
df["ma_28"] = rolled(y_prev, 27, "mean")
df["ma_56"] = rolled(y_prev, 55, "mean")

# 滚动标准差（样本标准差，与 STDDEV_SAMP 一致）
df["sd_7"] = rolled(y_prev, 6, "std", ddof=1)
df["sd_28"] = rolled(y_prev, 27, "std", ddof=1)

# 极值
df["mx_28"] = rolled(y_prev, 27, "max")
df["mn_28"] = rolled(y_prev, 27, "min")

# 零销量天数（每个商品第 1 天保持 NaN，与 MySQL 空窗口返回 NULL 对齐）
zero_prev = y_prev.eq(0).astype("float64").where(y_prev.notna())
df["zero_days_28"] = rolled(zero_prev, 27, "sum")

# 趋势比
df["ma7_ma28_ratio"] = df["ma_7"] / df["ma_28"].replace(0, np.nan)

# 价格特征
price_prev = g["sell_price"].shift(1).astype("float64")
price_ma28 = rolled(price_prev, 27, "mean").replace(0, np.nan)
df["price_vs_avg28"] = df["sell_price"] / price_ma28
df["price_delta"] = df["sell_price"] - price_prev

for c in FEATURE_COLS:
    df[c] = df[c].astype("float32")

print(f"    （{time.time() - t0:.1f}s）")

# ---------------------------------------------------------------------------
# 3. 自检
# ---------------------------------------------------------------------------
print("3/4 自检 ...")
n_rows = len(df)
null_ma7 = int(df["ma_7"].isna().sum())
null_ma28 = int(df["ma_28"].isna().sum())
print(f"    行数            {n_rows:>12,}   期望 2,789,217")
print(f"    ma_7  空值数    {null_ma7:>12,}   期望 1,437（每 SKU 第 1 天）")
print(f"    ma_28 空值数    {null_ma28:>12,}   期望 1,437")

if n_rows != 2_789_217:
    raise SystemExit(f"行数不对：{n_rows}")
if null_ma7 != 1_437:
    raise SystemExit(
        f"ma_7 空值数不对：{null_ma7}（若为 0 说明窗口含当天 = 标签泄漏，必须改）"
    )

# ---------------------------------------------------------------------------
# 4. 落盘
# ---------------------------------------------------------------------------
print("4/4 写 parquet ...")
out = CSV / "features.parquet"
df.to_parquet(out, index=False, compression="zstd")
print(f"    {out}")
print(f"    {out.stat().st_size / 1e6:.1f} MB，{df.shape[0]:,} 行 × {df.shape[1]} 列")
print(f"\n完成，总耗时 {time.time() - t0:.1f}s")
