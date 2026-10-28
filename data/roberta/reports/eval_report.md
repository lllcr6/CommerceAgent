# English topic classifier: held-out test evaluation

Test examples: 560. Threshold: 0.35 (selected on validation only). Synthetic draft labels; independent review pending.

**micro**: P=0.916 R=0.710 F1=0.800  |  **macro**: P=0.899 R=0.684 F1=0.767

## Per-topic metrics (planning targets: strict F1 >= 0.9; standard >= 0.8; flexible: no target)

| Topic | Tier | P | R | F1 | Support | Target |
|---|---|---|---|---|---|---|
| returns_refunds | strict | 0.900 | 0.720 | 0.800 | 50 | 0.9 Below target: review data |
| delivery_tracking | strict | 0.778 | 0.525 | 0.627 | 40 | 0.9 Below target: review data |
| size_fit | strict | 0.923 | 0.600 | 0.727 | 40 | 0.9 Below target: review data |
| receipts_invoices | strict | 0.951 | 0.650 | 0.772 | 60 | 0.9 Below target: review data |
| product_defect | strict | 0.775 | 0.775 | 0.775 | 40 | 0.9 Below target: review data |
| shipping_fees | standard | 0.966 | 0.950 | 0.958 | 60 | 0.8 Pass |
| promotions | standard | 1.000 | 0.650 | 0.788 | 40 | 0.8 Below target: review data |
| price_adjustments | standard | 0.938 | 0.750 | 0.833 | 40 | 0.8 Pass |
| payments | standard | 0.956 | 0.717 | 0.819 | 60 | 0.8 Pass |
| order_changes | standard | 0.894 | 0.700 | 0.785 | 60 | 0.8 Below target: review data |
| stock_availability | standard | 0.938 | 0.500 | 0.652 | 30 | 0.8 Below target: review data |
| product_information | standard | 0.588 | 0.333 | 0.426 | 30 | 0.8 Below target: review data |
| warranty_repairs | standard | 0.983 | 0.950 | 0.966 | 60 | 0.8 Pass |
| account_access | flexible | 0.824 | 0.350 | 0.491 | 40 | — |
| loyalty_rewards | flexible | 0.929 | 0.975 | 0.951 | 40 | — |
| reviews_feedback | flexible | 1.000 | 0.920 | 0.958 | 50 | — |
| other | flexible | 0.944 | 0.567 | 0.708 | 30 | — |

## Per-topic confusion matrices (TN FP / FN TP)

- **returns_refunds**: TN=506 FP=4 FN=14 TP=36
- **delivery_tracking**: TN=514 FP=6 FN=19 TP=21
- **size_fit**: TN=518 FP=2 FN=16 TP=24
- **receipts_invoices**: TN=498 FP=2 FN=21 TP=39
- **product_defect**: TN=511 FP=9 FN=9 TP=31
- **shipping_fees**: TN=498 FP=2 FN=3 TP=57
- **promotions**: TN=520 FP=0 FN=14 TP=26
- **price_adjustments**: TN=518 FP=2 FN=10 TP=30
- **payments**: TN=498 FP=2 FN=17 TP=43
- **order_changes**: TN=495 FP=5 FN=18 TP=42
- **stock_availability**: TN=529 FP=1 FN=15 TP=15
- **product_information**: TN=523 FP=7 FN=20 TP=10
- **warranty_repairs**: TN=499 FP=1 FN=3 TP=57
- **account_access**: TN=517 FP=3 FN=26 TP=14
- **loyalty_rewards**: TN=517 FP=3 FN=1 TP=39
- **reviews_feedback**: TN=510 FP=0 FN=4 TP=46
- **other**: TN=529 FP=1 FN=13 TP=17