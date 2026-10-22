USE m5_foods;

DROP TABLE IF EXISTS price_filled;
CREATE TABLE price_filled AS
SELECT t.item_id, t.store_id, t.wm_yr_wk, p.sell_price,
       COUNT(p.sell_price) OVER (
           PARTITION BY t.item_id ORDER BY t.wm_yr_wk
       ) AS grp
FROM item_week t
LEFT JOIN sell_prices p
       ON p.item_id = t.item_id
      AND p.store_id = t.store_id
      AND p.wm_yr_wk = t.wm_yr_wk;

DROP TABLE IF EXISTS price_ff;
CREATE TABLE price_ff AS
SELECT item_id, store_id, wm_yr_wk,
       MAX(sell_price) OVER (PARTITION BY item_id, grp) AS sell_price
FROM price_filled;

DROP TABLE IF EXISTS price_final;
CREATE TABLE price_final AS
SELECT pf.item_id, pf.store_id, pf.wm_yr_wk,
       COALESCE(pf.sell_price, fp.sell_price) AS sell_price
FROM price_ff pf
LEFT JOIN first_price fp ON fp.item_id = pf.item_id;

CREATE OR REPLACE VIEW v_sales_enriched AS
SELECT s.store_id, s.item_id, s.dept_id, s.cat_id, s.sale_date,
       c.d, c.wm_yr_wk, c.wday, c.weekday, c.month, c.year,
       c.event_name_1, c.event_type_1, c.snap_CA,
       s.units_sold, pf.sell_price
FROM sales s
JOIN calendar c            ON c.sale_date  = s.sale_date
LEFT JOIN price_final pf   ON pf.item_id   = s.item_id
                          AND pf.store_id  = s.store_id
                          AND pf.wm_yr_wk  = c.wm_yr_wk;