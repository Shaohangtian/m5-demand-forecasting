"""阶段 6：四模型 × 10 折 × 28 天滚动回测"""
import warnings

import numpy as np
import pandas as pd

from config import CSV, MET
from db import q

warnings.filterwarnings("ignore")

HORIZON = 42           # 预测 42 天
EVAL_H = 28            # 只考核前 28 天
N_FOLDS = 10
FIRST_ORIGIN_D = 1633  # 训练截止日

# ---------- 读数据 ----------
print("读取特征...")
feat = pd.read_parquet(CSV / "features.parquet")
cal = q("SELECT sale_date, d FROM calendar ORDER BY sale_date")
abc = q("SELECT item_id, abc FROM abc_class")

feat["sale_date"] = pd.to_datetime(feat["sale_date"])
cal["sale_date"] = pd.to_datetime(cal["sale_date"])

items = np.sort(feat["item_id"].unique())
dates = np.sort(feat["sale_date"].unique())
Y = (feat.pivot(index="item_id", columns="sale_date", values="y")
        .reindex(index=items, columns=dates).fillna(0).values.astype(np.float32))
date_of_d = dict(zip(cal["d"], cal["sale_date"]))
date_idx = {d: i for i, d in enumerate(dates)}

print("SKU:", len(items), "日期:", len(dates), "矩阵:", Y.shape)

FEATURES = ["lag_1", "lag_7", "lag_14", "lag_28", "ma_7", "ma_28", "ma_56",
            "sd_7", "sd_28", "mx_28", "mn_28", "zero_days_28",
            "ma7_ma28_ratio", "price_vs_avg28", "price_delta",
            "wday", "month", "snap_CA", "is_event"]


def naive_seasonal(hist, h):
    out = np.zeros((hist.shape[0], h), dtype=np.float32)
    buf = np.concatenate([hist, np.zeros((hist.shape[0], h), np.float32)], axis=1)
    n = hist.shape[1]
    for k in range(h):
        v = buf[:, n + k - 7]
        buf[:, n + k] = v
        out[:, k] = v
    return out


def moving_average(hist, h, w=28):
    base = hist[:, -w:].mean(axis=1)
    return np.repeat(base[:, None], h, axis=1).astype(np.float32)


def holt_winters(hist, h):
    """Holt-Winters，失败则回落季节朴素"""
    from statsmodels.tsa.holtwinters import ExponentialSmoothing
    out = np.zeros((hist.shape[0], h), dtype=np.float32)
    fallback = 0
    for i in range(hist.shape[0]):
        s = hist[i].astype(np.float64)
        try:
            if s.sum() < 10:
                raise ValueError("too sparse")
            m = ExponentialSmoothing(
                s, trend="add", seasonal="add", seasonal_periods=7,
                initialization_method="estimated",
                use_boxcox=False,                      # ← 移进构造函数
            )
            fit = m.fit(optimized=True, remove_bias=False)   # ← 这里去掉 use_boxcox
            out[i] = np.maximum(fit.forecast(h), 0)
        except Exception:
            fallback += 1
            out[i] = naive_seasonal(s[None, :], h)[0]
    print(f"    Holt-Winters 回落季节朴素: {fallback} 条")
    return out


def lightgbm_recursive(origin_idx, h):
    import lightgbm as lgb
    train = feat[(feat["sale_date"] <= dates[origin_idx])].dropna(subset=["ma_28"])
    tr = train.dropna(subset=FEATURES)
    X, y = tr[FEATURES].values.astype(np.float32), tr["y"].values.astype(np.float32)
    model = lgb.LGBMRegressor(
        objective="tweedie", tweedie_variance_power=1.1,
        n_estimators=600, learning_rate=0.05, num_leaves=96,
        min_child_samples=50, feature_fraction=0.8,
        subsample=0.8, subsample_freq=1, n_jobs=-1, verbose=-1,
    )
    model.fit(X, y)
    ext = Y[:, :origin_idx + 1].copy()
    preds = np.zeros((len(items), h), dtype=np.float32)
    F = feat[feat["sale_date"] == dates[origin_idx]].set_index("item_id")[FEATURES]
    cur = F.reindex(items).values.astype(np.float32)
    for k in range(h):
        p = np.maximum(model.predict(cur), 0)
        preds[:, k] = p
        ext = np.concatenate([ext, p[:, None]], axis=1)
        cur = np.column_stack([
            np.roll(p, 1), np.roll(p, 7), np.roll(p, 14), np.roll(p, 28),
            ext[:, -7:].mean(1), ext[:, -28:].mean(1), ext[:, -56:].mean(1),
            ext[:, -7:].std(1), ext[:, -28:].std(1),
            ext[:, -28:].max(1), ext[:, -28:].min(1),
            (ext[:, -28:] == 0).sum(1),
            ext[:, -7:].mean(1) / np.maximum(ext[:, -28:].mean(1), 1e-6),
            cur[:, 13], cur[:, 14], cur[:, 15], cur[:, 16], cur[:, 17], cur[:, 18],
        ]).astype(np.float32)
        cur = np.nan_to_num(cur, nan=0.0, posinf=0.0, neginf=0.0)
    return preds


# ---------- 主循环 ----------
results, records = [], []
for k in range(N_FOLDS):
    origin_d = FIRST_ORIGIN_D + 28 * k
    start_d, end_d = origin_d + 1, origin_d + EVAL_H
    o_idx = date_idx[date_of_d[origin_d]]
    hist = Y[:, :o_idx + 1]
    print(f"\n=== F{k+1} 训练至 {date_of_d[origin_d].date()} "
          f"预测 {date_of_d[start_d].date()}~{date_of_d[end_d].date()}")

    preds = {
        "naive": naive_seasonal(hist, HORIZON),
        "ma28": moving_average(hist, HORIZON),
        "hw": holt_winters(hist, HORIZON),
        "lgbm": lightgbm_recursive(o_idx, HORIZON),
    }
    s_idx = date_idx[date_of_d[start_d]]
    truth = Y[:, s_idx: s_idx + EVAL_H]

    for name, P in preds.items():
        ph = P[:, :EVAL_H]
        err = np.abs(truth - ph)
        wmape = err.sum() / max(truth.sum(), 1)
        bias = (ph - truth).sum() / max(truth.sum(), 1)
        records.append(dict(fold=k + 1, model=name, wmape=wmape, bias=bias,
                            mae=err.mean(),
                            rmse=np.sqrt(((truth - ph) ** 2).mean())))
        print(f"  {name:6s} WMAPE={wmape:.4f} Bias={bias:+.4f}")

met = pd.DataFrame(records)
met.to_csv(MET / "metrics_fold.csv", index=False, encoding="utf-8-sig")

g = met.groupby("model")["wmape"].mean().sort_values()
print("\n=== 各模型 10 折平均 WMAPE ===")
print(g.to_string())
g.to_frame("wmape_mean").to_csv(MET / "model_compare.csv", encoding="utf-8-sig")