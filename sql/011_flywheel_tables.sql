-- Flywheel tables.
-- =============================================================
-- =============================================================

SET NAMES utf8mb4;

CREATE TABLE review_queue (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  normalized_question VARCHAR(512)    NOT NULL,
  ai_suggested_answer TEXT            NULL,
  occurrence_count    INT UNSIGNED    NOT NULL DEFAULT 1,
  review_status       ENUM('pending','approved','rejected') NOT NULL DEFAULT 'pending',
  approved_answer     TEXT            NULL,
  created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_review_status (review_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE eval_runs (
  id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  triggered_by ENUM('scheduled','manual') NOT NULL DEFAULT 'scheduled',
  dataset_size INT UNSIGNED    NOT NULL,
  metrics      JSON            NOT NULL,
  created_at   DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

ALTER TABLE low_confidence_questions
  ADD COLUMN retrieved_chunks  JSON            NULL AFTER reason,
  ADD COLUMN matched_review_id BIGINT UNSIGNED NULL AFTER retrieved_chunks,
  ADD KEY idx_matched_review_id (matched_review_id),
  ADD CONSTRAINT fk_lcq_review FOREIGN KEY (matched_review_id) REFERENCES review_queue (id) ON DELETE SET NULL;
