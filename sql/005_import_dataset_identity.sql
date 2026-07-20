-- Phase A1：为导入批次增加稳定的数据集身份和可复用的文件指纹。
-- 旧批次无法凭空恢复原文件哈希，因此允许 file_hash 为空。

ALTER TABLE import_batch
    ADD COLUMN dataset_id CHAR(36) NULL AFTER id,
    ADD COLUMN file_hash CHAR(64) NULL AFTER source_name,
    ADD COLUMN file_size BIGINT UNSIGNED NULL AFTER file_hash,
    ADD COLUMN processed_rows BIGINT UNSIGNED NOT NULL DEFAULT 0 AFTER quality_summary,
    ADD COLUMN written_rows BIGINT UNSIGNED NOT NULL DEFAULT 0 AFTER processed_rows,
    ADD COLUMN skipped_rows BIGINT UNSIGNED NOT NULL DEFAULT 0 AFTER written_rows,
    ADD COLUMN last_accessed_at DATETIME NULL AFTER completed_at;

UPDATE import_batch
SET dataset_id = UUID()
WHERE dataset_id IS NULL;

ALTER TABLE import_batch
    MODIFY COLUMN dataset_id CHAR(36) NOT NULL,
    ADD UNIQUE KEY uq_import_batch_dataset_id (dataset_id),
    ADD UNIQUE KEY uq_import_batch_file_hash (file_hash);
