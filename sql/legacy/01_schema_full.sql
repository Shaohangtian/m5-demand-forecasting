-- ============================================================================
-- M5 供应链需求预测项目 —— MySQL 8.0 建表脚本
--
-- 设计要点
--   1. 原始 sales_*.csv 是"宽表"（30490 行 x 1941 个 d_N 列），无法直接建表，
--      这里统一转成"长表"事实表 fact_sales（5918 万行）。
--   2. 事实表主键顺序 (store_id, item_id, d_key) 与源文件的物理行序一致，
--      LOAD DATA 时是顺序追加写，导入速度最快，也便于按门店+商品点查。
--   3. 所有字符串字段均为纯 ASCII，utf8mb4 只影响排序规则，不额外占空间；
--      保留 utf8mb4 是为了后续可以加中文备注/中文维度名。
--   4. 不建外键：5918 万行规模下外键约束会让导入慢数倍，完整性交给校验脚本。
--
-- 执行方式：mysql -u root -p --default-character-set=utf8mb4 < sql/01_schema.sql
--          或由 src/01_load_mysql.py 自动执行
-- ============================================================================

SET NAMES utf8mb4;

CREATE DATABASE IF NOT EXISTS m5_demand
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_0900_ai_ci;

USE m5_demand;

-- 注意：下面 5 行会删表重建，重复执行等于清空重导。
DROP TABLE IF EXISTS fact_price;
DROP TABLE IF EXISTS fact_sales;
DROP TABLE IF EXISTS dim_date;
DROP TABLE IF EXISTS dim_item;
DROP TABLE IF EXISTS dim_store;

-- ----------------------------------------------------------------------------
-- 1. 日历维表：calendar.csv  ->  1969 行
-- ----------------------------------------------------------------------------
CREATE TABLE dim_date (
  d_key        SMALLINT UNSIGNED NOT NULL COMMENT 'd_1 -> 1，与 sales 表的 d_N 列一一对应',
  d            VARCHAR(8)        NOT NULL COMMENT '原始列名，如 d_1941',
  `date`       DATE              NOT NULL,
  wm_yr_wk     SMALLINT UNSIGNED NOT NULL COMMENT '沃尔玛财务周(年+周)，关联 fact_price',
  weekday      VARCHAR(10)       NOT NULL COMMENT 'Saturday..Friday',
  wday         TINYINT UNSIGNED  NOT NULL COMMENT '1=周六, 7=周五（M5 原始定义）',
  `month`      TINYINT UNSIGNED  NOT NULL,
  `year`       SMALLINT UNSIGNED NOT NULL,
  event_name_1 VARCHAR(40)       NULL COMMENT '主要事件名',
  event_type_1 VARCHAR(20)       NULL COMMENT 'Cultural/National/Religious/Sporting',
  event_name_2 VARCHAR(40)       NULL,
  event_type_2 VARCHAR(20)       NULL,
  snap_ca      TINYINT UNSIGNED  NOT NULL DEFAULT 0 COMMENT 'CA 州 SNAP 日标记',
  snap_tx      TINYINT UNSIGNED  NOT NULL DEFAULT 0 COMMENT 'TX 州 SNAP 日标记',
  snap_wi      TINYINT UNSIGNED  NOT NULL DEFAULT 0 COMMENT 'WI 州 SNAP 日标记',
  PRIMARY KEY (d_key),
  UNIQUE KEY uk_dim_date_date (`date`),
  KEY idx_dim_date_wm_yr_wk (wm_yr_wk)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '日历维表（calendar.csv）';

-- ----------------------------------------------------------------------------
-- 2. 商品维表：sales 文件维度列去重  ->  3049 行
-- ----------------------------------------------------------------------------
CREATE TABLE dim_item (
  item_id VARCHAR(20) NOT NULL COMMENT '如 HOBBIES_1_001',
  dept_id VARCHAR(20) NOT NULL COMMENT '如 HOBBIES_1（7 个）',
  cat_id  VARCHAR(20) NOT NULL COMMENT '如 HOBBIES（3 个）',
  PRIMARY KEY (item_id),
  KEY idx_dim_item_dept (dept_id),
  KEY idx_dim_item_cat (cat_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '商品维表（3 大类 / 7 部门 / 3049 商品）';

-- ----------------------------------------------------------------------------
-- 3. 门店维表  ->  10 行
-- ----------------------------------------------------------------------------
CREATE TABLE dim_store (
  store_id VARCHAR(10) NOT NULL COMMENT '如 CA_1',
  state_id VARCHAR(5)  NOT NULL COMMENT 'CA / TX / WI',
  PRIMARY KEY (store_id),
  KEY idx_dim_store_state (state_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '门店维表（3 州 / 10 店）';

-- ----------------------------------------------------------------------------
-- 4. 日销量事实表：sales_train_evaluation.csv 宽转长  ->  5918 万行
--    5918 万 = 30490 (门店x商品) x 1941 天
--    units 最大 763，SMALLINT UNSIGNED 足够；MySQL 没有更小的整型，无需 INT
-- ----------------------------------------------------------------------------
CREATE TABLE fact_sales (
  store_id VARCHAR(10)       NOT NULL,
  item_id  VARCHAR(20)       NOT NULL,
  d_key    SMALLINT UNSIGNED NOT NULL COMMENT '关联 dim_date.d_key',
  units    SMALLINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '当日销量',
  PRIMARY KEY (store_id, item_id, d_key),
  KEY idx_fact_sales_d (d_key)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '日销量事实表（长表，仅 evaluation 文件）';

-- ----------------------------------------------------------------------------
-- 5. 周价格事实表：sell_prices.csv  ->  684 万行
-- ----------------------------------------------------------------------------
CREATE TABLE fact_price (
  store_id   VARCHAR(10)       NOT NULL,
  item_id    VARCHAR(20)       NOT NULL,
  wm_yr_wk   SMALLINT UNSIGNED NOT NULL COMMENT '关联 dim_date.wm_yr_wk',
  sell_price DECIMAL(8, 2)     NOT NULL COMMENT '周售价，最大值 107.32',
  PRIMARY KEY (store_id, item_id, wm_yr_wk),
  KEY idx_fact_price_wk (wm_yr_wk)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '周售价事实表（sell_prices.csv）';

-- ----------------------------------------------------------------------------
-- 6. 便捷视图：把 d_key 还原成日期，并带上部门/品类
--    注意：底层 5918 万行，按日期范围过滤后会很快，全表扫仍然慢。
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_sales_daily AS
SELECT s.store_id,
       s.item_id,
       i.dept_id,
       i.cat_id,
       s.d_key,
       d.`date`,
       d.wm_yr_wk,
       s.units
FROM fact_sales s
JOIN dim_date d ON d.d_key   = s.d_key
JOIN dim_item i ON i.item_id = s.item_id;
