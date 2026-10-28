# Paw & Hearth English topic annotation

This is a **17-label, multi-label topic task**, separate from the live Agent's
intent routing. The authoritative English IDs, fixed index order, display names,
and definitions are in [labels.json](labels.json).

## Unit and rules

Annotate one standalone English customer message. Select every **explicit request
or actual reported issue**, not every noun mentioned. Negated requests and
hypothetical consequences do not create extra labels. Do not infer a refund from
a defect, a defect from a general warranty question, or an account request from
the mere mention of an account.

- "The clasp is broken." → `product_defect`.
- "The clasp is broken; can it be repaired under warranty?" →
  `product_defect`, `warranty_repairs`.
- "The jacket is too small." → `size_fit`.
- "The jacket is too small; I want an exchange." → `size_fit`, `returns_refunds`.
- "Where is the parcel?" → `delivery_tracking`.
- "Does the delivery surcharge apply?" → `shipping_fees`.
- "Does this coupon work?" → `promotions`.
- "The price fell after I bought it; can I get the difference?" → `price_adjustments`.
- "Where does my refund go if my payment card is closed?" → `returns_refunds`;
  the payment card is context, not a separate checkout/payment-management request.
- "I want to skip the upcoming order, not delete my account." → `order_changes`.
- "Could a person take over?" → `other`.

`other` is an **exclusive fallback**. A message containing a recognized topic and
a request for a human retains the recognized topic; do not add `other`.
Missing or failed annotations must be quarantined, never converted to `other`.

Classify requests for an unsupported service by their topic when it is explicit.
A question about competitor price protection is still `price_adjustments`, even
if the store does not offer it. The classifier is not deciding eligibility or
answering policy questions. Medical advice, adoption, legal help, and unrelated
services belong to `other`; the dataset contains questions, not advice.

U.S. examples use itemized/gift receipts, card/wallet payments, ZIP codes, U.S.
shipping terminology, and cat/dog supplies.

## Source families and split isolation

The source catalog defines 400 semantic scenario families, each with two authored
anchor expressions. Extra natural expressions are generated **within an already
assigned family and partition**. Product substitutions, spelling variants, tone
changes, or paraphrases are not independent scenarios and never get a new split.
Related source families found by lexical screening share a `group_id`.

The split plan is selected before generation: about 70% train, 15% validation,
15% test by whole family groups, with multilabel coverage. No generation request
receives messages from a different partition. The writer never receives the RAG
question set or Agent benchmark prompts. They are read only by the subsequent
contamination audit.

This release does **not** create post-split training augmentation or tune a model.
The additional expressions in validation/test are synthetic source-family members,
not transformations of training messages. They are still dependent observations;
report family counts alongside sample counts and use family-level resampling if
confidence intervals are computed.

## Checks and review

The offline audit checks family/group intersection, normalized exact copies,
lexical TF-IDF cosine near duplicates, and overlap with protected RAG/Agent
questions. Known contractions, quantities, and selected lexical aliases are
normalized only for this audit. The audit vectors are **not classifier features**
and must not be reused as training preprocessing.

A separate configured model screens likely semantic overlaps; same-request and
uncertain matches are excluded conservatively. This candidate screen is neither
exhaustive nor independent human gold. At the lexical rejection threshold, the entire implicated semantic family and its planned
related group are quarantined. Their messages are omitted from all exported
partitions; quarantine is never done in response to model performance. Lower-score
cross-split pairs are queued for independent review. Lexical similarity does not
rule out every semantic paraphrase. Keep the synthetic/draft designation until
independent annotation and semantic review are complete.

Conservative annotation-drift rules also quarantine a few individual messages.
Their flags can be false positives; they never silently rewrite a label. These
exclusions and a stratified annotation sample are available in `reports/`.

The label definitions were authored before generating expressions. Generated
expressions inherit their scenario labels; this can introduce drift. Review every
flagged case and independently sample all labels and splits. Check for added or
negated requests, ambiguous wording, and multi-label omissions. Do not treat the
same generator's agreement as independent human validation.

## Freeze and training contract

The export manifest freezes source/split/generation hashes and the exact three
files. Rerunning an unchanged export is idempotent. Changed inputs or altered
frozen files cause an error; issue a new version rather than silently editing a
test set. Keep test labels out of training, early stopping, threshold selection,
prompt design, and error-driven training additions. Validation is for those
choices. After using test errors to change training, retire that test set as an
independent final evaluation.

**Only `text` is a classifier input.** `labels` are targets. Never feed `id`,
`family_id`, `group_id`, `split`, `source`, or review metadata into the model; some
IDs deliberately expose their topic for traceability.

The training pipeline uses the English label schema and a RoBERTa encoder.
Building this dataset does not train or deploy a model.
