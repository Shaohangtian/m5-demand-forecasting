# -*- coding: utf-8 -*-
"""
给 MySQL Workbench 用的预处理脚本：把 data/ 里的文件变成 Workbench 能直接
LOAD DATA 的 CSV，并生成两个可以直接"打开 + 执行"的 SQL 文件。

为什么需要这一步
--------------
  Workbench 的 Table Data Import Wizard 只能导入"列对列"的规整 CSV。
  而 sales_train_evaluation.csv 是 30490 行 x 1941 个 d_N 列的宽表，
  InnoDB 单表最多 1017 列，根本建不出对应的表，向导也就无从映射。
  所以在 Workbench 里唯一正确的做法是：用 Python 把宽表摊平成"长表"CSV，
  再用 SQL 编辑器执行 LOAD DATA。

产出
----
  outputs/_stage/dim_date.csv                  1,969 行
  outputs/_stage/dim_item.csv                  3,049 行
  outputs/_stage/dim_store.csv                    10 行
  outputs/_stage/fact_sales_part_01..16.csv    每片 3,882,000 行（合计 5918 万）
  outputs/_stage/fact_price.csv                6,841,121 行（去掉表头）
  sql/02_load_data_local.sql                   直接可用（LOAD DATA LOCAL INFILE）
  sql/02_load_data_server.sql                  备用（需先把 _stage 复制到 Uploads）

用法
----
  py src/01b_stage_for_workbench.py
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STAGE = os.path.join(ROOT, "outputs", "_stage")
SQLDIR = os.path.join(ROOT, "sql")
DATA = os.path.join(ROOT, "data")

CHUNK_ROWS = 2000
UPLOADS_POSIX = "C:/ProgramData/MySQL/MySQL Server 8.0/Uploads/_stage"


def load_loader():
    """以模块方式加载 01_load_mysql.py（文件名以数字开头，不能直接 import）"""
    spec = importlib.util.spec_from_file_location(
        "loader", os.path.join(ROOT, "src", "01_load_mysql.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def posix(p: str) -> str:
    return os.path.abspath(p).replace("\\", "/")


def data_stmt(table: str, path_posix: str, cols: list[str], local: bool,
              tag: str = "") -> str:
    kw = "LOCAL " if local else ""
    body = (
        f"LOAD DATA {kw}INFILE '{path_posix}'\n"
        f"  INTO TABLE {table}\n"
        f"  CHARACTER SET utf8mb4\n"
        f"  FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '\"'\n"
        f"  LINES TERMINATED BY '\\n'\n"
        f"  ({', '.join(cols)});\n"
    )
    return f"-- {tag or os.path.basename(path_posix)}\n{body}\n"


def write_sql(local: bool, sales_parts: list[str], out_path: str) -> None:
    base = posix(STAGE) if local else UPLOADS_POSIX
    mode_cn = "LOAD DATA LOCAL INFILE（文件留在项目里，不需要管理员权限）" if local \
        else "LOAD DATA INFILE（文件必须先复制到 MySQL 的 Uploads 目录）"
    head = f"""-- ============================================================================
-- M5 数据导入 —— 在 MySQL Workbench 里执行
-- 方式：{mode_cn}
--
-- 执行步骤
--   1. Workbench 里连接本地 MySQL80
--   2. File > Open SQL Script... 打开本文件
--   3. 点工具栏的闪电图标 ⚡ 执行（或 Ctrl+Shift+Enter）
--   4. 第一条 LOAD DATA 就会暴露配置问题：
--        ERROR 3948  -> 服务端没开，先单独执行  SET GLOBAL local_infile = 1;
--        ERROR 1148  -> 客户端不允许 LOCAL，改用 sql/02_load_data_server.sql
--
-- 预计耗时：10~25 分钟；入库后占用磁盘约 3 GB
-- ============================================================================

SET NAMES utf8mb4;
USE m5_demand;

SET SESSION unique_checks      = 0;
SET SESSION foreign_key_checks = 0;
SET SESSION sql_mode           = 'NO_ENGINE_SUBSTITUTION';

