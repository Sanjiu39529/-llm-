-- 仅用于从早期 Phase 1 版本的 001_schema.sql 一次性升级。
-- 执行前应先备份，并清理 payment/refund 完整业务键重复数据。

ALTER TABLE import_batch
    ADD COLUMN error_code VARCHAR(64) NULL AFTER quality_summary;

ALTER TABLE user_info
    ADD COLUMN age INT NULL AFTER register_time;

ALTER TABLE product_info
    ADD COLUMN is_outlier BOOLEAN NOT NULL DEFAULT FALSE AFTER stock;

ALTER TABLE order_info
    ADD COLUMN is_outlier BOOLEAN NOT NULL DEFAULT FALSE AFTER order_amount;

ALTER TABLE order_item
    ADD COLUMN is_outlier BOOLEAN NOT NULL DEFAULT FALSE AFTER item_amount;

ALTER TABLE payment_info
    ADD COLUMN is_outlier BOOLEAN NOT NULL DEFAULT FALSE AFTER payment_status,
    ADD UNIQUE KEY uq_payment_info_id (payment_id),
    ADD UNIQUE KEY uq_payment_info_business_key (order_id, paid_at, payment_amount);

ALTER TABLE refund_info
    ADD COLUMN is_outlier BOOLEAN NOT NULL DEFAULT FALSE AFTER refund_status,
    ADD UNIQUE KEY uq_refund_info_id (refund_id),
    ADD UNIQUE KEY uq_refund_info_business_key (order_id, refunded_at, refund_amount);

ALTER TABLE ads_info
    ADD COLUMN is_outlier BOOLEAN NOT NULL DEFAULT FALSE AFTER cost;

ALTER TABLE ad_attribution
    ADD COLUMN is_outlier BOOLEAN NOT NULL DEFAULT FALSE AFTER attribution_amount;
