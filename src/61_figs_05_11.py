# -*- coding: utf-8 -*-
"""第 9 章 图 05~09、11（02/10 已有，01/03/04 已出）"""
import matplotlib
from config import CSV, FIG, MET, SIM, setup_cjk_font
setup_cjk_font()

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import db

# ---------------- 基础数据 ----------------
feat = pd.read_parquet(CSV / "features.parquet")
items = np.sort(feat["item_id"].unique())
dates = np.sort(feat["sale_date"].unique())
Y = (feat.pivot(index="item_id", columns="sale_date", values="y")
        .reindex(index=items, columns=dates).fillna(0).values.astype(np.float32))
n_sku = len(items)

abc = (db.q("SELECT item_id, abc FROM abc_class")
         .set_index("item_id")["abc"].reindex(items).values)

z = np.load(SIM / "preds_cache.npz")
preds = {b: [z[f"{b}_{k}"] for k in range(10)] for b in ("naive", "ma28", "lgbm")}

cal = db.q("SELECT sale_date, d FROM calendar ORDER BY sale_date")
cal["sale_date"] = pd.to_datetime(cal["sale_date"])
date_of_d = dict(zip(cal["d"], cal["sale_date"]))
date_idx = {d: i for i, d in enumerate(dates)}
FIRST_ORIGIN_D = 1633
starts = [date_idx[date_of_d[FIRST_ORIGIN_D + 28 * k + 1]] for k in range(10)]
truth_all = [Y[:, s:s + 28] for s in starts]

# ---------------- 05 分 ABC 的 WMAPE ----------------
print("图 05 ...")
rows = []
for b in preds:
    for cls in ("A", "B", "C"):
        m = abc == cls
        num = den = 0.0
        for k in range(10):
            t, p = truth_all[k][m], preds[b][k][m][:, :28]
            num += np.abs(t - p).sum()
            den += t.sum()
        rows.append(dict(model=b, abc=cls, wmape=num / max(den, 1)))
df05 = pd.DataFrame(rows).pivot(index="abc", columns="model", values="wmape")
print(df05.round(3).to_string())

hw_overall = float(pd.read_csv(MET / "model_compare.csv")
                     .set_index("model").loc["hw", "wmape_mean"])

fig, ax = plt.subplots(figsize=(9, 4.5))
x = np.arange(3)
w = 0.26
for i, b in enumerate(["lgbm", "ma28", "naive"]):
    ax.bar(x + (i - 1) * w, df05[b].values, w, label=b)
ax.axhline(hw_overall, ls="--", c="k", lw=1.2,
           label=f"hw（整体 {hw_overall:.3f}，未分档）")
ax.set_xticks(x); ax.set_xticklabels(["A 类", "B 类", "C 类"])
ax.set_ylabel("WMAPE（越低越好）")
ax.set_title("四个模型分 ABC 的预测误差")
ax.legend(fontsize=9)
fig.tight_layout(); fig.savefig(FIG / "05_四模型分ABC误差.png", dpi=150)
plt.close(fig)

# ---------------- 06 10 折稳定性 ----------------
print("图 06 ...")
met = pd.read_csv(MET / "metrics_fold.csv")
fig, ax = plt.subplots(figsize=(9, 4.5))
for b in ["lgbm", "hw", "ma28", "naive"]:
    d = met[met["model"] == b].sort_values("fold")
    ax.plot(d["fold"], d["wmape"], "o-", label=b)
ax.set_xlabel("折（第 k 个时间切点）")
ax.set_ylabel("WMAPE")
ax.set_title("10 折回测稳定性")
ax.set_xticks(range(1, 11))
ax.grid(alpha=.3); ax.legend()
fig.tight_layout(); fig.savefig(FIG / "06_十折稳定性.png", dpi=150)
plt.close(fig)

# ---------------- 07 泄漏对照 ----------------
print("图 07 ...")
# 作弊版：用「当天前后共 10 天的实际均值」当预测（含未来 7 天）
cheat = np.zeros((n_sku, 28), dtype=np.float32)
num = den = 0.0
for k in range(10):
    s = starts[k]
    for j in range(28):
        lo, hi = max(0, s + j - 3), min(len(dates), s + j + 8)
        cheat[:, j] = Y[:, lo:hi].mean(axis=1)
    t = truth_all[k]
    num += np.abs(t - cheat).sum(); den += t.sum()