-- ---------------------------------------------------------------------------
-- 1. 维表
-- ---------------------------------------------------------------------------
"""
    parts = [head]
    parts.append(data_stmt("dim_date", f"{base}/dim_date.csv",
                           ["d_key", "d", "`date`", "wm_yr_wk", "weekday", "wday",
                            "`month`", "`year`", "event_name_1", "event_type_1",
                            "event_name_2", "event_type_2", "snap_ca", "snap_tx",
                            "snap_wi"], local, "日历 1,969 行"))
    parts.append(data_stmt("dim_item", f"{base}/dim_item.csv",
                           ["item_id", "dept_id", "cat_id"], local, "商品 3,049 行"))
    parts.append(data_stmt("dim_store", f"{base}/dim_store.csv",
                           ["store_id", "state_id"], local, "门店 10 行"))

    parts.append("-- ---------------------------------------------------------------------------\n"
                 "-- 2. 周价格 6,841,121 行（最大的一张，先跑这个观察速度）\n"
                 "-- ---------------------------------------------------------------------------\n")
    parts.append(data_stmt("fact_price", f"{base}/fact_price.csv",
                           ["store_id", "item_id", "wm_yr_wk", "sell_price"], local,
                           "价格 6,841,121 行"))

    parts.append("-- ---------------------------------------------------------------------------\n"
                 "-- 3. 日销量 59,181,090 行，分 16 片。每片约 100 MB，逐片执行。\n"
                 "--    中途失败只需重跑未完成的那几片（主键唯一，重复执行会报 Duplicate）。\n"
                 "-- ---------------------------------------------------------------------------\n")
    for name in sales_parts:
        parts.append(data_stmt("fact_sales", f"{base}/{name}",
                               ["store_id", "item_id", "d_key", "units"], local, name))

    parts.append("""-- ---------------------------------------------------------------------------
-- 4. 更新统计信息，优化器才会选对索引
-- ---------------------------------------------------------------------------
ANALYZE TABLE dim_date, dim_item, dim_store, fact_sales, fact_price;

-- 行数自检：应分别为 1969 / 3049 / 10 / 59181090 / 6841121
SELECT 'dim_date'   AS tbl, COUNT(*) AS rows_ FROM dim_date
UNION ALL SELECT 'dim_item',   COUNT(*) FROM dim_item
UNION ALL SELECT 'dim_store',  COUNT(*) FROM dim_store
UNION ALL SELECT 'fact_sales', COUNT(*) FROM fact_sales
UNION ALL SELECT 'fact_price', COUNT(*) FROM fact_price;
""")

    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("".join(parts))


def main() -> int:
    t0 = time.time()
    loader = load_loader()

    if os.path.exists(STAGE):
        shutil.rmtree(STAGE)
    os.makedirs(STAGE, exist_ok=True)
    os.makedirs(loader.TMP, exist_ok=True)
    print(f"输出目录: {STAGE}")

    # ---- 维表 ----
    p, n = loader.build_dim_date_csv()
    shutil.copyfile(p, os.path.join(STAGE, "dim_date.csv"))
    ip, ni, sp, ns = loader.build_item_store_csv()
    shutil.copyfile(ip, os.path.join(STAGE, "dim_item.csv"))
    shutil.copyfile(sp, os.path.join(STAGE, "dim_store.csv"))
    print(f"  dim_date {n:,} / dim_item {ni:,} / dim_store {ns:,}")

    # ---- 价格：去掉表头，省掉 IGNORE 1 LINES 的不一致 ----
    src = os.path.join(DATA, "sell_prices.csv")
    dst = os.path.join(STAGE, "fact_price.csv")
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        fi.readline()
        shutil.copyfileobj(fi, fo, length=8 * 1024 * 1024)
    print(f"  fact_price {os.path.getsize(dst) / 1e6:,.0f} MB")

    # ---- 销量分片 ----
    parts = []
    rows = 0
    for i, long in enumerate(loader.iter_sales_long(CHUNK_ROWS), start=1):
        name = f"fact_sales_part_{i:02d}.csv"
        long.to_csv(os.path.join(STAGE, name), index=False, header=False,
                    lineterminator="\n")
        parts.append(name)
        rows += len(long)
        print(f"  {name}  {len(long):>10,} 行  "
              f"(累计 {rows:,} / 59,181,090)")

    # ---- 生成 SQL ----
    os.makedirs(SQLDIR, exist_ok=True)
    write_sql(True, parts, os.path.join(SQLDIR, "02_load_data_local.sql"))
    write_sql(False, parts, os.path.join(SQLDIR, "02_load_data_server.sql"))
    total_mb = sum(os.path.getsize(os.path.join(STAGE, f))
                   for f in os.listdir(STAGE)) / 1e6

    print(f"\n完成，耗时 {time.time() - t0:.1f}s，_stage 共 {total_mb / 1000:.2f} GB，"
          f"{len(parts) + 4} 个 CSV")
    print(f"  {os.path.join(SQLDIR, '02_load_data_local.sql')}")
    print(f"  {os.path.join(SQLDIR, '02_load_data_server.sql')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
