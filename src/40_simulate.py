# -*- coding: utf-8 -*-
"""阶段 7：(R,S) 补货仿真，固定 SKU 级 fill rate = 95%

手册只给了 solve_ss / simulate 两个函数和伪代码，这里补成可运行的完整脚本：
  1. 用第 6 章的四种口径生成 280 天逐日预测（每折 42 天，取前 28 天拼接）
  2. 由回测残差解安全库存 SS（二分法解 fill rate 方程，不是取分位数）
  3. 标定循环：调 SS 直到 SKU 级 fill rate 中位数落在 0.95±0.003
  4. 成本最优服务水平扫描（9 个点）
"""
import numpy as np
import pandas as pd

from config import CSV, SIM, MET
from db import q

R, LT = 7, 7
PROT = R + LT
TARGET_BETA = 0.95
N_DAYS = 280
N_FOLDS = 10
FIRST_ORIGIN_D = 1633
HORIZON, EVAL_H = 42, 28

FEATURES = ["lag_1", "lag_7", "lag_14", "lag_28", "ma_7", "ma_28", "ma_56",
            "sd_7", "sd_28", "mx_28", "mn_28", "zero_days_28",
            "ma7_ma28_ratio", "price_vs_avg28", "price_delta",
            "wday", "month", "snap_CA", "is_event"]
I_WDAY, I_MONTH, I_SNAP, I_EVENT = 15, 16, 17, 18

# ---------------------------------------------------------------------------
# 数据
# ---------------------------------------------------------------------------
print("读取数据 ...")
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
n_sku = len(items)

price = (q("SELECT item_id, AVG(sell_price) p FROM v_sales_enriched GROUP BY item_id")
         .set_index("item_id")["p"].reindex(items).values)
abc = (q("SELECT item_id, abc FROM abc_class")
       .set_index("item_id")["abc"].reindex(items).values)

cal_feat = (feat.drop_duplicates("sale_date")
                .set_index("sale_date")[["wday", "month", "snap_CA", "is_event"]])


# ---------------------------------------------------------------------------
# 四模型预测（与第 6 章一致）
# ---------------------------------------------------------------------------
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
    return np.repeat(hist[:, -w:].mean(axis=1)[:, None], h, axis=1).astype(np.float32)


def lgbm_direct(origin_idx, h):
    """滞后特征冻结在起始日 + 日历特征随预测日期推进（第 6 章修正后的版本）"""
    import lightgbm as lgb
    train = feat[feat["sale_date"] <= dates[origin_idx]].dropna(subset=FEATURES)
    X = train[FEATURES].values.astype(np.float32)
    y = train["y"].values.astype(np.float32)
    model = lgb.LGBMRegressor(
        objective="tweedie", tweedie_variance_power=1.1,
        n_estimators=600, learning_rate=0.05, num_leaves=96,
        min_child_samples=50, feature_fraction=0.8,
        subsample=0.8, subsample_freq=1, n_jobs=-1, verbose=-1)
    model.fit(X, y)
    base = (feat[feat["sale_date"] == dates[origin_idx]]
            .set_index("item_id")[FEATURES].reindex(items)
            .fillna(0.0).values.astype(np.float32))
    preds = np.zeros((n_sku, h), dtype=np.float32)
    for k in range(h):
        cur = base.copy()
        wd, mo, sp, ev = cal_feat.loc[dates[origin_idx + 1 + k]]
        cur[:, I_WDAY], cur[:, I_MONTH] = wd, mo
        cur[:, I_SNAP], cur[:, I_EVENT] = sp, ev
        preds[:, k] = np.maximum(model.predict(cur), 0)
    return preds


print("生成 10 折预测（lgbm 较慢，约 5~8 分钟）...")
CACHE = SIM / "preds_cache.npz"
BASES = ("naive", "ma28", "lgbm")
if CACHE.exists():
    z = np.load(CACHE)
    preds = {b: [z[f"{b}_{k}"] for k in range(N_FOLDS)] for b in BASES}
    print(f"  命中缓存 {CACHE.name}，跳过重算")
