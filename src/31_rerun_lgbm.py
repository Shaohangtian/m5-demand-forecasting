"""只重跑 LightGBM（修正特征构造），合并进已有指标

相对手册原版的三处修正：
1. 滞后特征从时间轴取（原版 np.roll 把当天预测向量横向滚动，等于拿别的 SKU 的值当滞后）
2. 日历特征（星期/月份/SNAP/事件）随预测日期推进（原版冻结在起始日）
3. 不递归回填预测值（误差逐日放大），滞后特征冻结在起始日
   单折实测：原版 0.898 -> 修正后 0.684
"""
import numpy as np
import pandas as pd

from config import CSV, MET
from db import q

HORIZON, EVAL_H, N_FOLDS, FIRST_ORIGIN_D = 42, 28, 10, 1633

FEATURES = ["lag_1", "lag_7", "lag_14", "lag_28", "ma_7", "ma_28", "ma_56",
            "sd_7", "sd_28", "mx_28", "mn_28", "zero_days_28",
            "ma7_ma28_ratio", "price_vs_avg28", "price_delta",
            "wday", "month", "snap_CA", "is_event"]
I_WDAY, I_MONTH, I_SNAP, I_EVENT = 15, 16, 17, 18

feat = pd.read_parquet(CSV / "features.parquet")
cal = q("SELECT sale_date, d FROM calendar ORDER BY sale_date")
feat["sale_date"] = pd.to_datetime(feat["sale_date"])
cal["sale_date"] = pd.to_datetime(cal["sale_date"])

items = np.sort(feat["item_id"].unique())
dates = np.sort(feat["sale_date"].unique())
Y = (feat.pivot(index="item_id", columns="sale_date", values="y")
        .reindex(index=items, columns=dates).fillna(0).values.astype(np.float32))

date_of_d = dict(zip(cal["d"], cal["sale_date"]))
date_idx = {d: i for i, d in enumerate(dates)}

# 每个日期对应的日历特征（同一天对所有 SKU 相同）
cal_feat = (feat.drop_duplicates("sale_date")
                .set_index("sale_date")[["wday", "month", "snap_CA", "is_event"]])


def lgbm_fold(origin_idx, h):
    import lightgbm as lgb

    train = feat[feat["sale_date"] <= dates[origin_idx]].dropna(subset=FEATURES)
    X = train[FEATURES].values.astype(np.float32)
    y = train["y"].values.astype(np.float32)

    model = lgb.LGBMRegressor(
        objective="tweedie", tweedie_variance_power=1.1,
        n_estimators=600, learning_rate=0.05, num_leaves=96,
        min_child_samples=50, feature_fraction=0.8,
        subsample=0.8, subsample_freq=1, n_jobs=-1, verbose=-1,
    )
    model.fit(X, y)

    base = (feat[feat["sale_date"] == dates[origin_idx]]
            .set_index("item_id")[FEATURES].reindex(items)
            .fillna(0.0).values.astype(np.float32))

    preds = np.zeros((len(items), h), dtype=np.float32)
    for k in range(h):
        cur = base.copy()
        wd, mo, sp, ev = cal_feat.loc[dates[origin_idx + 1 + k]]
        cur[:, I_WDAY], cur[:, I_MONTH] = wd, mo
        cur[:, I_SNAP], cur[:, I_EVENT] = sp, ev
        preds[:, k] = np.maximum(model.predict(cur), 0)
    return preds


records = []
for k in range(N_FOLDS):
    origin_d = FIRST_ORIGIN_D + 28 * k
    start_d = origin_d + 1
    o_idx = date_idx[date_of_d[origin_d]]

    P = lgbm_fold(o_idx, HORIZON)
    s_idx = date_idx[date_of_d[start_d]]
    truth = Y[:, s_idx: s_idx + EVAL_H]
    ph = P[:, :EVAL_H]

    err = np.abs(truth - ph)
    wmape = err.sum() / max(truth.sum(), 1)
    records.append(dict(fold=k + 1, model="lgbm", wmape=wmape,
                        bias=(ph - truth).sum() / max(truth.sum(), 1),
                        mae=err.mean(),
                        rmse=np.sqrt(((truth - ph) ** 2).mean())))
    print(f"  F{k+1} lgbm WMAPE={wmape:.4f}  预测均值={ph.mean():.2f}")

new = pd.DataFrame(records)
old = pd.read_csv(MET / "metrics_fold.csv")
merged = (pd.concat([old[old["model"] != "lgbm"], new])
            .sort_values(["fold", "model"]).reset_index(drop=True))
merged.to_csv(MET / "metrics_fold.csv", index=False, encoding="utf-8-sig")

g = merged.groupby("model")["wmape"].mean().sort_values()
print("\n=== 各模型 10 折平均 WMAPE ===")
print(g.to_string())
g.to_frame("wmape_mean").to_csv(MET / "model_compare.csv", encoding="utf-8-sig")
print(f"\n指标文件：{MET / 'metrics_fold.csv'}  （{len(merged)} 行）")