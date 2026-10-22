-- ============================================================================
-- M5 导入结果校验 —— 在 MySQL Workbench 里执行，看结果网格里"结果"列是否全为 OK
--
-- 用法：File > Open SQL Script 打开本文件，点 ⚡ 执行。
--       逐条执行也可以（把光标放在某条语句上按 Ctrl+Enter）。
-- ============================================================================

USE m5_demand;

-- ---------------------------------------------------------------------------
-- 1. 五张表的行数
--    预期：1969 / 3049 / 10 / 59181090 / 6841121
-- ---------------------------------------------------------------------------
SELECT 'dim_date'   AS 表名, COUNT(*) AS 实际, 1969      AS 预期,
       IF(COUNT(*) = 1969,      'OK', 'FAIL') AS 结果 FROM dim_date
UNION ALL
SELECT 'dim_item',   COUNT(*), 3049,      IF(COUNT(*) = 3049,      'OK', 'FAIL') FROM dim_item
UNION ALL
SELECT 'dim_store',  COUNT(*), 10,        IF(COUNT(*) = 10,        'OK', 'FAIL') FROM dim_store
UNION ALL
SELECT 'fact_sales', COUNT(*), 59181090,  IF(COUNT(*) = 59181090,  'OK', 'FAIL') FROM fact_sales
UNION ALL
SELECT 'fact_price', COUNT(*), 6841121,   IF(COUNT(*) = 6841121,   'OK', 'FAIL') FROM fact_price;

-- ---------------------------------------------------------------------------
-- 2. 销量汇总（全表扫一次，59M 行大约 30~90 秒）
--    总销量 66,927,173；非零行 18,939,271（占 32%，其余都是一天没卖出去的行）
--    这两项对不上，说明有分片没导进去
-- ---------------------------------------------------------------------------
SELECT COUNT(*)                AS 行数,
       SUM(units)              AS 销量总和,
       SUM(units > 0)          AS 非零行数,
       ROUND(SUM(units > 0) / COUNT(*) * 100, 2) AS 非零占比百分比,
       IF(COUNT(*) = 59181090 AND SUM(units) = 66927173, 'OK', 'FAIL') AS 结果
FROM fact_sales;

-- ---------------------------------------------------------------------------
-- 3. 价格汇总
--    6,841,121 行，价格区间 0.01 ~ 107.32
-- ---------------------------------------------------------------------------
SELECT COUNT(*)          AS 行数,
       MIN(sell_price)   AS 最低价,
       MAX(sell_price)   AS 最高价,
       MIN(wm_yr_wk)     AS 起始周,
       MAX(wm_yr_wk)     AS 结束周,
       IF(COUNT(*) = 6841121 AND MIN(sell_price) > 0, 'OK', 'FAIL') AS 结果
FROM fact_price;

-- ---------------------------------------------------------------------------
-- 4. 拿一条真实序列对账
--    HOBBIES_1_001 在 CA_1 店：1941 天，合计 633 件，单日最多 5 件
--    （这三个数是我从原始 CSV 直接算出来的，对不上就是转换错了）
-- ---------------------------------------------------------------------------
SELECT COUNT(*)  AS 天数,
       SUM(units) AS 合计销量,
       MAX(units) AS 单日最高,
       IF(COUNT(*) = 1941 AND SUM(units) = 633 AND MAX(units) = 5,
          'OK', 'FAIL') AS 结果
FROM fact_sales
WHERE store_id = 'CA_1' AND item_id = 'HOBBIES_1_001';

-- ---------------------------------------------------------------------------
-- 5. 日期维度是否接得上（d_1 = 2011-01-29，d_1941 = 2016-05-22）
-- ---------------------------------------------------------------------------
SELECT MIN(d.`date`) AS 最早日期, MAX(d.`date`) AS 最晚日期,
       COUNT(*)      AS 天数,
       SUM(d.event_name_1 IS NOT NULL) AS 有事件的天数,
       IF(COUNT(*) = 1969 AND MIN(d.`date`) = '2011-01-29'
          AND MAX(d.`date`) = '2016-06-19', 'OK', 'FAIL') AS 结果
FROM dim_date d;

-- ---------------------------------------------------------------------------
-- 6. 视图是否可用
-- ---------------------------------------------------------------------------
SELECT * FROM v_sales_daily
WHERE store_id = 'CA_1' AND item_id = 'HOBBIES_1_001'
ORDER BY d_key
LIMIT 10;

-- ---------------------------------------------------------------------------
-- 7. 顺手看一眼数据（导入成功后的第一个业务问题）
--    2016 年最后 142 天，三大品类的销量
-- ---------------------------------------------------------------------------
SELECT i.cat_id            AS 品类,
       SUM(s.units)        AS 销量,
       COUNT(DISTINCT s.item_id) AS 商品数,
       ROUND(AVG(s.units), 2)    AS 单店单日平均
FROM fact_sales s
JOIN dim_item i ON i.item_id = s.item_id
WHERE s.d_key BETWEEN 1800 AND 1941
GROUP BY i.cat_id
ORDER BY 销量 DESC;
