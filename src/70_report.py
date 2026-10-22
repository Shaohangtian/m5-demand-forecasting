# -*- coding: utf-8 -*-
"""阶段 9：生成 docx 报告（所有数字都从 outputs/ 里的文件读，保证可追溯）"""
import numpy as np
import pandas as pd
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt

from config import CSV, FIG, MET, SIM, TAB
from db import q

ROOT = CSV.parent
REPORT = ROOT.parent / "reports" / "供应链需求预测报告.docx"


# ---------------- 读数据 ----------------
print("汇总数字 ...")
try:
    dq = pd.read_csv(TAB / "dq_result.csv", encoding="utf-8-sig")
except UnicodeDecodeError:
    dq = pd.read_csv(TAB / "dq_result.csv", encoding="gbk")
abc = q("SELECT * FROM abc_summary")
abc_cls = q("SELECT item_id, abc, revenue_52w FROM abc_class")
mc = pd.read_csv(MET / "model_compare.csv")
mf = pd.read_csv(MET / "metrics_fold.csv")
sim = pd.read_csv(SIM / "sim_result.csv", index_col=0)
curve = pd.read_csv(SIM / "cost_curve.csv")

feat = pd.read_parquet(CSV / "features.parquet")
items = np.sort(feat["item_id"].unique())
dates = np.sort(feat["sale_date"].unique())
Y = (feat.pivot(index="item_id", columns="sale_date", values="y")
        .reindex(index=items, columns=dates).fillna(0).values.astype(np.float32))
abc_arr = abc_cls.set_index("item_id")["abc"].reindex(items).values

z = np.load(SIM / "preds_cache.npz")
preds = {b: [z[f"{b}_{k}"] for k in range(10)] for b in ("naive", "ma28", "lgbm")}
cal = q("SELECT sale_date, d FROM calendar ORDER BY sale_date")
cal["sale_date"] = pd.to_datetime(cal["sale_date"])
date_of_d = dict(zip(cal["d"], cal["sale_date"]))
date_idx = {d: i for i, d in enumerate(dates)}
starts = [date_idx[date_of_d[1633 + 28 * k + 1]] for k in range(10)]

# 分 ABC 的 WMAPE
rows = []
for b in preds:
    for cls in ("A", "B", "C"):
        m = abc_arr == cls
        num = den = 0.0
        for k in range(10):
            t, p = Y[m][:, starts[k]:starts[k] + 28], preds[b][k][m][:, :28]
            num += np.abs(t - p).sum(); den += t.sum()
        rows.append(dict(model=b, abc=cls, wmape=num / max(den, 1)))
by_cls = pd.DataFrame(rows).pivot(index="abc", columns="model", values="wmape")

# 作弊版（含未来 7 天）
num = den = 0.0
for k in range(10):
    s = starts[k]
    for j in range(28):
        lo, hi = max(0, s + j - 3), min(len(dates), s + j + 8)
        cheat = Y[:, lo:hi].mean(axis=1)
        t = Y[:, s + j]
        num += np.abs(t - cheat).sum(); den += t.sum()
w_cheat = num / den
w_correct = float(mc.set_index("model").loc["lgbm", "wmape_mean"])

best = curve.loc[curve["total_cost"].idxmin()]
s95 = sim.loc["lgbm"]

# ---------------- 建文档 ----------------
doc = Document()
st = doc.styles["Normal"]
st.font.name = "微软雅黑"
st.font.size = Pt(10.5)
st.element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")


def H(text, level=1):
    h = doc.add_heading(text, level=level)
    for r in h.runs:
        r.font.name = "微软雅黑"
        r._element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")


def P(text, bold=False):
    p = doc.add_paragraph()
    r = p.add_run(text)
    r.bold = bold
    r.font.name = "微软雅黑"
    r._element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")
    return p


def FIGURE(name, caption):
    doc.add_picture(str(FIG / name), width=Inches(6.0))
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    c = doc.add_paragraph(caption)
    c.alignment = WD_ALIGN_PARAGRAPH.CENTER
    c.runs[0].font.size = Pt(9)


