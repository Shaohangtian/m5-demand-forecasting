USE m5_foods;

DROP TABLE IF EXISTS abc_class;
CREATE TABLE abc_class AS
WITH rev AS (
  SELECT item_id, SUM(units_sold * sell_price) AS revenue_52w
  FROM v_sales_enriched
  WHERE sale_date > (SELECT DATE_SUB(MAX(sale_date), INTERVAL 364 DAY) FROM sales)
  GROUP BY item_id
), rk AS (
  SELECT item_id, revenue_52w,
         SUM(revenue_52w) OVER (ORDER BY revenue_52w DESC, item_id)
           / SUM(revenue_52w) OVER () AS cum_share
  FROM rev
)
SELECT item_id, revenue_52w, cum_share,
       CASE WHEN cum_share <= 0.70 THEN 'A'
            WHEN cum_share <= 0.90 THEN 'B'
            ELSE 'C' END AS abc
FROM rk;

ALTER TABLE abc_class ADD PRIMARY KEY (item_id);

DROP TABLE IF EXISTS abc_summary;
CREATE TABLE abc_summary AS
SELECT abc, COUNT(*) AS n_sku,
       ROUND(COUNT(*) / (SELECT COUNT(*) FROM abc_class) * 100, 1) AS sku_pct,
       ROUND(SUM(revenue_52w), 0) AS revenue,
       ROUND(SUM(revenue_52w) / (SELECT SUM(revenue_52w) FROM abc_class) * 100, 1) AS rev_pct
FROM abc_class GROUP BY abc ORDER BY abc;