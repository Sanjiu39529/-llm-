-- 电商数据 MySQL 8 模式，所有业务表通过 import_batch_id 保留导入追溯。
CREATE TABLE IF NOT EXISTS import_batch (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    source_name VARCHAR(255) NOT NULL,
    table_name VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    field_mapping JSON NOT NULL,
    quality_summary JSON NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME NULL,
    INDEX idx_import_batch_table_created (table_name, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS metric_config (
    config_key VARCHAR(100) PRIMARY KEY,
    config_value VARCHAR(255) NOT NULL,
    description VARCHAR(500) NOT NULL,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS user_info (
    user_id VARCHAR(64) PRIMARY KEY,
    user_name VARCHAR(255) NULL,
    phone VARCHAR(64) NULL,
    email VARCHAR(255) NULL,
    register_time DATETIME NULL,
    import_batch_id BIGINT UNSIGNED NOT NULL,
    INDEX idx_user_info_batch_user (import_batch_id, user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS order_info (
    order_id VARCHAR(64) PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL,
    order_time DATETIME NOT NULL,
    channel VARCHAR(64) NULL,
    order_status VARCHAR(64) NULL,
    order_amount DECIMAL(18,2) NULL,
    import_batch_id BIGINT UNSIGNED NOT NULL,
    INDEX idx_order_info_user_time (user_id, order_time),
    INDEX idx_order_info_channel_time (channel, order_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS payment_info (
    payment_id VARCHAR(64) NULL,
    order_id VARCHAR(64) NOT NULL,
    paid_at DATETIME NOT NULL,
    payment_amount DECIMAL(18,2) NOT NULL,
    payment_method VARCHAR(64) NULL,
    payment_status VARCHAR(64) NULL,
    import_batch_id BIGINT UNSIGNED NOT NULL,
    INDEX idx_payment_info_order_paid (order_id, paid_at),
    INDEX idx_payment_info_batch_paid (import_batch_id, paid_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS refund_info (
    refund_id VARCHAR(64) NULL,
    order_id VARCHAR(64) NOT NULL,
    refund_amount DECIMAL(18,2) NOT NULL,
    refunded_at DATETIME NOT NULL,
    refund_reason VARCHAR(255) NULL,
    refund_status VARCHAR(64) NULL,
    import_batch_id BIGINT UNSIGNED NOT NULL,
    INDEX idx_refund_info_order_refunded (order_id, refunded_at),
    INDEX idx_refund_info_batch_refunded (import_batch_id, refunded_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS traffic_visit (
    visit_id VARCHAR(64) PRIMARY KEY,
    visited_at DATETIME NOT NULL,
    user_id VARCHAR(64) NULL,
    channel VARCHAR(64) NULL,
    page_url VARCHAR(2048) NULL,
    import_batch_id BIGINT UNSIGNED NOT NULL,
    INDEX idx_traffic_visit_user_time (user_id, visited_at),
    INDEX idx_traffic_visit_channel_time (channel, visited_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS ad_attribution (
    order_id VARCHAR(64) NOT NULL,
    ad_id VARCHAR(64) NOT NULL,
    attributed_at DATETIME NOT NULL,
    user_id VARCHAR(64) NULL,
    attribution_amount DECIMAL(18,2) NULL,
    import_batch_id BIGINT UNSIGNED NOT NULL,
    PRIMARY KEY (order_id, ad_id, attributed_at),
    INDEX idx_ad_attribution_ad_time (ad_id, attributed_at),
    INDEX idx_ad_attribution_user_time (user_id, attributed_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