w_cheat = num / den

w_lgbm_overall = float(pd.read_csv(MET / "model_compare.csv")
                         .set_index("model").loc["lgbm", "wmape_mean"])

fig, ax = plt.subplots(figsize=(6, 4))
ax.bar(["作弊版\n(含未来7天)", "正确版\nlgbm"], [w_cheat, w_lgbm_overall],
       color=["#c53030", "#2b6cb0"])
for i, v in enumerate([w_cheat, w_lgbm_overall]):
    ax.text(i, v + 0.01, f"{v:.3f}", ha="center")
ax.set_ylabel("WMAPE")
ax.set_title("标签泄漏对照：用了未来数据，分数虚高")
fig.tight_layout(); fig.savefig(FIG / "07_泄漏对照.png", dpi=150)
plt.close(fig)
print(f"  作弊版 WMAPE={w_cheat:.4f}  正确版={w_lgbm_overall:.4f}")

# ---------------- 08 预测 vs 实际 ----------------
print("图 08 ...")
P = preds["lgbm"][9]
fig, ax = plt.subplots(figsize=(10, 4.5))
days = range(1, 43)
ax.plot(days, P.sum(axis=0), "-", label="预测（全店合计）")
ax.plot(days, Y[:, starts[9]:starts[9] + 42].sum(axis=0), "-", label="实际")
ax.axvline(28, ls=":", c="gray")
ax.text(28.3, ax.get_ylim()[1] * .95, "考核边界 28 天", fontsize=9, color="gray")
ax.set_xlabel("预测步长（天）"); ax.set_ylabel("日销量（件）")
ax.set_title("第 10 折：LightGBM 预测 vs 实际（全店合计）")
ax.legend(); ax.grid(alpha=.3)
fig.tight_layout(); fig.savefig(FIG / "08_预测vs实际.png", dpi=150)
plt.close(fig)

# ---------------- 09 残差分布 ----------------
print("图 09 ...")
res = np.concatenate([(preds["lgbm"][k][:, :28] - truth_all[k]).ravel()
                      for k in range(10)])
fig, ax = plt.subplots(figsize=(8, 4.5))
ax.hist(np.clip(res, -20, 20), bins=80, color="#2b6cb0", edgecolor="white")
ax.axvline(0, ls="--", c="r")
ax.set_xlabel("残差（预测−实际，截断到 ±20）")
ax.set_ylabel("SKU-日 数")
ax.set_title(f"LightGBM 残差分布（均值 {res.mean():+.2f}，中位数 {np.median(res):+.2f}）")
fig.tight_layout(); fig.savefig(FIG / "09_残差分布.png", dpi=150)
plt.close(fig)

# ---------------- 11 三基准库存对比 ----------------
print("图 11 ...")
sim = pd.read_csv(SIM / "sim_result.csv", index_col=0)
fig, axes = plt.subplots(1, 2, figsize=(11, 4))
axes[0].bar(sim.index, sim["avg_inv_value"], color=["#a0aec0", "#4a90c2", "#2b6cb0"])
axes[0].set_ylabel("平均库存金额（美元）")
axes[0].set_title("等服务水平（95%）下的库存")
axes[1].bar(sim.index, sim["total_cost"], color=["#e2a0a0", "#c97070", "#c53030"])
axes[1].set_ylabel("总成本（美元）")
axes[1].set_title("总成本对比")
for ax in axes:
    for i, v in enumerate(ax.patches):
        ax.text(v.get_x() + v.get_width() / 2, v.get_height() * 1.01,
                f"{v.get_height():,.0f}", ha="center", fontsize=9)
fig.suptitle("同一 95% fill rate 下的三种预测依据对比")
fig.tight_layout(); fig.savefig(FIG / "11_三基准库存对比.png", dpi=150)
plt.close(fig)

print("\n已输出 05 / 06 / 07 / 08 / 09 / 11 到", FIG)