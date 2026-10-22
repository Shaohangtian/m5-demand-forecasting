# -*- coding: utf-8 -*-
"""第 9 章 图 01~04：季节性 / 零销量分布 / 价格与促销"""
import matplotlib
from config import CSV, FIG, setup_cjk_font
setup_cjk_font()

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import db

feat = pd.read_parquet(CSV / "features.parquet")

# ---------------- 01 周内 / 年度季节性 ----------------
print("图 01 ...")
wd = db.q("""SELECT wday, AVG(units_sold) AS avg_units
             FROM v_sales_enriched GROUP BY wday ORDER BY wday""")
mo = db.q("""SELECT `month`, AVG(units_sold) AS avg_units
             FROM v_sales_enriched GROUP BY `month` ORDER BY `month`""")

fig, axes = plt.subplots(1, 2, figsize=(11, 4))
axes[0].bar(wd["wday"], wd["avg_units"], color="#2b6cb0")
axes[0].set_xlabel("星期几（1=周六，7=周五）")
axes[0].set_ylabel("平均日销量")
axes[0].set_title("周内季节性")
axes[1].plot(mo["month"], mo["avg_units"], "o-", color="#c53030")
axes[1].set_xlabel("月份")
axes[1].set_ylabel("平均日销量")
axes[1].set_title("年度季节性")
fig.suptitle("FOODS 品类日销量季节性（CA_1 店）")
fig.tight_layout()
fig.savefig(FIG / "01_季节性.png", dpi=150)
plt.close(fig)

# ---------------- 03 零销量占比分布 ----------------
print("图 03 ...")
zero_rate = feat.groupby("item_id")["y"].apply(lambda s: float((s == 0).mean())) * 100

fig, ax = plt.subplots(figsize=(8, 4.5))
ax.hist(zero_rate, bins=40, color="#2b6cb0", edgecolor="white")
ax.axvline(zero_rate.mean(), ls="--", c="r",
           label=f"均值 {zero_rate.mean():.1f}%")
ax.set_xlabel("零销量天数占比 (%)")
ax.set_ylabel("SKU 数")
ax.set_title(f"{len(zero_rate):,} 个 SKU 的零销量占比分布")
ax.legend()
fig.tight_layout()
fig.savefig(FIG / "03_零销量分布.png", dpi=150)
plt.close(fig)

# ---------------- 04 价格与促销 ----------------
print("图 04 ...")
bins = [0, 1, 2, 3, 4, 5, 7, 10, 20]
price_bin = pd.cut(feat["sell_price"], bins=bins)
g = feat.groupby(price_bin, observed=True)["y"].mean()

promo = (feat["price_vs_avg28"] < 0.95).fillna(False)
non_promo = (feat["price_vs_avg28"] >= 0.95).fillna(False)

fig, axes = plt.subplots(1, 2, figsize=(11, 4))
axes[0].plot(range(len(g)), g.values, "o-", color="#2b6cb0")
axes[0].set_xticks(range(len(g)))
axes[0].set_xticklabels([str(i) for i in g.index], rotation=30)
axes[0].set_xlabel("售价区间（美元）")
axes[0].set_ylabel("平均日销量")
axes[0].set_title("价格 vs 销量")

bars = [feat.loc[non_promo, "y"].mean(), feat.loc[promo, "y"].mean()]
axes[1].bar(["价格持平/上涨", "降价(低于28日均价)"], bars,
            color=["#a0aec0", "#c53030"])
for i, v in enumerate(bars):
    axes[1].text(i, v * 1.02, f"{v:.2f}", ha="center")
axes[1].set_ylabel("平均日销量")
axes[1].set_title("降价日的销量提升")
fig.tight_layout()
fig.savefig(FIG / "04_价格与促销.png", dpi=150)
plt.close(fig)

print("已输出 01 / 03 / 04 到", FIG)
