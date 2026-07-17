-- 为已有业务表追加第二阶段统一指标所需的可选源字段。
ALTER TABLE payment_info
    ADD COLUMN coupon_discount DECIMAL(18,2) NULL,
    ADD COLUMN promotion_discount DECIMAL(18,2) NULL,
    ADD COLUMN shipping_fee DECIMAL(18,2) NULL;

ALTER TABLE refund_info
    ADD COLUMN refund_quantity INT NULL;

ALTER TABLE traffic_visit
    ADD COLUMN device_id VARCHAR(64) NULL;

ALTER TABLE ad_attribution
    ADD COLUMN attribution_type VARCHAR(64) NULL;
