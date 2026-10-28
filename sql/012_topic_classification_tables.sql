-- Topic classification tables.
-- =============================================================
-- =============================================================

SET NAMES utf8mb4;

CREATE TABLE topic_classifications (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  question_id   BIGINT UNSIGNED NOT NULL,
  labels        JSON            NOT NULL,
  classified_at DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_question_id (question_id),
  CONSTRAINT fk_topic_question FOREIGN KEY (question_id) REFERENCES low_confidence_questions (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
