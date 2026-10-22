-- ============================================================================
-- M5 数据导入 —— 在 MySQL Workbench 里执行
-- 方式：LOAD DATA INFILE（文件必须先复制到 MySQL 的 Uploads 目录）
--
-- 执行步骤
--   1. Workbench 里连接本地 MySQL80
--   2. File > Open SQL Script... 打开本文件
--   3. 点工具栏的闪电图标 ⚡ 执行（或 Ctrl+Shift+Enter）
--   4. 第一条 LOAD DATA 就会暴露配置问题：
--        ERROR 3948  -> 服务端没开，先单独执行  SET GLOBAL local_infile = 1;
--        ERROR 1148  -> 客户端不允许 LOCAL，改用 sql/02_load_data_server.sql
--
-- 预计耗时：10~25 分钟；入库后占用磁盘约 3 GB
-- ============================================================================

SET NAMES utf8mb4;
USE m5_demand;

SET SESSION unique_checks      = 0;
SET SESSION foreign_key_checks = 0;
SET SESSION sql_mode           = 'NO_ENGINE_SUBSTITUTION';

-- ---------------------------------------------------------------------------
-- 1. 维表
-- ---------------------------------------------------------------------------
-- 日历 1,969 行
LOAD DATA INFILE 'C:/ProgramData/MySQL/MySQL Server 8.0/Uploads/_stage/dim_date.csv'
  INTO TABLE dim_date
  CHARACTER SET utf8mb4
  FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
  LINES TERMINATED BY '\n'
  (d_key, d, `date`, wm_yr_wk, weekday, wday, `month`, `year`, event_name_1, event_type_1, event_name_2, event_type_2, snap_ca, snap_tx, snap_wi);

-- 商品 3,049 行
LOAD DATA INFILE 'C:/ProgramData/MySQL/MySQL Server 8.0/Uploads/_stage/dim_item.csv'
  INTO TABLE dim_item
  CHARACTER SET utf8mb4
  FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
  LINES TERMINATED BY '\n'
  (item_id, dept_id, cat_id);

-- 门店 10 行
LOAD DATA INFILE 'C:/ProgramData/MySQL/MySQL Server 8.0/Uploads/_stage/dim_store.csv'
  INTO TABLE dim_store
  CHARACTER SET utf8mb4
  FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
  LINES TERMINATED BY '\n'
  (store_id, state_id);

-- ---------------------------------------------------------------------------
-- 2. 周价格 6,841,121 行（最大的一张，先跑这个观察速度）
-- ---------------------------------------------------------------------------
-- 价格 6,841,121 行
LOAD DATA INFILE 'C:/ProgramData/MySQL/MySQL Server 8.0/Uploads/_stage/fact_price.csv'
  INTO TABLE fact_price
  CHARACTER SET utf8mb4
  FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
  LINES TERMINATED BY '\n'
  (store_id, item_id, wm_yr_wk, sell_price);

-- ---------------------------------------------------------------------------
-- 3. 日销量 59,181,090 行，分 16 片。每片约 100 MB，逐片执行。
--    中途失败只需重跑未完成的那几片（主键唯一，重复执行会报 Duplicate）。
-- ---------------------------------------------------------------------------
-- fact_sales_part_01.csv
LOAD DATA INFILE 'C:/ProgramData/MySQL/MySQL Server 8.0/Uploads/_stage/fact_sales_part_01.csv'
  INTO TABLE fact_sales
  CHARACTER SET utf8mb4
  FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
  LINES TERMINATED BY '\n'
  (store_id, item_id, d_key, units);

-- fact_sales_part_02.csv
LOAD DATA INFILE 'C:/ProgramData/MySQL/MySQL Server 8.0/Uploads/_stage/fact_sales_part_02.csv'
  INTO TABLE fact_sales
  CHARACTER SET utf8mb4
  FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
  LINES TERMINATED BY '\n'
  (store_id, item_id, d_key, units);

-- fact_sales_part_03.csv
LOAD DATA INFILE 'C:/ProgramData/MySQL/MySQL Server 8.0/Uploads/_stage/fact_sales_part_03.csv'
  INTO TABLE fact_sales
  CHARACTER SET utf8mb4
  FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
  LINES TERMINATED BY '\n'
  (store_id, item_id, d_key, units);

-- fact_sales_part_04.csv
LOAD DATA INFILE 'C:/ProgramData/MySQL/MySQL Server 8.0/Uploads/_stage/fact_sales_part_04.csv'
  INTO TABLE fact_sales
  CHARACTER SET utf8mb4
  FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
  LINES TERMINATED BY '\n'
  (store_id, item_id, d_key, units);

-- fact_sales_part_05.csv
LOAD DATA INFILE 'C:/ProgramData/MySQL/MySQL Server 8.0/Uploads/_stage/fact_sales_part_05.csv'
  INTO TABLE fact_sales
  CHARACTER SET utf8mb4
  FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
  LINES TERMINATED BY '\n'
  (store_id, item_id, d_key, units);

