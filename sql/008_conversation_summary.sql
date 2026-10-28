-- Conversation summary.
-- =============================================================
-- =============================================================

SET NAMES utf8mb4;

ALTER TABLE conversations
  ADD COLUMN summary             TEXT            NULL AFTER status,
  ADD COLUMN summary_upto_msg_id BIGINT UNSIGNED NULL AFTER summary;