else:
    preds = {b: [] for b in BASES}
    for k in range(N_FOLDS):
        o_idx = date_idx[date_of_d[FIRST_ORIGIN_D + 28 * k]]
        hist = Y[:, :o_idx + 1]
        preds["naive"].append(naive_seasonal(hist, HORIZON))
        preds["ma28"].append(moving_average(hist, HORIZON))
        preds["lgbm"].append(lgbm_direct(o_idx, HORIZON))
        print(f"  F{k + 1} 完成")
    np.savez_compressed(
        CACHE, **{f"{b}_{k}": preds[b][k] for b in BASES for k in range(N_FOLDS)})
    print(f"  预测已缓存到 {CACHE.name}")

# ---------------------------------------------------------------------------
# 拼成 280 天的仿真序列
# ---------------------------------------------------------------------------
demand = np.zeros((n_sku, N_DAYS), dtype=np.float32)
forecast = {b: np.zeros((n_sku, N_DAYS), dtype=np.float32) for b in preds}

for k in range(N_FOLDS):
    o_idx = date_idx[date_of_d[FIRST_ORIGIN_D + 28 * k]]
    s_idx = date_idx[date_of_d[FIRST_ORIGIN_D + 28 * k + 1]]
    block = slice(k * 28, (k + 1) * 28)
    demand[:, block] = Y[:, s_idx: s_idx + 28]
    for j in range(0, 28, R):                      # 每个 28 天块里 4 个评审点
        for b in preds:
            forecast[b][:, k * 28 + j] = preds[b][k][:, j:j + PROT].sum(axis=1)


# ---------------------------------------------------------------------------
# 安全库存求解与仿真（手册 Step 7.2 原样）
# ---------------------------------------------------------------------------
def solve_ss(errors_14, demand_14, target=TARGET_BETA):
    ss = np.zeros(n_sku)
    for i in range(n_sku):
        e = errors_14[i][~np.isnan(errors_14[i])]
        d = max(demand_14[i], 1e-6)
        if len(e) == 0:
            continue
        lo, hi = 0.0, max(e.max(), 0.0) + 1.0
        for _ in range(40):
            mid = (lo + hi) / 2
            beta = 1 - np.maximum(e - mid, 0).mean() / d
            if beta < target:
                lo = mid
            else:
                hi = mid
        ss[i] = hi
    return ss


def simulate(demand, forecast, ss, keep_daily=False):
    T = demand.shape[1]
    I = np.zeros(n_sku)
    pipe = np.zeros((n_sku, LT))
    on_hand = np.zeros((n_sku, T))
    shipped = np.zeros((n_sku, T))
    unmet = np.zeros((n_sku, T))
    orders = np.zeros((n_sku, T))

    for t in range(T):
        I += pipe[:, t % LT]
        pipe[:, t % LT] = 0.0        # ← 到货后必须清零，否则每 7 天重复到货
        ship = np.minimum(I, demand[:, t])
        I -= ship
        shipped[:, t] = ship
        unmet[:, t] = demand[:, t] - ship
        on_hand[:, t] = I
        if t % R == 0:
            IP = I + pipe.sum(axis=1)
            S = forecast[:, t] + ss
            qty = np.maximum(0, S - IP)
            pipe[:, t % LT] += qty
            orders[:, t] = qty

    warm = 28
    beta = shipped[:, warm:].sum() / max(demand[:, warm:].sum(), 1e-6)
    beta_sku = shipped[:, warm:].sum(1) / np.maximum(demand[:, warm:].sum(1), 1e-6)
    avg_inv = on_hand[:, warm:].mean(1)
    dos = avg_inv / np.maximum(demand[:, warm:].mean(1), 1e-6)
    dos_sales = avg_inv / np.maximum(shipped[:, warm:].mean(1), 1e-6)

    GM, HOLD_R = 0.25, 0.22
    unit_cost = price * (1 - GM)
    h_day = unit_cost * HOLD_R / 365
    hold_cost = float((on_hand[:, warm:] * h_day[:, None]).sum())
    loss_cost = float((unmet[:, warm:] * (price * GM)[:, None]).sum())

    return dict(
        sku_beta_median=float(np.median(beta_sku)),
        sys_beta=float(beta),
        avg_inv=float(avg_inv.sum()),
        avg_inv_value=float((avg_inv * price).sum()),
        dos_days=float(np.average(dos, weights=np.maximum(demand[:, warm:].sum(1), 1e-6))),
        dos_sales_days=float(np.average(dos_sales, weights=np.maximum(demand[:, warm:].sum(1), 1e-6))),
        stockout_days=int((unmet[:, warm:] > 0).sum()),
        n_orders=int((orders[:, warm:] > 0).sum()),
        hold_cost=hold_cost,
        loss_cost=loss_cost,
        total_cost=hold_cost + loss_cost,
        _shipped=shipped.sum(), _unmet=unmet.sum(), _demand=demand.sum(),
        _on_hand=on_hand if keep_daily else None,
        _shipped_arr=shipped if keep_daily else None,
        _unmet_arr=unmet if keep_daily else None,
    )