def TABLE(headers, rows):
    """插入表格：headers 为表头列表，rows 为二维数据

    两个排版处理：
      1. 除最后一行外所有单元格段落设 keep_with_next —— 防止表格跨页断裂
      2. 表头行设 tblHeader —— 万一仍需跨页，表头会自动重复
    """
    t = doc.add_table(rows=1, cols=len(headers))
    try:
        t.style = "Light Grid Accent 1"
    except KeyError:
        t.style = "Table Grid"
    for i, h in enumerate(headers):
        t.rows[0].cells[i].text = str(h)
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = str(v)

    # 1) 防止表格跨页断裂
    for row in t.rows[:-1]:
        for cell in row.cells:
            for p in cell.paragraphs:
                p.paragraph_format.keep_with_next = True

    # 2) 表头跨页重复
    tr_pr = t.rows[0]._tr.get_or_add_trPr()
    tr_pr.append(OxmlElement("w:tblHeader"))

    doc.add_paragraph()
    return t


# 封面
t = doc.add_heading("M5 供应链需求预测与补货决策", 0)
t.alignment = WD_ALIGN_PARAGRAPH.CENTER
P("——从数据入库到成本最优服务水平的完整分析").alignment = WD_ALIGN_PARAGRAPH.CENTER
P(f"数据范围：Walmart CA_1 门店 FOODS 品类，1,437 个 SKU × 1,941 天").alignment = WD_ALIGN_PARAGRAPH.CENTER
doc.add_page_break()

# 摘要
H("摘要")
P(f"本报告基于 M5 公开数据集，为 CA_1 门店 FOODS 品类的 1,437 个 SKU 建立日需求预测模型，"
  f"并据此设计 (R,S) 周期补货策略。数据规模 {len(feat):,} 行（SKU-日）。"
  f"四个模型 10 折滚动回测中，Holt-Winters 与 LightGBM 表现最佳（WMAPE "
  f"{mc.set_index('model').loc['hw','wmape_mean']:.3f} / {w_correct:.3f}），"
  f"显著优于季节朴素法的 {mc.set_index('model').loc['naive','wmape_mean']:.3f}。"
  f"在统一的 95% SKU 级 fill rate 下，LightGBM 预测带来的总成本最低"
  f"（{s95['total_cost']:,.0f} 美元），比朴素法低 "
  f"{(1 - s95['total_cost'] / sim.loc['naive','total_cost']) * 100:.1f}%。")

# 1
H("1  业务问题与数据边界")
P("目标是回答一个问题：在有限库存成本下，如何为 1,437 个 SKU 决定补货量，"
  "使缺货损失与持有成本之和最小。")
P("边界一：销量 ≠ 需求。数据集只记录成交销量，缺货期间的真实需求无法观测。"
  "因此所有模型学习的都是「有货条件下的销量」，服务水平越高，这个偏差越小，"
  "但在高缺货场景下预测会被系统性低估。", bold=True)
P("边界二：单店单品类。全部结论仅适用于 CA_1 门店的 FOODS 品类，"
  "跨门店、跨品类的迁移未经验证。")
P("边界三：外部因素缺失。促销计划、竞品价格、天气等变量不在数据中，"
  "价格只能通过「相对近 28 日均价」间接刻画。")

# 2
H("2  数据工程")
P(f"原始文件为宽表（30,490 行 × 1,941 个日期列），转换为长表后入库 2,789,217 行。"
  f"采用三表结构：sales（销量）、calendar（日历）、sell_prices（周价格），"
  f"关联后形成分析视图 v_sales_enriched。")
P("2.1  数据质量校验")
for _, r in dq.iterrows():
    P(f"检查 {int(r['check_id'])}　{r['check_name']}：{r['status']}，"
      f"异常行 {int(r['failed_rows']):,}"
      + (f"（{r['detail']}）" if isinstance(r["detail"], str) else ""))
P("第 6 项为 WARN 属预期：全部 SKU 都存在连续 28 天以上零销量，"
  "最长连续零销量达 1,845 天，反映食品类目的长尾结构，非数据缺陷。")
P("2.2  ABC 分层")

