-- Knowledge review.
-- =============================================================
-- =============================================================
--
--
-- =============================================================

SET NAMES utf8mb4;

ALTER TABLE qa_extraction_staging
  MODIFY COLUMN status ENUM('extracted','kept','discarded','approved','rejected')
    NOT NULL DEFAULT 'extracted';

--
UPDATE qa_extraction_staging
   SET status = 'approved'
 WHERE status = 'kept' AND created_at < '2026-08-16';
