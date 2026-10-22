USE m5_foods;

SET SESSION sort_buffer_size = 268435456;

DROP TABLE IF EXISTS feat_item_day;
CREATE TABLE feat_item_day AS
SELECT
  e.item_id, e.sale_date, e.dept_id,
  e.units_sold AS y,
  e.sell_price, e.wday, e.month, e.year, e.snap_CA,
  (e.event_name_1 IS NOT NULL) AS is_event,

  /* 滞后 */
  LAG(e.units_sold, 1)  OVER w AS lag_1,
  LAG(e.units_sold, 7)  OVER w AS lag_7,
  LAG(e.units_sold, 14) OVER w AS lag_14,
  LAG(e.units_sold, 28) OVER w AS lag_28,

  /* 滚动均值：右端 1 PRECEDING */
  AVG(e.units_sold) OVER (PARTITION BY e.item_id ORDER BY e.sale_date
      ROWS BETWEEN 6 PRECEDING AND 1 PRECEDING)   AS ma_7,
  AVG(e.units_sold) OVER (PARTITION BY e.item_id ORDER BY e.sale_date
      ROWS BETWEEN 27 PRECEDING AND 1 PRECEDING)  AS ma_28,
  AVG(e.units_sold) OVER (PARTITION BY e.item_id ORDER BY e.sale_date
      ROWS BETWEEN 55 PRECEDING AND 1 PRECEDING)  AS ma_56,

  /* 滚动标准差 */
  STDDEV_SAMP(e.units_sold) OVER (PARTITION BY e.item_id ORDER BY e.sale_date
      ROWS BETWEEN 6 PRECEDING AND 1 PRECEDING)   AS sd_7,
  STDDEV_SAMP(e.units_sold) OVER (PARTITION BY e.item_id ORDER BY e.sale_date
      ROWS BETWEEN 27 PRECEDING AND 1 PRECEDING)  AS sd_28,

  /* 极值 */
  MAX(e.units_sold) OVER (PARTITION BY e.item_id ORDER BY e.sale_date
      ROWS BETWEEN 27 PRECEDING AND 1 PRECEDING)  AS mx_28,
  MIN(e.units_sold) OVER (PARTITION BY e.item_id ORDER BY e.sale_date
      ROWS BETWEEN 27 PRECEDING AND 1 PRECEDING)  AS mn_28,

  /* 零销量结构（间歇性需求） */
  SUM(e.units_sold = 0) OVER (PARTITION BY e.item_id ORDER BY e.sale_date
      ROWS BETWEEN 27 PRECEDING AND 1 PRECEDING)  AS zero_days_28,

  /* 趋势 */
  AVG(e.units_sold) OVER (PARTITION BY e.item_id ORDER BY e.sale_date
      ROWS BETWEEN 6 PRECEDING AND 1 PRECEDING)
  / NULLIF(AVG(e.units_sold) OVER (PARTITION BY e.item_id ORDER BY e.sale_date
      ROWS BETWEEN 27 PRECEDING AND 1 PRECEDING), 0) AS ma7_ma28_ratio,

  /* 价格 */
  e.sell_price
  / NULLIF(AVG(e.sell_price) OVER (PARTITION BY e.item_id ORDER BY e.sale_date
      ROWS BETWEEN 27 PRECEDING AND 1 PRECEDING), 0) AS price_vs_avg28,
  e.sell_price - LAG(e.sell_price, 1) OVER w AS price_delta

FROM v_sales_enriched e
WINDOW w AS (PARTITION BY e.item_id ORDER BY e.sale_date);