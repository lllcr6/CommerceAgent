-- Tool audit tables.
-- =============================================================
-- =============================================================

SET NAMES utf8mb4;

CREATE TABLE tool_audit_logs (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  conversation_id BIGINT UNSIGNED NULL,
  tool_call_id    VARCHAR(64)     NULL,
  tool_name       VARCHAR(128)    NOT NULL,
  tool_source     ENUM('builtin','mcp') NOT NULL,
  mcp_server      VARCHAR(64)     NULL,
  arguments       JSON            NULL,
  result_summary  TEXT            NULL,
  status          ENUM('success','failure','timeout','validation_blocked','permission_denied') NOT NULL,
  error_message   VARCHAR(512)    NULL,
  retry_count     TINYINT UNSIGNED NOT NULL DEFAULT 0,
  duration_ms     INT UNSIGNED    NULL,
  created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_conversation_id (conversation_id),
  KEY idx_tool_name (tool_name),
  KEY idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
