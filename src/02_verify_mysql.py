# -*- coding: utf-8 -*-
"""
导入后校验：确认 MySQL 里的数据和 data/*.csv 完全一致。

检查项
------
  1. 5 张表行数是否符合预期
  2. fact_sales 的 units 总和是否等于导入时记录的总和（不一致 = 丢了行或有 NULL）
  3. fact_price 的 sell_price 总和是否相等
  4. 主键范围、日期范围、零销量占比是否合理
  5. 抽一行原始数据做逐日比对（HOBBIES_1_001 @ CA_1，1941 天）
  6. 关联完整性：dim_date / dim_item / dim_store 是否覆盖事实表全部取值
  7. 跑几条典型分析 SQL，确认视图可用

用法
----
  python src/02_verify_mysql.py --user root
  python src/02_verify_mysql.py --user root --password xxx --full   # 加做全表关联检查（慢）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(ROOT, "outputs")
TMP = os.path.join(OUT, "_tmp")

EXPECTED = {
    "dim_date": 1969,
    "dim_item": 3049,
    "dim_store": 10,
    "fact_sales": 59181090,
    "fact_price": 6841121,
}

results: list[dict] = []


def check(name: str, ok: bool | None, detail, hint: str = "") -> None:
    status = "PASS" if ok else ("WARN" if ok is None else "FAIL")
    results.append({"check": name, "status": status, "detail": detail, "hint": hint})
    mark = {"PASS": "[OK]  ", "FAIL": "[FAIL]", "WARN": "[WARN]"}[status]
    print(f"  {mark} {name:<42s} {detail}")


def parse_args():
    p = argparse.ArgumentParser(description="M5 导入结果校验")
    p.add_argument("--host", default=os.environ.get("MYSQL_HOST", "127.0.0.1"))
    p.add_argument("--port", type=int, default=int(os.environ.get("MYSQL_PORT", 3306)))
    p.add_argument("--user", default=os.environ.get("MYSQL_USER", "root"))
    p.add_argument("--password", default=None)
    p.add_argument("--database", default="m5_demand")
    p.add_argument("--full", action="store_true", help="加做全表关联完整性检查（较慢）")
    return p.parse_args()


def connect(args):
    import pymysql
    pwd = args.password or os.environ.get("MYSQL_PASSWORD")
    if pwd is None:
        import getpass
        pwd = getpass.getpass(f"MySQL 用户 {args.user} 的密码: ")
    return pymysql.connect(host=args.host, port=args.port, user=args.user,
                           password=pwd, database=args.database,
                           charset="utf8mb4", autocommit=True,
                           connect_timeout=15, read_timeout=7200)


def load_manifest() -> dict:
    p = os.path.join(OUT, "load_manifest.json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return {}


def main() -> int:
    args = parse_args()
    manifest = load_manifest()

    print("=" * 78)
    print("校验 MySQL 导入结果")
    print("=" * 78)

    try:
        conn = connect(args)
    except Exception as e:
        print(f"[错误] 连接失败：{e}")
        return 1
    cur = conn.cursor()

    # ---------- 1. 行数 ----------
    print("\n[1] 行数")
    actual = {}
    for t in EXPECTED:
        cur.execute(f"SELECT COUNT(*) FROM `{t}`")
        actual[t] = int(cur.fetchone()[0])
        exp = EXPECTED[t]
        check(f"COUNT(*) {t}", actual[t] == exp,
              f"{actual[t]:,} / 预期 {exp:,}",
              "用 --skip 少导了某张表？或 LOAD DATA 中途失败")

    has_facts = actual["fact_sales"] > 0

    # ---------- 2. fact_sales 全表汇总（一次全表扫描拿齐所有指标）----------
    print("\n[2] fact_sales 汇总（全表扫一次，约 30~90 秒）")
    t0 = time.time()
    cur.execute("""
        SELECT COUNT(*)              AS n,
               COALESCE(SUM(units),0) AS units_sum,
               MIN(d_key)             AS d_min,
               MAX(d_key)             AS d_max,
               SUM(units = 0)         AS zero_rows,
               SUM(d_key NOT BETWEEN 1 AND 1941) AS bad_d
        FROM fact_sales
    """)
    n, units_sum, d_min, d_max, zero_rows, bad_d = cur.fetchone()
    units_sum, zero_rows, bad_d = int(units_sum), int(zero_rows or 0), int(bad_d or 0)
    print(f"      扫描耗时 {time.time() - t0:.1f}s")

    check("SUM(units) 与导入时一致",
          ("fact_sales" in manifest.get("steps", {})
           and units_sum == manifest["steps"]["fact_sales"].get("units_sum")),
          f"{units_sum:,}",
          "不一致说明有行没进去，或 units 被截断")

    check("d_key 范围包含 1..1941", d_min == 1 and d_max == 1941 and bad_d == 0,
          f"[{d_min}, {d_max}]，越界 {bad_d:,} 行")

    zero_rate = zero_rows / n if n else 0
    check("零销量占比约 68%（M5 特性）", 0.66 <= zero_rate <= 0.70,
          f"{zero_rate:.2%}")

    # ---------- 3. fact_price 汇总 ----------
    print("\n[3] fact_price 汇总")
    cur.execute("""
        SELECT COUNT(*), COALESCE(SUM(sell_price),0),
               MIN(sell_price), MAX(sell_price), MIN(wm_yr_wk), MAX(wm_yr_wk)
        FROM fact_price
    """)
    pn, psum, pmin, pmax, wk_min, wk_max = cur.fetchone()
    psum = float(psum)
    exp_psum = manifest.get("steps", {}).get("fact_price", {}).get("price_sum")
    check("价格总和一致", exp_psum is None or abs(psum - exp_psum) < 1.0,
          f"{psum:,.2f}" + (f" / 预期 {exp_psum:,.2f}" if exp_psum else ""))
    check("价格区间合理", float(pmin) >= 0 and float(pmax) <= 200,
          f"{pmin} ~ {pmax}，周 {wk_min}~{wk_max}")

    # ---------- 4. 抽一行逐日比对 ----------
    print("\n[4] 逐日比对（HOBBIES_1_001 @ CA_1，d_1..d_1941）")
    ck = compare_one_series(cur)
    check("单条时间序列与 CSV 完全一致", ck["ok"],
          f"CSV={ck['csv_sum']:,} DB={ck['db_sum']:,}，不一致天数 {ck['diff_days']}")

    # ---------- 5. 关联完整性 ----------
    print("\n[5] 关联完整性")
    if args.full:
        cur.execute("""
            SELECT COUNT(*) FROM fact_sales s
            LEFT JOIN dim_date d ON d.d_key = s.d_key
            WHERE d.d_key IS NULL
        """)
        orphan_d = int(cur.fetchone()[0])
        check("fact_sales.d_key 全部存在于 dim_date", orphan_d == 0, f"孤儿行 {orphan_d:,}")

        cur.execute("""
            SELECT COUNT(*) FROM fact_sales s
            LEFT JOIN dim_item i ON i.item_id = s.item_id
            WHERE i.item_id IS NULL
        """)
        orphan_i = int(cur.fetchone()[0])
        check("fact_sales.item_id 全部存在于 dim_item", orphan_i == 0, f"孤儿行 {orphan_i:,}")
    else:
        check("关联完整性（全表 LEFT JOIN，需 --full）", None,
              "已跳过", "加 --full 参数执行")

    # ---------- 6. 典型分析 SQL ----------
    print("\n[6] 典型分析 SQL")
    samples = run_samples(cur)
    for name, val in samples.items():
        print(f"      {name:<28s} {val}")

    # ---------- 收尾 ----------
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    summary = {"passed": passed, "failed": failed,
               "checks": results, "counts": actual, "samples": samples,
               "checked_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    path = os.path.join(OUT, "mysql_verify.json")
    os.makedirs(OUT, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)

    print("\n" + "=" * 78)
    print(f"通过 {passed} 项，失败 {failed} 项，报告：{path}")
    print("=" * 78)
    conn.close()
    return 0 if failed == 0 else 2


def compare_one_series(cur) -> dict:
    """从 CSV 只读第一行数据（nrows=2，很快），与数据库逐日比对"""
    try:
        import pandas as pd
        path = os.path.join(DATA, "sales_train_evaluation.csv")
        head = pd.read_csv(path, nrows=2)
        row = head.iloc[0]
        item_id, store_id = row["item_id"], row["store_id"]
        daycols = [c for c in head.columns if c.startswith("d_")]
        csv_vals = [int(row[c]) for c in daycols]

        cur.execute(
            "SELECT d_key, units FROM fact_sales "
            "WHERE store_id = %s AND item_id = %s ORDER BY d_key",
            (store_id, item_id),
        )
        db_rows = cur.fetchall()
        db_vals = [int(u) for _, u in db_rows]

        diff = (sum(1 for a, b in zip(csv_vals, db_vals) if a != b)
                + abs(len(csv_vals) - len(db_vals)))
        return {
            "item_id": item_id, "store_id": store_id,
            "csv_sum": sum(csv_vals), "db_sum": sum(db_vals),
            "diff_days": diff,
            "ok": diff == 0 and len(csv_vals) == len(db_vals),
        }
    except Exception as e:
        return {"ok": False, "csv_sum": -1, "db_sum": -1, "diff_days": -1, "err": str(e)}


def run_samples(cur) -> dict:
    out = {}
    try:
        cur.execute("""
            SELECT i.cat_id, SUM(s.units) AS units, ROUND(SUM(s.units * 1.0) /
                   COUNT(*), 2) AS avg_daily
            FROM fact_sales s
            JOIN dim_item i ON i.item_id = s.item_id
            WHERE s.d_key BETWEEN 1800 AND 1941
            GROUP BY i.cat_id
            ORDER BY units DESC
        """)
        out["各品类销量(最后142天)"] = {
            r[0]: f"{int(r[1]):,} 件，日均 {r[2]}" for r in cur.fetchall()
        }
    except Exception as e:
        out["各品类销量"] = f"查询失败: {e}"

    try:
        cur.execute("""
            SELECT d.`year`, COUNT(DISTINCT s.store_id * 100000 + s.d_key) AS store_days
            FROM fact_sales s JOIN dim_date d ON d.d_key = s.d_key
            WHERE s.d_key = 1
            GROUP BY d.`year`
        """)
        rows = cur.fetchall()
        cur.execute("SELECT COUNT(*) FROM v_sales_daily WHERE d_key = 1")
        out["视图 v_sales_daily(d_1)"] = f"{int(cur.fetchone()[0]):,} 行"
    except Exception as e:
        out["视图 v_sales_daily(d_1)"] = f"查询失败: {e}"

    try:
        cur.execute("""
            SELECT COUNT(*) FROM fact_sales s
            JOIN dim_date d ON d.d_key = s.d_key
            WHERE d.snap_ca = 1 AND s.store_id = 'CA_1' AND s.d_key BETWEEN 1900 AND 1941
        """)
        out["SNAP 日行数(CA_1, 末42天)"] = f"{int(cur.fetchone()[0]):,}"
    except Exception as e:
        out["SNAP 日行数"] = f"查询失败: {e}"

    return out


if __name__ == "__main__":
    sys.exit(main())
