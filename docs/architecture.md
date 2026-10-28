# Architecture and operating boundaries

## Request flow

An authenticated customer message enters the generation manager, which persists its request identity and streamed output. The graph resolves conversational references and classifies one of nine English intents. Policy questions retrieve evidence before generation. Business tools verify record ownership through the shared execution engine. Refund and ticket workflows require customer confirmation; an eligibility question alone does not authorize a write.

The execution engine validates tool arguments, enforces local authorization rules, applies timeouts and bounded retries, formats results, and records audit outcomes. Built-in and MCP tools share this path. Remote tool declarations cannot grant additional write permissions.

## Retrieval and knowledge

The English corpus covers U.S. shipping, billing, returns, warranty, rewards, and cat/dog product specifications. It defines 30-day standard returns, a separate 60-day litter-box trial, and explicit exceptions. Product prices and order states come from current operational records rather than policy embeddings.

Documents become hierarchical chunks with sentence overlap and repeated table headers. MySQL stores text and indexing state; Milvus stores dense vectors and English BM25 fields. Hybrid search combines results with reciprocal-rank fusion and a reranker. Confidence combines the highest score, valid-hit count, score margin, and key-clause matches. Evidence self-check failures fail closed. Product model numbers must appear exactly in evidence.

Mined conversation answers enter staging for deduplication and human review. Only approval publishes knowledge. Pending indexing can be retried without clearing the index. A review gap retains its original questions and evidence snapshots.

## Conversation state

A persistent graph checkpointer supports order-selection and ticket-confirmation interrupts. Historical messages remain unchanged; rendering uses recent full turns, compressed older turns, and append-only summary segments. Stable anchors and a single system message preserve prompt-prefix consistency. Context budgets distinguish peak ReAct usage from settled history usage.

Browser disconnection does not cancel server generation. The generation table preserves output snapshots for reconnection. Application restarts interrupt active work; automatic replay is avoided because tool execution may already have written records.

## Human service and access control

Customer, support, and admin roles have distinct permissions. Support specialists claim conversations or independent tickets. Public ticket updates and internal notes are separate; completing a ticket requires a public result. Reassignment revokes the prior specialist's access. Ticket work does not implicitly take over or close an AI conversation.

Order and workflow updates use optimistic versions; record changes and audits commit together. MySQL conversation locks coordinate processes. SQLite test fixtures use in-process locks. MCP processes read the same committed business records.

## Evaluation and artifacts

RAG runs freeze input snapshots and save successful retrieval and model work under a run ID. Continue fills missing calls when fingerprints match. Reports score exact chunk IDs and distinguish missing work from zero scores. Only completed, comparable runs contribute trend comparisons.

Agent runs use authenticated synthetic accounts and real SSE endpoints. Recovered stream replay is excluded from latency distributions. Input and output token usage are reported separately, and synthetic runs are excluded from customer usage totals. Lexical response contracts are diagnostics rather than independently reviewed resolution labels.

The optional topic classifier shares English labels across training, evaluation, export, and inference. Its data card records synthetic generation and family-level split limitations.

## Scope

This is a simulated commerce environment. Payment execution, shipping-label issuance, real inventory synchronization, and production workforce savings have not been implemented or established. Default task ownership assumes a single application process; horizontal deployment needs a shared queue and workers.
