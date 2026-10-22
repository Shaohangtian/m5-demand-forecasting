# M5 供应链需求预测与补货决策

基于 Walmart [M5 公开数据集](https://www.kaggle.com/competitions/m5-forecasting-accuracy)，
为 CA_1 门店 FOODS 品类的 **1,437 个 SKU** 建立日需求预测模型，并据此设计 (R,S)
周期补货策略、求解成本最优服务水平。

完整链路：**入库 → 质量校验 → ABC 分层 → 特征工程 → 四模型回测 → 补货仿真 →
服务水平权衡 → 图表与报告**。

---

## 成果概览

| 指标 | 数值 |
|---|---|
| 数据规模 | 2,789,217 行（1,437 SKU × 1,941 天） |
| 最佳模型 WMAPE | **0.709**（Holt-Winters）／ 0.711（LightGBM） |
| 基线（季节朴素） | 0.846 |
| 95% 服务水平下总成本 | LightGBM **31,248 美元**，比朴素法低 3.7% |
| 成本最优服务水平 | 99.8%（总成本 18,564 美元） |

### 三个核心发现

1. **误差随销量层级翻倍**：A 类 WMAPE 0.57 → C 类 1.19。且在 C 类上简单移动平均
   （1.155）反而优于 LightGBM（1.192）——低销量、高间歇性的序列上，复杂模型容易过拟合噪声。
2. **预测精度可量化为成本**：同等 95% fill rate 下，LightGBM 比朴素法节省 3.7% 总成本，
   但库存并非最少（101,384 vs 97,224 美元）——它用略高的库存换来了更少的缺货。
3. **成本最优服务水平远高于行业经验**：在「缺货仅计 25% 毛利、持有成本 22%/年」的假设下，
   最优点达 99.8%——多备一件货 553 天才等于丢一单的损失。这说明真实决策必须计入
   缺货的信誉成本。

完整分析见 [`reports/供应链需求预测报告.docx`](reports/)。

---

## 数据来源

需自行从 Kaggle 下载后放入 `data/`（本仓库不分发数据）：

```
data/
├── calendar.csv
├── sales_train_evaluation.csv
└── sell_prices.csv
```

`sales_train_validation.csv` 与 `sample_submission.csv` 不需要：
前者是 evaluation 的子集（1,913 天 ⊂ 1,941 天），两者都导会让销量翻倍。

---

## 目录结构

```
├── data/                        原始 CSV（.gitignore，需自行下载）
├── sql/
│   ├── 02_enrich.sql            价格向前填充 + 分析视图（注意用 02b 修正版）
│   ├── 02b_fix_price.sql        修正价格填充分组（见「已修正的缺陷」#1）
│   ├── 03_dq_checks.sql         6 项数据质量校验
│   ├── 04_abc.sql               ABC 分层
│   ├── 05_features.sql          MySQL 窗口函数版特征（实测过慢，未采用）
│   ├── 08_weekly.sql            周报视图
│   └── legacy/                  早期 5 表全量支线的 SQL
├── src/
│   ├── config.py                路径与数据库连接
│   ├── db.py                    连接封装（q / run / run_script）
│   ├── 10_ingest.py             宽表转长表 → sales_long.csv
│   ├── 11_load_sales.py         LOAD DATA 灌入 sales
│   ├── 12_load_dims.py          灌入 calendar 与 sell_prices
│   ├── 13_build_features.py     19 个特征（pandas 实现）
│   ├── 20_abc_plot.py           ABC 帕累托图
│   ├── 30_backtest.py           四模型 × 10 折回测
│   ├── 31_rerun_lgbm.py         修正递归特征后单独重跑 LightGBM
│   ├── 40_simulate.py           (R,S) 补货仿真 + 服务水平扫描
│   ├── 50_weekly.py             周报视图导出 + 权衡曲线
│   ├── 60_figs_01_04.py         图 01 / 03 / 04
│   ├── 61_figs_05_11.py         图 05~09、11
│   ├── 70_report.py             生成 docx 报告
│   └── 00_profile.py 等 4 个     早期 5 表支线脚本（与主线无关）
├── outputs/
│   ├── csv/                     sales_long.csv、features.parquet（生成物，不入库）
│   ├── figures/                 11 张图
│   ├── metrics/                 metrics_fold.csv、model_compare.csv
│   ├── tables/                  dq_result.csv、weekly_report.csv
│   ├── sim/                     sim_result.csv、cost_curve.csv、level_scan.csv
│   └── logs/                    运行日志（空目录不入库）
├── reports/                     供应链需求预测报告.docx
├── docs/                        零基础执行手册.md（分步教程）
├── .gitignore
├── .gitattributes
├── requirements.txt
└── README.md
```

---

## 环境准备

Python 3.13，依赖见 `requirements.txt`：

```bash
python -m pip install -r requirements.txt
```

MySQL 8.0 需要先建库和专用账号：

```sql
CREATE DATABASE m5_foods CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE USER 'm5user'@'localhost' IDENTIFIED BY 'M5pass_2026';
GRANT ALL PRIVILEGES ON m5_foods.* TO 'm5user'@'localhost';
FLUSH PRIVILEGES;
```

若使用 `LOAD DATA LOCAL INFILE`，服务端需开启（重启后失效）：

```sql
SET GLOBAL local_infile = 1;
```

把数据库密码写进 `src/config.py` 的 `DB` 字典。

### 建表 DDL

```sql
USE m5_foods;

CREATE TABLE IF NOT EXISTS sales (
  store_id    CHAR(4)           NOT NULL,
  item_id     VARCHAR(20)       NOT NULL,
  dept_id     VARCHAR(12)       NOT NULL,
  cat_id      VARCHAR(12)       NOT NULL,
  state_id    CHAR(2)           NOT NULL,
  sale_date   DATE              NOT NULL,
  units_sold  SMALLINT UNSIGNED NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS calendar (
  sale_date     DATE             NOT NULL PRIMARY KEY,
  d             SMALLINT UNSIGNED NOT NULL UNIQUE,
  wm_yr_wk      INT UNSIGNED     NOT NULL,
  weekday       VARCHAR(9)       NULL,
  wday          TINYINT UNSIGNED NULL,
  month         TINYINT UNSIGNED NULL,
  year          SMALLINT UNSIGNED NULL,
  day           TINYINT UNSIGNED NULL,
  event_name_1  VARCHAR(32)      NULL,
  event_type_1  VARCHAR(16)      NULL,
  event_name_2  VARCHAR(32)      NULL,
  event_type_2  VARCHAR(16)      NULL,
  snap_CA       TINYINT UNSIGNED NULL,
  snap_TX       TINYINT UNSIGNED NULL,
  snap_WI       TINYINT UNSIGNED NULL,
  KEY idx_week (wm_yr_wk)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sell_prices (
  store_id   CHAR(4)        NOT NULL,
  item_id    VARCHAR(20)    NOT NULL,
  wm_yr_wk   INT UNSIGNED   NOT NULL,
  sell_price DECIMAL(8,2)   NOT NULL,
  PRIMARY KEY (store_id, item_id, wm_yr_wk)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

`sales` 故意不建主键与索引——先灌 279 万行，载完再建，比边载边建快 3~5 倍。

---

## 复现步骤

```bash
cd src

# ---------- 1. 入库（约 5 分钟）----------
py 10_ingest.py          # 宽表转长表 → outputs/csv/sales_long.csv（2,789,217 行）
py 11_load_sales.py      # LOAD DATA 灌入 sales，载完建主键与索引
py 12_load_dims.py       # 灌入 calendar（1,941 行）与 sell_prices（约 33 万行）

# ---------- 2. 加工（在 MySQL 客户端执行）----------
#   sql/02_enrich.sql      → price_final + v_sales_enriched
#   sql/02b_fix_price.sql  → 修正价格填充（务必执行，覆盖上一步的 price_final）
#   sql/03_dq_checks.sql   → 6 项质检 → dq_result
#   sql/04_abc.sql         → abc_class / abc_summary

# ---------- 3. 特征工程（约 1 分钟）----------
py 13_build_features.py  # 19 个特征 → outputs/csv/features.parquet

# ---------- 4. 回测（约 30 分钟）----------
py 30_backtest.py        # 四模型 × 10 折 → metrics_fold.csv
py 31_rerun_lgbm.py      # 修正递归特征后重跑 LightGBM，合并进指标

# ---------- 5. 补货仿真（约 20 分钟）----------
py 40_simulate.py        # → outputs/sim/，并把逐日结果回写 sim_daily 表

# ---------- 6. 图表与报告（约 2 分钟）----------
py 50_weekly.py          # 周报视图 + 图 10
py 60_figs_01_04.py      # 图 01 / 03 / 04
py 61_figs_05_11.py      # 图 05~09 / 11
py 70_report.py          # → reports/供应链需求预测报告.docx
```

### 校验点

跑到一半可以对照这些数字确认没有跑偏：

| 环节 | 期望值 |
|---|---|
| `sales` 行数 | **2,789,217** |
| `v_sales_enriched` 行数 / 价格缺失 | 2,789,217 / **0** |
| `price_final` 与原始价格不一致行数 | **0**（修复前为 188,394） |
| `features.parquet` 行数 / `ma_7` 空值 | 2,789,217 / **1,437** |
| `metrics_fold.csv` 行数 | **40**（4 模型 × 10 折） |
| 仿真 SKU 级 fill rate | ≈ **0.95** |
| `outputs/figures/` | **11** 张 png |

---

## 已修正的三处缺陷

初版实现中有三处会导致结论失真，途中定位并修正——这也是本项目最有价值的部分：

| # | 缺陷 | 后果 | 修正 |
|---|---|---|---|
| 1 | 价格向前填充用「累计**空值**数」分组 | 无缺失的序列所有行落入同一组，`MAX` 取到历史最**高**价。58% 的记录与原始价格不符，`price_vs_avg28` 恒为 1，等于废特征 | 改用「累计**非空**数」分组 |
| 2 | 递归预测中 `np.roll(p, k)` 作用于当天预测向量 | 等于拿其他 SKU 的预测当自身滞后值，WMAPE 高达 0.97 | 改为从时间轴 `ext[:, -k]` 取值 |
| 3 | 补货仿真中在途订单到货后未清零 | 每 7 天重复到货，库存虚增、fill rate 恒为 100%、成本最优点被推到边界 | 到货后 `pipe[:, t % LT] = 0` |

修正后 WMAPE 由 0.97 / 1.10 收敛到 0.711。

---

## 已知局限

- **销量 ≠ 需求**：缺货期间的真实需求无法观测，模型学的是「有货条件下的销量」，
  高缺货场景下预测会被系统性低估。这是删失偏差，不是模型缺陷。
- 仅单店单品类（CA_1 店 FOODS），跨门店/品类未验证。
- 未纳入促销计划、竞品价格、天气等外部变量，价格只能通过「相对近 28 日均价」间接刻画。
- Holt-Winters（0.709）与 LightGBM（0.711）的差距在统计上不显著，不宜宣称某一模型更优。

---

## 相关文档

- [`docs/零基础执行手册.md`](docs/零基础执行手册.md)：从零开始的 9 章分步教程，含每章检查点与常见报错
- [`reports/供应链需求预测报告.docx`](reports/供应链需求预测报告.docx)：完整分析报告（7 节 + 8 张图）
