import pymysql
from config import DB, CSV

path = (CSV / "sales_long.csv").as_posix()   # SQL 里必须用正斜杠

conn = pymysql.connect(
    host=DB["host"], port=DB["port"], user=DB["user"],
    password=DB["password"], database=DB["database"],
    local_infile=True, charset="utf8mb4", autocommit=True,
)
cur = conn.cursor()
cur.execute("TRUNCATE TABLE sales")
sql = f"""
LOAD DATA LOCAL INFILE '{path}'
INTO TABLE sales
FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
LINES TERMINATED BY '\n'
IGNORE 1 LINES
(store_id, item_id, dept_id, cat_id, state_id, sale_date, units_sold)
"""
cur.execute(sql)
print("imported:", cur.rowcount)

# 载完再建索引，比边载边建快 3~5 倍
cur.execute("ALTER TABLE sales ADD PRIMARY KEY (store_id, item_id, sale_date)")
cur.execute("ALTER TABLE sales ADD INDEX idx_date (sale_date)")
cur.execute("ALTER TABLE sales ADD INDEX idx_item (item_id, sale_date)")
cur.execute("SELECT COUNT(*) FROM sales")
print("总计:", cur.fetchone()[0], "（应为 2789217）")
conn.close()