-- fact_sales_part_06.csv
LOAD DATA INFILE 'C:/ProgramData/MySQL/MySQL Server 8.0/Uploads/_stage/fact_sales_part_06.csv'
  INTO TABLE fact_sales
  CHARACTER SET utf8mb4
  FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
  LINES TERMINATED BY '\n'
  (store_id, item_id, d_key, units);

-- fact_sales_part_07.csv
LOAD DATA INFILE 'C:/ProgramData/MySQL/MySQL Server 8.0/Uploads/_stage/fact_sales_part_07.csv'
  INTO TABLE fact_sales
  CHARACTER SET utf8mb4
  FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
  LINES TERMINATED BY '\n'
  (store_id, item_id, d_key, units);

-- fact_sales_part_08.csv
LOAD DATA INFILE 'C:/ProgramData/MySQL/MySQL Server 8.0/Uploads/_stage/fact_sales_part_08.csv'
  INTO TABLE fact_sales
  CHARACTER SET utf8mb4
  FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
  LINES TERMINATED BY '\n'
  (store_id, item_id, d_key, units);

-- fact_sales_part_09.csv
LOAD DATA INFILE 'C:/ProgramData/MySQL/MySQL Server 8.0/Uploads/_stage/fact_sales_part_09.csv'
  INTO TABLE fact_sales
  CHARACTER SET utf8mb4
  FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
  LINES TERMINATED BY '\n'
  (store_id, item_id, d_key, units);

-- fact_sales_part_10.csv
LOAD DATA INFILE 'C:/ProgramData/MySQL/MySQL Server 8.0/Uploads/_stage/fact_sales_part_10.csv'
  INTO TABLE fact_sales
  CHARACTER SET utf8mb4
  FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
  LINES TERMINATED BY '\n'
  (store_id, item_id, d_key, units);

-- fact_sales_part_11.csv
LOAD DATA INFILE 'C:/ProgramData/MySQL/MySQL Server 8.0/Uploads/_stage/fact_sales_part_11.csv'
  INTO TABLE fact_sales
  CHARACTER SET utf8mb4
  FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
  LINES TERMINATED BY '\n'
  (store_id, item_id, d_key, units);

-- fact_sales_part_12.csv
LOAD DATA INFILE 'C:/ProgramData/MySQL/MySQL Server 8.0/Uploads/_stage/fact_sales_part_12.csv'
  INTO TABLE fact_sales
  CHARACTER SET utf8mb4
  FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
  LINES TERMINATED BY '\n'
  (store_id, item_id, d_key, units);

-- fact_sales_part_13.csv
LOAD DATA INFILE 'C:/ProgramData/MySQL/MySQL Server 8.0/Uploads/_stage/fact_sales_part_13.csv'
  INTO TABLE fact_sales
  CHARACTER SET utf8mb4
  FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
  LINES TERMINATED BY '\n'
  (store_id, item_id, d_key, units);

-- fact_sales_part_14.csv
LOAD DATA INFILE 'C:/ProgramData/MySQL/MySQL Server 8.0/Uploads/_stage/fact_sales_part_14.csv'
  INTO TABLE fact_sales
  CHARACTER SET utf8mb4
  FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
  LINES TERMINATED BY '\n'
  (store_id, item_id, d_key, units);

-- fact_sales_part_15.csv
LOAD DATA INFILE 'C:/ProgramData/MySQL/MySQL Server 8.0/Uploads/_stage/fact_sales_part_15.csv'
  INTO TABLE fact_sales
  CHARACTER SET utf8mb4
  FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
  LINES TERMINATED BY '\n'
  (store_id, item_id, d_key, units);

-- fact_sales_part_16.csv
LOAD DATA INFILE 'C:/ProgramData/MySQL/MySQL Server 8.0/Uploads/_stage/fact_sales_part_16.csv'
  INTO TABLE fact_sales
  CHARACTER SET utf8mb4
  FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
  LINES TERMINATED BY '\n'
  (store_id, item_id, d_key, units);

-- ---------------------------------------------------------------------------
-- 4. 更新统计信息，优化器才会选对索引
-- ---------------------------------------------------------------------------
ANALYZE TABLE dim_date, dim_item, dim_store, fact_sales, fact_price;

-- 行数自检：应分别为 1969 / 3049 / 10 / 59181090 / 6841121
SELECT 'dim_date'   AS tbl, COUNT(*) AS rows_ FROM dim_date
UNION ALL SELECT 'dim_item',   COUNT(*) FROM dim_item
UNION ALL SELECT 'dim_store',  COUNT(*) FROM dim_store
UNION ALL SELECT 'fact_sales', COUNT(*) FROM fact_sales
UNION ALL SELECT 'fact_price', COUNT(*) FROM fact_price;
