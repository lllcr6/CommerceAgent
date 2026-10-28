-- English sample conversations for optional knowledge-draft extraction.
-- Reuse seed conversations on repeated runs; never delete linked business history.
SET NAMES utf8mb4;
INSERT INTO conversations (user_id, status)
SELECT 'seed-u1', 'closed' WHERE NOT EXISTS (SELECT 1 FROM conversations WHERE user_id = 'seed-u1');
INSERT INTO conversations (user_id, status)
SELECT 'seed-u2', 'closed' WHERE NOT EXISTS (SELECT 1 FROM conversations WHERE user_id = 'seed-u2');
SET @c1 = (SELECT id FROM conversations WHERE user_id = 'seed-u1' ORDER BY id DESC LIMIT 1);
SET @c2 = (SELECT id FROM conversations WHERE user_id = 'seed-u2' ORDER BY id DESC LIMIT 1);
INSERT INTO messages (conversation_id, role, content)
SELECT @c1, 'user', 'When do in-stock orders ship?'
WHERE NOT EXISTS (SELECT 1 FROM messages WHERE conversation_id = @c1 AND role = 'user');
INSERT INTO messages (conversation_id, role, content)
SELECT @c1, 'assistant', 'In-stock orders normally ship in 1-2 business days after payment confirmation. Standard transit is estimated at 3-5 business days after carrier pickup.'
WHERE NOT EXISTS (SELECT 1 FROM messages WHERE conversation_id = @c1 AND role = 'assistant');
INSERT INTO messages (conversation_id, role, content)
SELECT @c2, 'user', 'What is the free shipping threshold?'
WHERE NOT EXISTS (SELECT 1 FROM messages WHERE conversation_id = @c2 AND role = 'user');
INSERT INTO messages (conversation_id, role, content)
SELECT @c2, 'assistant', 'Standard shipping is free when merchandise totals at least $49 after discounts and rewards, before sales tax. Otherwise it is $4.95 for supported destinations.'
WHERE NOT EXISTS (SELECT 1 FROM messages WHERE conversation_id = @c2 AND role = 'assistant');
SELECT COUNT(*) AS sample_messages FROM messages WHERE conversation_id IN (@c1, @c2);
