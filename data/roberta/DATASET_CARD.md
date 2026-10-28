# Paw & Hearth English topic dataset

Release: `paw-topics-en-v1`. Status: **synthetic draft; independent review required**.

This is a 17-label multi-label topic dataset for English U.S. cat/dog retail support. It is separate from the Agent's live intent-routing task. No classifier was trained, evaluated, or deployed to build this release.

## Composition

| Partition | Messages | Scenario families | Multilabel messages |
| --- | ---: | ---: | ---: |
| train | 2,735 | 274 | 200 |
| val | 547 | 55 | 150 |
| test | 560 | 56 | 210 |

Total: **3,842 messages across 385 retained families**. The candidate pool contained 400 families and 4,000 messages: two assistant-authored anchors and eight model-generated expressions per family. These variants are dependent observations, not 4,000 independent scenarios.

## Leakage controls

- Whole source families and lexically related groups were assigned before expression generation.
- Each stateless writer request contains only families from one partition. The writer never receives protected RAG/Agent evaluation questions.
- Exact normalization and lexical near-duplicate checks compare all partitions and protected evaluation questions.
- A separate model screened 98 candidate source-family/evaluation comparisons. Same-request, uncertain, and unavailable comparisons are excluded conservatively. This is candidate screening, not exhaustive semantic certification.
- Fifteen implicated families were removed in full. Separate conservative annotation-drift flags excluded eight additional retained-family messages. Nine messages were flagged overall; one was already inside an excluded family.
- Partition file hashes and source/generation/audit hashes are frozen in `dataset/manifest.json`. Re-exporting unchanged inputs is idempotent. Changed inputs or altered frozen files are rejected.
- Only `text` may enter the classifier. Labels are targets; family/group/split/source metadata must never be model inputs.

No retained family or related group crosses partitions. No normalized text crosses partitions, and no retained pair exceeds the configured lexical rejection threshold. These checks do not prove that every possible semantic paraphrase has been ruled out.

## Label coverage

| Label | Train positives | Validation positives | Test positives |
| --- | ---: | ---: | ---: |
| returns_refunds | 180 | 59 | 50 |
| delivery_tracking | 200 | 70 | 40 |
| size_fit | 210 | 40 | 40 |
| receipts_invoices | 170 | 39 | 60 |
| product_defect | 170 | 60 | 40 |
| shipping_fees | 170 | 30 | 60 |
| promotions | 200 | 40 | 40 |
| price_adjustments | 130 | 49 | 40 |
| payments | 159 | 50 | 60 |
| order_changes | 190 | 30 | 60 |
| stock_availability | 189 | 40 | 30 |
| product_information | 180 | 30 | 30 |
| warranty_repairs | 150 | 30 | 60 |
| account_access | 179 | 30 | 40 |
| loyalty_rewards | 198 | 20 | 40 |
| reviews_feedback | 120 | 50 | 50 |
| other | 140 | 30 | 30 |

All 17 labels occur in every partition. Test has at least 30 positives per label. Validation `loyalty_rewards` has 20 after contamination exclusions; that estimate will be less stable. Counts include dependent variants. Do not infer equivalent independent sample sizes.

## Provenance and usage

Writer: `qwen3.8-flash`, temperature 0.8, thinking disabled. Semantic overlap screener: `qwen3.7-flash`, temperature 0, thinking disabled. No customer conversation was imported. Scenario labels were fixed before model generation. There is no independent human gold annotation.

| Stage | Recorded input tokens | Recorded output tokens |
| --- | ---: | ---: |
| generation | 239,176 | 84,071 |
| semantic_screen | 14,424 | 12,840 |

Usage includes returned provider counts from format-failed attempts as well as successful work. Requests interrupted without returned usage may be absent. Token counts are not a provider invoice; cache pricing and unknown billing are not inferred.

## Limitations and appropriate use

- This is a synthetic development benchmark, not production traffic. A shared generator can create common style across partitions.
- Inherited scenario labels can drift when a generated sentence adds a request. Conservative rules flag some such cases; they are not a substitute for independent annotation.
- The overlap screener is also an LLM and can overexclude or miss equivalences. Its decisions are preserved for review, not treated as human truth.
- The release remains a draft pending independent semantic review and label checks. Do not claim audited leakage-free data, human-gold test accuracy, or production generalization.
- Training selection, early stopping, thresholds, and prompt experiments use train/validation only. If test errors are used to add training cases, retire that test set as an independent final benchmark.
- Use family-level resampling for confidence intervals. Multiple expressions from the same family are not independent trials.
- The English training pipeline uses pinned FacebookAI/roberta-base weights, this release’s 17 English IDs, and validation-only epoch/threshold selection. ONNX parity checks use validation texts; held-out test examples are reserved for final evaluation. No production training or deployment has been run.

## Review artifacts

`reports/dataset_audit.json` lists all family exclusions, conservative annotation flags, lower-score lexical candidates, and checks. `source/semantic_review.json` preserves the candidate comparisons and screener decisions. Quarantined text remains in the source/generation provenance, not in exported partitions. Do not pass audit text or test examples to the training-data writer.

For a new release, preserve these frozen files and use separate versioned sources, split plan, generation checkpoint, and export directory. Do not delete the manifest to bypass its checks.