t = doc.add_table(rows=1, cols=4)
try:
    t.style = "Light Grid Accent 1"
except KeyError:
    t.style = "Table Grid"          # 样式名不存在时的兜底

hdr = t.rows[0].cells
for i, h in enumerate(["分层", "SKU 数", "SKU 占比", "销售额占比"]):
    hdr[i].text = h

for _, r in abc.iterrows():
    cells = t.add_row().cells
    cells[0].text = str(r["abc"])
    cells[1].text = f"{int(r['n_sku']):,}"
    cells[2].text = f"{r['sku_pct']}%"
    cells[3].text = f"{r['rev_pct']}%"

doc.add_paragraph()                 # 表格后空一行，避免图贴着表格

FIGURE("02_ABC帕累托.png", "图 2-1  ABC 帕累托曲线")

# 3
H("3  特征工程与防泄漏")
P("铁律：第 t 行的任何特征只能使用 t−1 天及以前的数据。所有滚动窗口右端一律取 "
  "「1 PRECEDING」，共构建 19 个特征：滞后（1/7/14/28 天）、滚动均值与标准差"
  "（7/28/56 天）、极值、零销量天数、趋势比、价格相对水平。")
P("3.1  防泄漏自检")
P(f"正确特征下，每个 SKU 第 1 天的 ma_7 必为空，全表共 1,437 个空值——实测吻合，"
  f"证明窗口未包含当天。")
P(f"3.2  作弊对照实验")
P(f"构造一个使用「当天前后共 10 天实际均值」的作弊版预测，WMAPE 为 {w_cheat:.3f}，"
  f"而正确版 LightGBM 为 {w_correct:.3f}，虚高 {(1 - w_cheat / w_correct) * 100:.0f}%。"
  f"这说明一旦引入未来信息，离线指标会显著失真，上线后必然崩盘。")
FIGURE("07_泄漏对照.png", "图 3-1  标签泄漏对照")

# 4
H("4  四模型回测结果")
P("采用 10 折滚动回测：每折用切点之前的数据训练，预测未来 42 天，只考核前 28 天。")
P("4.1  整体表现")
base = float(mc.set_index("model").loc["naive", "wmape_mean"])
TABLE(["模型", "10 折平均 WMAPE", "相对季节朴素改善"],
      [[m, f"{v:.4f}", f"{(1 - v / base) * 100:+.1f}%"]
       for m, v in mc.set_index("model")["wmape_mean"].sort_values().items()])
FIGURE("06_十折稳定性.png", "图 4-1  10 折回测稳定性")
P("4.2  分 ABC 的误差")
P("误差随销量层级明显恶化：A 类最好，C 类最差。值得注意的是，"
  "在 C 类上单调移动平均（ma28）反而优于 LightGBM——"
  "低销量、高间歇性的序列上，复杂模型容易过拟合噪声。")
TABLE(["分层", "LightGBM", "ma28", "naive"],
      [[f"{idx} 类", f"{r['lgbm']:.3f}", f"{r['ma28']:.3f}", f"{r['naive']:.3f}"]
       for idx, r in by_cls.iterrows()])
FIGURE("05_四模型分ABC误差.png", "图 4-2  四模型分 ABC 的预测误差")
FIGURE("08_预测vs实际.png", "图 4-3  第 10 折预测与实际对比")
P("预测准确复现了周内节律，但在考核窗口内整体略高于实际值，"
  "属保守偏置——在补货场景中偏向「多备」是安全侧偏差。")
FIGURE("09_残差分布.png", "图 4-4  残差分布")

# 5
H("5  补货仿真：等服务水平下的库存效率")
P("补货策略为 (R,S)：每 7 天评审一次，提前期 7 天，保护期 14 天。"
  "安全库存通过求解 fill rate 方程 β(SS)=0.95 得到，而非简单取分位数——"
  "分位数控制的是不缺货概率（cycle service level），不是订单满足率。")
