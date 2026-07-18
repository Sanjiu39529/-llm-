CREATE TABLE IF NOT EXISTS behavior_funnel (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    new_user BOOLEAN NULL,
    age INT NULL,
    sex VARCHAR(64) NULL,
    market INT NULL,
    device VARCHAR(64) NULL,
    operative_system VARCHAR(64) NULL,
    source VARCHAR(64) NULL,
    total_pages_visited INT NOT NULL,
    home_page INT NULL,
    listing_page INT NULL,
    product_page INT NULL,
    payment_page INT NULL,
    confirmation_page INT NULL,
    import_batch_id BIGINT UNSIGNED NOT NULL,
    INDEX idx_behavior_funnel_source (source),
    INDEX idx_behavior_funnel_device (device)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
