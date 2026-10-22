# -*- coding: utf-8 -*-
"""阶段 8：周报视图 + 库存–服务水平权衡曲线

  1. 执行 sql/08_weekly.sql 建视图 vw_weekly_report
  2. 导出 outputs/tables/weekly_report.csv
  3. 画 outputs/figures/10_库存服务水平权衡曲线.png
"""
import time

import matplotlib
from config import FIG, SIM, TAB, setup_cjk_font
setup_cjk_font()

import matplotlib.pyplot as plt
import pandas as pd

import db

t0 = time.time()

# ---------- 1. 建视图 ----------
print("1/3 建周报视图 ...")
db.run_script("../sql/08_weekly.sql")
chk = db.q("SELECT COUNT(*) AS n FROM vw_weekly_report")
print(f"    vw_weekly_report 返回 {int(chk['n'][0]):,} 行（ABC×周）")

weekly = db.q("SELECT * FROM vw_weekly_report")
weekly.to_csv(TAB / "weekly_report.csv", index=False, encoding="utf-8-sig")
print(f"    已写出 {TAB / 'weekly_report.csv'}")

print("\n    按 ABC 汇总（全期）：")
summary = db.q("""
    SELECT a.abc,
           SUM(s.units_demand)  AS 需求,
           SUM(s.units_shipped) AS 发出,
           ROUND(SUM(s.units_shipped) / SUM(s.units_demand), 4) AS fill_rate,
           ROUND(SUM(s.abs_err) / SUM(s.units_demand), 4)       AS wmape,
           ROUND(AVG(s.on_hand), 0)                             AS 平均在库
    FROM sim_daily s JOIN abc_class a ON a.item_id = s.item_id
    GROUP BY a.abc ORDER BY a.abc
""")
print(summary.to_string(index=False))

# ---------- 2. 权衡曲线 ----------
print("\n2/3 画权衡曲线 ...")
df = pd.read_csv(SIM / "cost_curve.csv")
best = df.loc[df["total_cost"].idxmin()]

fig, ax1 = plt.subplots(figsize=(9, 5))
ax1.plot(df["level"] * 100, df["avg_inv_value"], "o-", color="#2b6cb0",
         label="平均库存金额")
ax1.set_xlabel("fill rate 目标 (%)")
ax1.set_ylabel("平均库存金额（美元）", color="#2b6cb0")
ax1.tick_params(axis="y", labelcolor="#2b6cb0")
ax1.grid(alpha=.3)

ax2 = ax1.twinx()
ax2.plot(df["level"] * 100, df["total_cost"], "s--", color="#c53030",
         label="总成本")
ax2.set_ylabel("总成本（美元）", color="#c53030")
ax2.tick_params(axis="y", labelcolor="#c53030")

ax1.axvline(best["level"] * 100, ls=":", c="gray")
ax1.annotate(f"成本最优 {best['level'] * 100:.1f}%",
             xy=(best["level"] * 100, best["avg_inv_value"]),
             xytext=(-90, 30), textcoords="offset points",
             arrowprops=dict(arrowstyle="->", color="gray"))
ax1.set_title("库存–服务水平权衡曲线")

lines = ax1.get_lines()[:1] + ax2.get_lines()[:1]
ax1.legend(lines, [ln.get_label() for ln in lines], loc="upper left")

fig.tight_layout()
out_fig = FIG / "10_库存服务水平权衡曲线.png"
fig.savefig(out_fig, dpi=150)
print(f"    已写出 {out_fig}")

# ---------- 3. 检查点 I ----------
print("\n3/3 检查点 I")
mono = bool((df["avg_inv_value"].diff().dropna() > 0).all())
print(f"    库存随服务水平单调递增: {'✅' if mono else '❌'}")
print(f"    成本曲线有最低点: {'✅' if 0 < df['total_cost'].idxmin() < len(df) - 1 else '⚠️ 在边界'}"
      f"（最优点 {best['level'] * 100:.1f}%）")
print(f"    视图可直接查询: ✅（{int(chk['n'][0])} 行）")

print(f"\n完成，总耗时 {time.time() - t0:.1f}s")