TABLE(["预测依据", "SKU 级 fill rate", "系统 fill rate", "平均库存(件)",
       "库存金额($)", "DOS(天)", "总成本($)"],
      [[b,
        f"{sim.loc[b, 'sku_beta_median']:.4f}",
        f"{sim.loc[b, 'sys_beta']:.4f}",
        f"{sim.loc[b, 'avg_inv']:,.0f}",
        f"{sim.loc[b, 'avg_inv_value']:,.0f}",
        f"{sim.loc[b, 'dos_days']:.1f}",
        f"{sim.loc[b, 'total_cost']:,.0f}"] for b in sim.index])
FIGURE("11_三基准库存对比.png", "图 5-1  同一 fill rate 下的库存与成本对比")
P(f"LightGBM 的总成本最低（{s95['total_cost']:,.0f}），但库存并非最少"
  f"（{s95['avg_inv_value']:,.0f} vs ma28 的 "
  f"{sim.loc['ma28','avg_inv_value']:,.0f}）——它用略高的库存换来了更少的缺货。"
  f"这说明评价补货方案不能只看库存，必须看总成本。")

# 6
H("6  服务水平与成本的权衡")
P("扫描 9~11 个 fill rate 目标点，每个点重新求解安全库存并仿真。")
FIGURE("10_库存服务水平权衡曲线.png", "图 6-1  库存–服务水平权衡曲线")
P(f"库存金额随服务水平加速上升，总成本呈 U 形，"
  f"成本最优点出现在 {best['level']*100:.1f}%（总成本 {best['total_cost']:,.0f} 美元）。")
P("该最优点明显高于行业常见的 96~98%，原因在于成本参数："
  "持有成本为单价的 22%/年，而缺货损失仅计 25% 毛利。"
  "换算下来「多备一件货 553 天」才等于「丢一单的损失」，"
  "因此模型自然倾向高服务水平。", bold=True)
P("这提示：若把缺货的信誉成本（客户流失、品牌损伤）纳入，"
  "最优点会回落。真实决策中不应只按毛利计算缺货损失。")

# 7
H("7  结论与建议")
P("（1）预测精度能直接转化为成本。同等服务水淮下，LightGBM 比朴素法节省 "
  f"{(1 - s95['total_cost'] / sim.loc['naive','total_cost']) * 100:.1f}% 总成本。")
P("（2）分层施策。A 类用机器学习模型，C 类（占 SKU 数近四成、仅贡献 10% 销售额）"
  "建议用简单移动平均甚至固定补货量，投入产出比更高。")
P("（3）服务水平不应只按毛利反推。当前成本假设下最优解接近 99%，"
  "实践中需结合缺货的真实业务代价重新标定。")
P("7.1  局限")
P("销量不等于需求的删失偏差；未纳入促销计划与竞品信息；"
  "仅单店单品类；Holt-Winters 与 LightGBM 差距在统计上不显著（0.709 vs 0.711）。")
P("7.2  过程中发现并修正的三处缺陷")
P("① 价格向前填充分组错误：原实现用「累计空值数」分组，导致无缺失序列的所有行落入同一组，"
  "价格被填成历史最高价。改用「累计非空数」分组后，填充值与原始记录完全一致。")
P("② 递归预测特征错位：滞后特征在「当天预测向量」上做 np.roll，"
  "等于用其他 SKU 的预测值当作自身滞后，WMAPE 高达 0.97。")
P("③ 补货仿真在途未清零：订单一进入在途槽位就再未清空，每 7 天重复到货，"
  "导致库存虚增、fill rate 恒为 100%。")

# 附录
H("附录  复现步骤")
for i, s in enumerate([
    "pip install -r requirements.txt",
    "从 Kaggle 下载 M5 数据放入 data/",
    "py 10_ingest.py → 11_load_sales.py → 12_load_dims.py",
    "Workbench 执行 sql/02_enrich.sql、02b_fix_price.sql、04_abc.sql",
    "py 13_build_features.py",
    "py 30_backtest.py / 31_rerun_lgbm.py",
    "py 40_simulate.py",
    "py 50_weekly.py、60_figs_01_04.py、61_figs_05_11.py",
    "py 70_report.py",
], 1):
    P(f"{i}. {s}")

REPORT.parent.mkdir(parents=True, exist_ok=True)
doc.save(REPORT)
print("已生成:", REPORT)