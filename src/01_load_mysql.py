# -*- coding: utf-8 -*-
"""
把 data/ 下的 M5 数据批量导入 MySQL 8.0。

导入内容
--------
  dim_date      calendar.csv                   1,969 行
  dim_item      sales 文件维度列去重             3,049 行
  dim_store     sales 文件维度列去重                10 行
  fact_sales    sales_train_evaluation.csv     59,181,090 行（宽表转长表）
  fact_price    sell_prices.csv                 6,841,121 行

为什么不导 sales_train_validation.csv
------------------------------------
  它是 evaluation 的子集（1913 天 vs 1941 天，前 1913 天数值完全相同），
  两个都导会让销量翻倍（+5832 万行），后续任何 SUM 都是错的。

核心思路
--------
  宽表 30,490 行 x 1,941 天无法直接入库，必须转成长表：
  每 2000 个商品读一次 -> melt 成 388 万行 -> 写临时 CSV -> LOAD DATA LOCAL INFILE
  -> 删除临时文件。全程内存占用 < 1GB，磁盘只占约 100MB 临时空间。

用法
----
  # 0) 装驱动（只需要纯 Python 的 pymysql，不需要编译）
  pip install pymysql

  # 1) 先试跑：只生成样本，不连数据库，确认转换逻辑正确
  python src/01_load_mysql.py --dry-run

  # 2) 正式导入（建议先只导小表，确认权限没问题）
  python src/01_load_mysql.py --user root --password 你的密码 --skip fact_sales

  # 3) 全量导入（59M 行，预计 10~30 分钟）
  python src/01_load_mysql.py --user root --password 你的密码

  # 密码也可以用环境变量，避免留在命令历史里
  set MYSQL_PASSWORD=你的密码
  python src/01_load_mysql.py --user root

参数
----
  --host/--port/--user/--password/--database   连接信息
  --skip fact_sales        跳过某个步骤，可写多次
  --dry-run                不连数据库，只验证转换逻辑
  --chunk 2000             每个分片读多少行宽表（内存不够就调小）
  --mode infile|insert     infile 快 10~20 倍；insert 是 LOAD DATA 被禁用时的退路
  --no-schema              跳过建表（断点续传时用，注意事实表不要重复导入）
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(ROOT, "outputs")
TMP = os.path.join(OUT, "_tmp")
SCHEMA_SQL = os.path.join(ROOT, "sql", "01_schema.sql")

SALES_FILE = "sales_train_evaluation.csv"
SALES_SKIP = "sales_train_validation.csv"
PRICE_FILE = "sell_prices.csv"
CAL_FILE = "calendar.csv"

# 各表预期行数，仅用于最后打印对比
EXPECTED = {
    "dim_date": 1969,
    "dim_item": 3049,
    "dim_store": 10,
    "fact_sales": 30490 * 1941,
    "fact_price": 6841121,
}


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
def hr(title: str) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def fmt_secs(s: float) -> str:
    if s < 90:
        return f"{s:.1f}s"
    m, sec = divmod(int(s), 60)
    if m < 90:
        return f"{m}m{sec:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m"


def check_files() -> None:
    missing = [f for f in (SALES_FILE, PRICE_FILE, CAL_FILE)
               if not os.path.exists(os.path.join(DATA, f))]
    if missing:
        sys.exit(f"[错误] data/ 目录缺少文件: {missing}")


# ---------------------------------------------------------------------------
# 宽表 -> 长表
# ---------------------------------------------------------------------------
def iter_sales_long(chunk_rows: int, max_chunks: int | None = None):
    """按分片读取 sales 宽表，yield 长表 DataFrame(store_id, item_id, d_key, units)。

    输出顺序保持源文件行序（store_id, item_id 递增），且每个商品内部 d_key 递增，
    正好与 fact_sales 的主键 (store_id, item_id, d_key) 一致 —— InnoDB 顺序追加写，
    比乱序插入快很多。
    """
    import pandas as pd
    import numpy as np

    path = os.path.join(DATA, SALES_FILE)
    head = pd.read_csv(path, nrows=0)
    daycols = [c for c in head.columns if c.startswith("d_")]
    daykeys = [int(c[2:]) for c in daycols]
    rename = dict(zip(daycols, daykeys))
    usecols = ["store_id", "item_id"] + daycols

    reader = pd.read_csv(path, usecols=usecols, chunksize=chunk_rows)
    for i, chunk in enumerate(reader):
        if max_chunks is not None and i >= max_chunks:
            break
        chunk = chunk.rename(columns=rename)

        # 不用 df.melt：melt 是"变量优先"输出（先 d_1 的全部行，再 d_2 的全部行），
        # 会让入库顺序与主键 (store_id, item_id, d_key) 相反。这里直接用 numpy
        # 按行 flatten，得到"门店+商品优先、日期递增"的顺序，正好等于主键顺序，
        # InnoDB 就是顺序追加写，比乱序插入快数倍，也省内存。
        nd = len(daykeys)
        n = len(chunk)
        long = pd.DataFrame({
            "store_id": np.repeat(chunk["store_id"].to_numpy(), nd),
            "item_id": np.repeat(chunk["item_id"].to_numpy(), nd),
            "d_key": np.tile(np.asarray(daykeys, dtype="int32"), n),
            "units": chunk[daykeys].to_numpy(dtype="int32").ravel(),
        })
        yield long


def build_dim_date_csv() -> tuple[str, int]:
    """calendar.csv -> dim_date.csv（补出 d_key，空事件名写成 \\N 以便 MySQL 存 NULL）"""
    import pandas as pd

    cal = pd.read_csv(os.path.join(DATA, CAL_FILE), parse_dates=["date"])
    cal["d_key"] = cal["d"].str[2:].astype("int32")
    cal["date"] = cal["date"].dt.strftime("%Y-%m-%d")

    cols = ["d_key", "d", "date", "wm_yr_wk", "weekday", "wday", "month", "year",
            "event_name_1", "event_type_1", "event_name_2", "event_type_2",
            "snap_CA", "snap_TX", "snap_WI"]
    out = cal[cols]
    path = os.path.join(TMP, "dim_date.csv")
    # na_rep='\\N' + MySQL 默认 FIELDS ESCAPED BY '\\' => 空事件名落成 NULL 而不是 ''
    out.to_csv(path, index=False, header=False, lineterminator="\n", na_rep="\\N")
    return path, len(out)


def build_item_store_csv() -> tuple[str, int, str, int]:
    """从 sales 文件只读 5 个维度列，去重得到 dim_item / dim_store"""
    import pandas as pd

    meta = pd.read_csv(
        os.path.join(DATA, SALES_FILE),
        usecols=["item_id", "dept_id", "cat_id", "store_id", "state_id"],
    )
    items = meta[["item_id", "dept_id", "cat_id"]].drop_duplicates().sort_values("item_id")
    stores = meta[["store_id", "state_id"]].drop_duplicates().sort_values("store_id")

    ip = os.path.join(TMP, "dim_item.csv")
    sp = os.path.join(TMP, "dim_store.csv")
    items.to_csv(ip, index=False, header=False, lineterminator="\n")
    stores.to_csv(sp, index=False, header=False, lineterminator="\n")
    return ip, len(items), sp, len(stores)


# ---------------------------------------------------------------------------
# MySQL 操作
# ---------------------------------------------------------------------------
def connect(args):
    import pymysql

    pwd = args.password
    if pwd is None:
        pwd = os.environ.get("MYSQL_PASSWORD")
    if pwd is None:
        import getpass
        pwd = getpass.getpass(f"MySQL 用户 {args.user} 的密码: ")

    return pymysql.connect(
        host=args.host,
        port=args.port,
        user=args.user,
        password=pwd,
        charset="utf8mb4",
        autocommit=False,
        local_infile=True,          # 允许 LOAD DATA LOCAL INFILE
        connect_timeout=15,
        write_timeout=3600,
        read_timeout=3600,
    )


def run_schema(conn, skip: bool) -> None:
    if skip:
        print("  (已指定 --no-schema，跳过建表)")
        return
    with open(SCHEMA_SQL, encoding="utf-8") as f:
        text = f.read()
    # 去掉整行注释后按分号切分；本项目的 DDL 里没有字符串内含分号的情况
    body = "\n".join(ln for ln in text.splitlines() if not ln.strip().startswith("--"))
    stmts = [s.strip() for s in body.split(";") if s.strip()]

    cur = conn.cursor()
    for s in stmts:
        cur.execute(s)
    conn.commit()
    print(f"  建表完成，共执行 {len(stmts)} 条语句")


def tune_session(conn) -> None:
    """批量导入期间的会话优化。拿不到权限就跳过，不影响正确性。"""
    cur = conn.cursor()
    for stmt in (
        "SET SESSION unique_checks = 0",
        "SET SESSION foreign_key_checks = 0",
        "SET SESSION sql_mode = 'NO_ENGINE_SUBSTITUTION'",
        "SET SESSION net_write_timeout = 3600",
    ):
        try:
            cur.execute(stmt)
        except Exception:
            pass
    # 这两个是全局变量，通常需要 SYSTEM_VARIABLES_ADMIN，失败也无所谓
    for stmt, desc in (
        ("SET GLOBAL innodb_flush_log_at_trx_commit = 2", "降低刷盘频率"),
        ("SET GLOBAL innodb_buffer_pool_size = 2147483648", "buffer pool 调到 2G"),
    ):
        try:
            cur.execute(stmt)
            print(f"  已调整全局参数：{desc}")
        except Exception:
            pass
    conn.commit()


def ensure_local_infile(conn) -> bool:
    cur = conn.cursor()
    cur.execute("SHOW VARIABLES LIKE 'local_infile'")
    row = cur.fetchone()
    val = str(row[1]).upper() if row else "OFF"
    if val in ("ON", "1"):
        return True
    try:
        cur.execute("SET GLOBAL local_infile = 1")
        print("  已临时开启 local_infile（重启 MySQL 后失效，如需永久生效见 docs 指南）")
        return True
    except Exception as e:
        print(f"  [警告] local_infile 为 OFF 且无法自动开启：{e}")
        return False


def load_data(conn, table: str, path: str, columns: list[str],
              ignore_header: bool = False) -> int:
    """LOAD DATA LOCAL INFILE —— 比 INSERT 快 10~20 倍"""
    # 统一成正斜杠，避免 Windows 反斜杠被当作转义符
    p = os.path.abspath(path).replace("\\", "/")
    sql = (
        f"LOAD DATA LOCAL INFILE %s INTO TABLE `{table}` "
        "CHARACTER SET utf8mb4 "
        "FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '\"' "
        "LINES TERMINATED BY '\\n' "
        + ("IGNORE 1 LINES " if ignore_header else "")
        + f"({', '.join('`%s`' % c for c in columns)})"
    )
    cur = conn.cursor()
    cur.execute(sql, (p,))
    conn.commit()
    return cur.rowcount


def insert_data(conn, table: str, columns: list[str], rows, batch: int = 5000) -> int:
    """LOAD DATA 被禁用时的退路，慢很多但只要能连库就能用"""
    sql = (f"INSERT INTO `{table}` ({', '.join('`%s`' % c for c in columns)}) "
           f"VALUES ({', '.join(['%s'] * len(columns))})")
    cur = conn.cursor()
    buf, total = [], 0
    for r in rows:
        buf.append(tuple(r))
        if len(buf) >= batch:
            cur.executemany(sql, buf)
            conn.commit()
            total += len(buf)
            buf = []
    if buf:
        cur.executemany(sql, buf)
        conn.commit()
        total += len(buf)
    return total


def load_table(conn, table: str, path: str, columns: list[str], mode: str,
               ignore_header: bool = False, df=None) -> int:
    """统一入口：默认 LOAD DATA，--mode insert 时退回批量 INSERT"""
    if mode == "infile":
        return load_data(conn, table, path, columns, ignore_header)

    import pandas as pd
    if df is None:
        df = pd.read_csv(path, header=0 if ignore_header else None,
                         names=columns, dtype=str)
    return insert_data(conn, table, columns, df.itertuples(index=False, name=None))


# ---------------------------------------------------------------------------
# 各步骤
# ---------------------------------------------------------------------------
def step_dim_date(conn, mode: str) -> int:
    path, n = build_dim_date_csv()
    cols = ["d_key", "d", "date", "wm_yr_wk", "weekday", "wday", "month", "year",
            "event_name_1", "event_type_1", "event_name_2", "event_type_2",
            "snap_ca", "snap_tx", "snap_wi"]
    load_table(conn, "dim_date", path, cols, mode)
    print(f"  dim_date   : {n:>10,} 行")
    return n


def step_dims(conn, mode: str) -> int:
    ip, ni, sp, ns = build_item_store_csv()
    load_table(conn, "dim_item", ip, ["item_id", "dept_id", "cat_id"], mode)
    load_table(conn, "dim_store", sp, ["store_id", "state_id"], mode)
    print(f"  dim_item   : {ni:>10,} 行\n  dim_store  : {ns:>10,} 行")
    return ni + ns


def step_fact_sales(conn, args) -> tuple[int, int]:
    """逐片 宽表 -> 长表 -> 临时 CSV -> LOAD DATA -> 删临时文件。

    返回 (行数, units 总和)，units 总和写进 manifest 供校验脚本比对。
    """
    cols = ["store_id", "item_id", "d_key", "units"]
    tmp = os.path.join(TMP, "fact_sales_part.csv")
    total_rows = 0
    total_units = 0
    done = 0
    total_chunks = -(-30490 // args.chunk)
    t0 = time.time()

    for long in iter_sales_long(args.chunk):
        long.to_csv(tmp, index=False, header=False, lineterminator="\n")
        load_table(conn, "fact_sales", tmp, cols, args.mode, df=long)
        total_rows += len(long)
        total_units += int(long["units"].sum())
        os.remove(tmp)
        done += 1

        elapsed = time.time() - t0
        eta = elapsed / done * (total_chunks - done)
        print(f"  {done:>2}/{total_chunks} 片  {total_rows:>12,} / 59,181,090 行  "
              f"({fmt_secs(elapsed)}, 预计剩余 {fmt_secs(eta)})")

    return total_rows, total_units


def step_fact_price(conn, mode: str) -> tuple[int, float]:
    import pandas as pd

    path = os.path.join(DATA, PRICE_FILE)
    cols = ["store_id", "item_id", "wm_yr_wk", "sell_price"]
    load_table(conn, "fact_price", path, cols, mode, ignore_header=True)
    print(f"  fact_price : {EXPECTED['fact_price']:>10,} 行")

    # 同时算出价格总和，供校验比对
    sp = pd.read_csv(path, usecols=["sell_price"])
    return EXPECTED["fact_price"], round(float(sp["sell_price"].sum()), 2)


# ---------------------------------------------------------------------------
# dry-run
# ---------------------------------------------------------------------------
def dry_run(args) -> int:
    hr("DRY RUN：只验证转换逻辑，不连数据库")
    path, n = build_dim_date_csv()
    print(f"  dim_date.csv 已生成: {n} 行 -> {path}")
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i < 3:
                print("    ", line.rstrip())
            else:
                break

    ip, ni, sp, ns = build_item_store_csv()
    print(f"  dim_item.csv 已生成: {ni} 行 -> {ip}")
    print(f"  dim_store.csv 已生成: {ns} 行 -> {sp}")

    rows = 0
    units = 0
    last = None
    t0 = time.time()
    for long in iter_sales_long(args.chunk, max_chunks=args.limit_chunks):
        rows += len(long)
        units += int(long["units"].sum())
        last = long
    dur = time.time() - t0

    print(f"\n  宽表探针: {args.limit_chunks} 片 x {args.chunk} 行 -> 长表 {rows:,} 行")
    print(f"  耗时 {fmt_secs(dur)}，units 合计 {units:,}")
    print(f"  长表前 3 行:\n{last.head(3).to_string(index=False)}")
    print(f"  长表列 dtype: {dict(last.dtypes.astype(str))}")

    est = dur / rows * EXPECTED["fact_sales"] if rows else 0
    print(f"\n  按此速度推算全量 59,181,090 行转换约需 {fmt_secs(est)}（不含入库时间）")
    return 0


# ---------------------------------------------------------------------------
def parse_args():
    p = argparse.ArgumentParser(description="M5 数据导入 MySQL")
    p.add_argument("--host", default=os.environ.get("MYSQL_HOST", "127.0.0.1"))
    p.add_argument("--port", type=int, default=int(os.environ.get("MYSQL_PORT", 3306)))
    p.add_argument("--user", default=os.environ.get("MYSQL_USER", "root"))
    p.add_argument("--password", default=None, help="不填则读 MYSQL_PASSWORD 或交互输入")
    p.add_argument("--database", default="m5_demand")
    p.add_argument("--skip", action="append", default=[],
                   choices=["dim_date", "dims", "fact_sales", "fact_price"])
    p.add_argument("--chunk", type=int, default=2000, help="每片读取的宽表行数")
    p.add_argument("--mode", choices=["infile", "insert"], default="infile")
    p.add_argument("--no-schema", action="store_true", help="跳过建表")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit-chunks", type=int, default=1, help="dry-run 时处理几片")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    os.makedirs(TMP, exist_ok=True)
    check_files()

    if args.dry_run:
        return dry_run(args)

    import pymysql  # noqa: F401  （缺包时给出友好提示）
    from pymysql.err import OperationalError

    hr("连接 MySQL")
    try:
        conn = connect(args)
    except Exception as e:
        print(f"[错误] 连接失败：{e}")
        print("  检查：1) MySQL80 服务是否在跑  2) 用户名/密码  3) 端口是否 3306")
        return 1
    print(f"  已连接 {args.host}:{args.port}，字符集 utf8mb4")

    if args.mode == "infile" and not ensure_local_infile(conn):
        print("\n[中止] 请先在 MySQL 里执行：SET GLOBAL local_infile = 1;")
        print("       或修改 my.ini 加 local_infile=1 后重启服务。")
        print("       实在改不了，加参数 --mode insert 走 INSERT 退路（会慢很多）。")
        return 1

    hr("建表")
    run_schema(conn, args.no_schema)
    tune_session(conn)

    manifest = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "steps": {}}
    t_start = time.time()

    if "dim_date" not in args.skip:
        hr("导入 dim_date")
        manifest["steps"]["dim_date"] = {"rows": step_dim_date(conn, args.mode)}

    if "dims" not in args.skip:
        hr("导入 dim_item / dim_store")
        manifest["steps"]["dims"] = {"rows": step_dims(conn, args.mode)}

    if "fact_sales" not in args.skip:
        hr("导入 fact_sales（59,181,090 行，最慢的一步）")
        n, units = step_fact_sales(conn, args)
        manifest["steps"]["fact_sales"] = {"rows": n, "units_sum": units}
        print(f"  fact_sales : {n:>10,} 行，units 合计 {units:,}")

    if "fact_price" not in args.skip:
        hr("导入 fact_price")
        n, psum = step_fact_price(conn, args.mode)
        manifest["steps"]["fact_price"] = {"rows": n, "price_sum": psum}

    manifest["elapsed_secs"] = round(time.time() - t_start, 1)
    manifest["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
    mpath = os.path.join(OUT, "load_manifest.json")
    with open(mpath, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    hr("完成")
    print(f"  总耗时 {fmt_secs(manifest['elapsed_secs'])}")
    print(f"  导入清单已写入 {mpath}")
    print("  下一步：python src/02_verify_mysql.py  （核对行数与汇总值）")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
