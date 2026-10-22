# -*- coding: utf-8 -*-
"""快速数据画像：确认 M5 数据结构、时间跨度、缺失情况。"""
import json
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(ROOT, "outputs")
os.makedirs(OUT, exist_ok=True)

res = {}

# ---------- calendar ----------
cal = pd.read_csv(os.path.join(DATA, "calendar.csv"), parse_dates=["date"])
res["calendar"] = {
    "rows": int(len(cal)),
    "date_min": str(cal["date"].min().date()),
    "date_max": str(cal["date"].max().date()),
    "d_min": cal["d"].iloc[0],
    "d_max": cal["d"].iloc[-1],
    "n_events": int(cal["event_name_1"].notna().sum()),
    "n_events_2": int(cal["event_name_2"].notna().sum()),
    "snap_rate": {c: round(float(cal[c].mean()), 4) for c in ["snap_CA", "snap_TX", "snap_WI"]},
}

# ---------- sales ----------
def sales_meta(fn, n_sales_cols_expected=None):
    head = pd.read_csv(os.path.join(DATA, fn), nrows=0)
    cols = head.columns.tolist()
    dcols = [c for c in cols if c.startswith("d_")]
    # 只读 id 维度列，算出序列/层级规模
    dim = pd.read_csv(os.path.join(DATA, fn), usecols=["id", "item_id", "dept_id", "cat_id", "store_id", "state_id"])
    return {
        "rows": int(len(dim)),
        "n_day_cols": len(dcols),
        "first_day": dcols[0],
        "last_day": dcols[-1],
        "n_items": int(dim["item_id"].nunique()),
        "n_depts": int(dim["dept_id"].nunique()),
        "n_cats": int(dim["cat_id"].nunique()),
        "n_stores": int(dim["store_id"].nunique()),
        "n_states": int(dim["state_id"].nunique()),
        "depts": sorted(dim["dept_id"].unique().tolist()),
        "cats": sorted(dim["cat_id"].unique().tolist()),
        "stores": sorted(dim["store_id"].unique().tolist()),
    }

res["sales_validation"] = sales_meta("sales_train_validation.csv")
res["sales_evaluation"] = sales_meta("sales_train_evaluation.csv")

# ---------- sell_prices ----------
sp_head = pd.read_csv(os.path.join(DATA, "sell_prices.csv"), nrows=0)
sp = pd.read_csv(os.path.join(DATA, "sell_prices.csv"), usecols=["wm_yr_wk", "sell_price"])
res["sell_prices"] = {
    "rows": int(len(sp)),
    "wm_yr_wk_min": int(sp["wm_yr_wk"].min()),
    "wm_yr_wk_max": int(sp["wm_yr_wk"].max()),
    "price_min": round(float(sp["sell_price"].min()), 2),
    "price_max": round(float(sp["sell_price"].max()), 2),
    "price_mean": round(float(sp["sell_price"].mean()), 2),
    "n_nan_price": int(sp["sell_price"].isna().sum()),
}

# ---------- submission ----------
ss = pd.read_csv(os.path.join(DATA, "sample_submission.csv"))
res["submission"] = {
    "rows": int(len(ss)),
    "n_forecast_cols": len([c for c in ss.columns if c.startswith("F")]),
    "id_sample": ss["id"].head(2).tolist(),
    "id_tail": ss["id"].tail(2).tolist(),
}

print(json.dumps(res, ensure_ascii=False, indent=2))
with open(os.path.join(OUT, "profile.json"), "w", encoding="utf-8") as f:
    json.dump(res, f, ensure_ascii=False, indent=2)
