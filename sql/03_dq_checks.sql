USE m5_foods;
SET @run = 'R001';

-- ① 主键唯一性
INSERT INTO dq_result
SELECT @run, 1, '主键唯一性', 'sales / sell_prices 主键重复行数', x, 0,
       IF(x = 0, 'PASS', 'FAIL'), NULL, NOW()
FROM (SELECT
        (SELECT COUNT(*) FROM (SELECT 1 FROM sales
             GROUP BY store_id,item_id,sale_date HAVING COUNT(*)>1) a)
      + (SELECT COUNT(*) FROM (SELECT 1 FROM sell_prices
             GROUP BY store_id,item_id,wm_yr_wk HAVING COUNT(*)>1) b) AS x) t;

-- ② 行数完整性
INSERT INTO dq_result
SELECT @run, 2, '行数完整性', '期望 1437 × 1941 = 2789217', x, 0,
       IF(x = 0, 'PASS', 'FAIL'), NULL, NOW()
FROM (SELECT ABS((SELECT COUNT(*) FROM sales) - 1437*1941) AS x) t;

-- ③ 参照完整性
INSERT INTO dq_result
SELECT @run, 3, '参照完整性', 'sales 中无 calendar 记录的日期数', x, 0,
       IF(x = 0, 'PASS', 'FAIL'), NULL, NOW()
FROM (SELECT COUNT(*) AS x FROM sales s
      LEFT JOIN calendar c ON c.sale_date = s.sale_date
      WHERE c.sale_date IS NULL) t;

-- ④ 取值合法性
INSERT INTO dq_result
SELECT @run, 4, '取值合法性', '负数销量 / 非正价格 / 非法 wday / 非法 snap', x, 0,
       IF(x = 0, 'PASS', 'FAIL'), NULL, NOW()
FROM (SELECT
        (SELECT COUNT(*) FROM sales WHERE units_sold < 0)
      + (SELECT COUNT(*) FROM sell_prices WHERE sell_price <= 0)
      + (SELECT COUNT(*) FROM calendar WHERE wday NOT BETWEEN 1 AND 7)
      + (SELECT COUNT(*) FROM calendar WHERE snap_CA NOT IN (0,1)) AS x) t;

-- ⑤ 时序连续性
INSERT INTO dq_result
SELECT @run, 5, '时序连续性', '日期数与 1941 不一致的 SKU 数', x, 0,
       IF(x = 0, 'PASS', 'FAIL'), NULL, NOW()
FROM (SELECT COUNT(*) AS x FROM
        (SELECT item_id, COUNT(DISTINCT sale_date) c
         FROM sales GROUP BY item_id HAVING c <> 1941) z) t;

-- ⑥ 分布异常
INSERT INTO dq_result
SELECT @run, 6, '分布异常',
       '连续零销量 >= 28 天的 SKU 数（疑似下架/断货）', x, 0,
       IF(x = 0, 'PASS', 'WARN'), CONCAT('最长连续零天数最大 = ', mx), NOW()
FROM (SELECT COUNT(*) AS x, MAX(mx_run) AS mx FROM (
        SELECT item_id, MAX(cnt) AS mx_run
        FROM (SELECT item_id, grp, COUNT(*) cnt
              FROM (SELECT item_id, units_sold,
                           ROW_NUMBER() OVER (PARTITION BY item_id ORDER BY sale_date)
                         - ROW_NUMBER() OVER (PARTITION BY item_id, (units_sold = 0)
                                              ORDER BY sale_date) AS grp
                    FROM sales) g0
              WHERE units_sold = 0
              GROUP BY item_id, grp) g1
        GROUP BY item_id) g2) t;