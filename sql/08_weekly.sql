-- ============================================================================
-- 第 8 章 周报视图
-- 依赖：第 7 章仿真回写的 sim_daily（402,360 行 = 280 天 × 1,437 SKU）
-- ============================================================================
USE m5_foods;

DROP VIEW IF EXISTS vw_weekly_report;
CREATE VIEW vw_weekly_report AS
SELECT a.abc,
       YEARWEEK(s.sim_date, 3) AS yr_wk,
       SUM(s.units_demand)  AS demand,
       SUM(s.units_shipped) AS shipped,
       ROUND(SUM(s.abs_err) / NULLIF(SUM(s.units_demand), 0), 4)      AS wmape,
       ROUND(SUM(s.units_shipped) / NULLIF(SUM(s.units_demand), 0), 4) AS fill_rate,
       ROUND(AVG(s.on_hand), 1) AS avg_on_hand,
       ROUND(AVG(s.on_hand) / NULLIF(AVG(s.daily_demand), 0), 1)          AS dos_days,
       SUM(s.stockout_flag) AS stockout_days
FROM sim_daily s
JOIN abc_class a ON a.item_id = s.item_id
GROUP BY a.abc, YEARWEEK(s.sim_date, 3)
ORDER BY yr_wk, a.abc;
