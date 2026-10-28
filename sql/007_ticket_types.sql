-- Ticket types.

SET NAMES utf8mb4;

ALTER TABLE tickets
  MODIFY COLUMN ticket_type ENUM('after_sales','complaint','question','refund') NOT NULL;
