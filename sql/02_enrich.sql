USE m5_foods;

DROP TABLE IF EXISTS item_week;
CREATE TABLE item_week AS
SELECT DISTINCT s.item_id, s.store_id, c.wm_yr_wk
FROM sales s JOIN calendar c ON c.sale_date = s.sale_date;

DROP TABLE IF EXISTS price_filled;
CREATE TABLE price_filled AS
SELECT t.item_id, t.store_id, t.wm_yr_wk, p.sell_price,
       SUM(p.sell_price IS NULL) OVER (
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

DROP TABLE IF EXISTS first_price;
CREATE TABLE first_price AS
SELECT f.item_id, p.sell_price
FROM (SELECT item_id, MIN(wm_yr_wk) AS wk
      FROM sell_prices WHERE store_id = 'CA_1'
      GROUP BY item_id) f
JOIN sell_prices p
  ON p.store_id = 'CA_1' AND p.item_id = f.item_id AND p.wm_yr_wk = f.wk;

DROP TABLE IF EXISTS price_final;
CREATE TABLE price_final AS
SELECT pf.item_id, pf.store_id, pf.wm_yr_wk,
       COALESCE(pf.sell_price, fp.sell_price) AS sell_price
FROM price_ff pf
LEFT JOIN first_price fp ON fp.item_id = pf.item_id;