# 残差样本：39 个 14 天窗口（不含末尾越界的）
win = [t for t in range(0, N_DAYS - PROT + 1, R)]
errors, dem14 = {}, {}
for b in preds:
    e = np.zeros((n_sku, len(win)), dtype=np.float64)
    d = np.zeros(n_sku, dtype=np.float64)
    for j, t in enumerate(win):
        actual = demand[:, t:t + PROT].sum(axis=1)
        e[:, j] = actual - forecast[b][:, t]
        d += actual
    errors[b] = e
    dem14[b] = d / len(win)

# ---------------------------------------------------------------------------
# Step 7.3 标定循环
# ---------------------------------------------------------------------------
print("\n=== 标定到 SKU 级 fill rate 95% ===")
report, ss_final = {}, {}
for b in preds:
    ss = solve_ss(errors[b], dem14[b])
    for it in range(20):
        res = simulate(demand, forecast[b], ss)
        gap = TARGET_BETA - res["sku_beta_median"]
        if abs(gap) <= 0.003:
            break
        ss = np.maximum(ss * (1 + 0.8 * gap), 0)
    res["iterations"] = it + 1
    report[b] = res
    ss_final[b] = ss.copy()
    print(f"  {b:6s} sku_beta_median={res['sku_beta_median']:.4f} "
          f"sys_beta={res['sys_beta']:.4f} DOS={res['dos_days']:.1f}天 "
          f"库存={res['avg_inv']:,.0f} 件 迭代{it + 1}次")

# 需求守恒自检
for b in report:
    r = report[b]
    assert abs(r["_shipped"] + r["_unmet"] - r["_demand"]) < 1e-3, f"{b} 需求不守恒"
print("  需求守恒检查通过（Σshipped + Σunmet == Σdemand）")

# ---------------------------------------------------------------------------
# Step 7.4 成本最优服务水平
# ---------------------------------------------------------------------------
print("\n=== 服务水平扫描（以 lgbm 预测为基准）===")
LEVELS = [0.80, 0.85, 0.90, 0.92, 0.95, 0.97, 0.98, 0.99, 0.995, 0.998, 0.999]
rows = []
for lv in LEVELS:
    ss = solve_ss(errors["lgbm"], dem14["lgbm"], target=lv)
    r = simulate(demand, forecast["lgbm"], ss)
    rows.append(dict(level=lv, avg_inv=r["avg_inv"], avg_inv_value=r["avg_inv_value"],
                     dos_days=r["dos_days"],
                     hold_cost=r["hold_cost"], loss_cost=r["loss_cost"],
                     total_cost=r["total_cost"], sys_beta=r["sys_beta"]))
    print(f"  {lv:5.3f}  库存={r['avg_inv']:>9,.0f}  DOS={r['dos_days']:5.1f}天  "
          f"持有={r['hold_cost']:>10,.0f}  缺货={r['loss_cost']:>10,.0f}  "
          f"合计={r['total_cost']:>10,.0f}")
scan = pd.DataFrame(rows)
best = scan.loc[scan["total_cost"].idxmin()]
print(f"\n  成本最优服务水平 = {best['level']:.3f}"
      f"（总成本 {best['total_cost']:,.0f}）")

# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------
out = (pd.DataFrame(report).T
         .drop(columns=["_shipped", "_unmet", "_demand",
                        "_on_hand", "_shipped_arr", "_unmet_arr"], errors="ignore"))
out.index.name = "basis"
out.to_csv(SIM / "sim_result.csv", encoding="utf-8-sig")
scan.to_csv(SIM / "level_scan.csv", index=False, encoding="utf-8-sig")
scan.to_csv(SIM / "cost_curve.csv", index=False, encoding="utf-8-sig")   # 第 8 章用

# ---- 回写 sim_daily，供第 8 章周报视图 ----
print("\n回写 sim_daily（280 天 × 1,437 SKU）...")
res_d = simulate(demand, forecast["lgbm"], ss_final["lgbm"], keep_daily=True)
on_hand, shipped_d, unmet_d = res_d["_on_hand"], res_d["_shipped_arr"], res_d["_unmet_arr"]

# 仿真第 t 天对应的日期，以及 lgbm 对该日的 h 步预测
sim_dates, daily_fc = [], np.zeros((n_sku, N_DAYS), dtype=np.float32)
for k in range(N_FOLDS):
    s_idx = date_idx[date_of_d[FIRST_ORIGIN_D + 28 * k + 1]]
    sim_dates.extend(list(dates[s_idx: s_idx + 28]))
    daily_fc[:, k * 28:(k + 1) * 28] = preds["lgbm"][k][:, :28]

sim_daily = pd.DataFrame({
    "sim_date": np.repeat(pd.to_datetime(sim_dates), n_sku),
    "item_id": np.tile(items, N_DAYS),
    "units_demand": demand.T.ravel(),
    "units_shipped": shipped_d.T.ravel(),
    "abs_err": np.abs(daily_fc - demand).T.ravel(),
    "on_hand": on_hand.T.ravel(),
    "daily_demand": demand.T.ravel(),
    "stockout_flag": (unmet_d > 0).astype(int).T.ravel(),
})
tmp = SIM / "_sim_daily.csv"
sim_daily.to_csv(tmp, index=False, header=True, lineterminator="\n")

import pymysql
from config import DB
conn = pymysql.connect(host=DB["host"], port=DB["port"], user=DB["user"],
                       password=DB["password"], database=DB["database"],
                       charset="utf8mb4", local_infile=True, autocommit=True)
cur = conn.cursor()
cur.execute("DROP TABLE IF EXISTS sim_daily")
cur.execute("""
CREATE TABLE sim_daily (
  sim_date      DATE          NOT NULL,
  item_id       VARCHAR(20)   NOT NULL,
  units_demand  INT           NOT NULL,
  units_shipped INT           NOT NULL,
  abs_err       DOUBLE        NOT NULL,
  on_hand       DOUBLE        NOT NULL,
  daily_demand  INT           NOT NULL,
  stockout_flag TINYINT       NOT NULL,
  PRIMARY KEY (sim_date, item_id),
  KEY idx_item (item_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
""")
try:
    cur.execute(f"""
LOAD DATA LOCAL INFILE '{tmp.as_posix()}'
INTO TABLE sim_daily
CHARACTER SET utf8mb4
FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
LINES TERMINATED BY '\\n'
IGNORE 1 LINES
(sim_date, item_id, units_demand, units_shipped, abs_err,
 on_hand, daily_demand, stockout_flag)
""")
    conn.commit()
except pymysql.err.OperationalError as e:
    if e.args and e.args[0] == 3948:
        print("  local_infile 未开启，改用批量 INSERT（较慢，但不需要服务端开关）")
        from db import engine
        with engine().begin() as c:
            sim_daily.to_sql("sim_daily", c, if_exists="append",
                             index=False, chunksize=5000, method="multi")
    else:
        raise
cur.execute("SELECT COUNT(*) FROM sim_daily")
n_written = cur.fetchone()[0]
conn.close()
tmp.unlink(missing_ok=True)
print(f"  sim_daily 写入 {n_written:,} 行（应为 {N_DAYS * n_sku:,}）")

print(f"\n已写出：{SIM / 'sim_result.csv'}")
print(f"已写出：{SIM / 'level_scan.csv'} 和 cost_curve.csv")
