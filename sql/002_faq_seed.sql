-- Sample English FAQs. The RAG documents remain the authoritative policies.
SET NAMES utf8mb4;

DELETE FROM faq WHERE question IN (
  'What is the return policy?', 'How do I request a refund?', 'How do exchanges work?',
  'When will my order ship?', 'How much is shipping?', 'How do I get an itemized receipt?'
);
INSERT INTO faq (question, answer, category) VALUES
  ('What is the return policy?', 'Standard returns may be requested within 30 days of delivery, subject to item condition and policy exclusions. Litter boxes have a separate 60-day trial; consult the current policy for eligibility.', 'returns'),
  ('How do I request a refund?', 'Select your order and submit a refund request. Eligibility and the final refund require review; submitting a request does not execute a payment.', 'returns'),
  ('How do exchanges work?', 'Contact support to review the item and available options. A request does not confirm replacement stock or shipment.', 'returns'),
  ('When will my order ship?', 'In-stock orders normally ship in 1-2 business days after payment confirmation. Standard transit is estimated at 3-5 business days after carrier pickup.', 'shipping'),
  ('How much is shipping?', 'Standard shipping is free at a merchandise subtotal of $49 after discounts and rewards, before sales tax; otherwise it is $4.95 for supported destinations.', 'shipping'),
  ('How do I get an itemized receipt?', 'View your order details or ask support for an itemized receipt showing merchandise, discounts, shipping, sales tax, and total.', 'billing');
SELECT COUNT(*) AS faq_rows FROM faq;
