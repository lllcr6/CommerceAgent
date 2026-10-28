# Deployment and operations

Run commands from the repository root. Keep an existing `.env` and persistent Docker volumes when upgrading.

## Environment

Use Python 3.12+, uv, Docker Compose, and Make:

```bash
uv sync
cp .env.example .env  # First setup only; preserve an existing configuration.
```

Configure three independent provider groups:

| Settings | Purpose |
| --- | --- |
| `CHAT_BASE_URL`, `CHAT_MODEL`, `CHAT_API_KEY` | OpenAI-compatible chat and tool calling |
| `EMBED_BASE_URL`, `EMBED_MODEL`, `EMBED_API_KEY` | Embeddings matching the index's 1024 dimensions |
| `RERANK_BASE_URL`, `RERANK_MODEL`, `RERANK_API_KEY` | Provider-specific reranking endpoint |
| `INTENT_*`, `SUMMARY_*`, `JUDGE_*` | Optional per-purpose overrides; missing values inherit `CHAT_*` |
| `DATABASE_URL`, `TEST_DATABASE_URL` | Separate application and disposable test databases |
| `MILVUS_URI`, `MILVUS_COLLECTION` | Search service and active English collection |

The model must support tool calls. `CHAT_BASE_URL` is the compatible API root, not a provider's native endpoint. Reranking uses a separate request protocol. Provider adapters support the configured endpoint shapes; credentials and model access depend on your account. Set `MODEL_CONTEXT_WINDOW` when the local model lookup does not describe your deployment. Optional reasoning parameters should match the selected provider.

The sample configuration retains the embedding and reranking adapters used by this project. You can replace their endpoints and model names; changing the embedding model requires rebuilding vectors rather than mixing incompatible embeddings.

## Start services

```bash
docker compose up -d
make seed
make kb-build
make kb-vectorize
make dev
```

SQL files are installed in numeric order only when the MySQL data volume is first initialized. `make seed` loads the small FAQ fixture; it does not apply missing schema migrations or build the RAG index. For an existing database, apply only missing SQL migrations in order after reviewing its schema.

The application adds its account, human-support, order, audit, ticket-workflow, and generation tables at startup. Order reconciliation preserves IDs, owners, lifecycle state, and ticket references. Custom product and amount combinations are not overwritten; currency is recorded explicitly.

For daily use, run `make dev`. The runner starts the two MCP services and FastAPI. `make dev-down` stops the development application and MCP processes.

| Port | Service |
| --- | --- |
| 8000 | Application |
| 8101 / 8102 | Logistics / after-sales MCP |
| 8110 | Optional topic classifier |
| 19530 | Milvus |
| 3000 | Optional Langfuse |

If host ports conflict, set `MYSQL_PORT`, `MILVUS_PORT`, and `MILVUS_HEALTH_PORT`, and update the matching client URLs. Internal MCP services bind to loopback and rely on the main tool engine for customer ownership checks.

## Accounts and workflow checks

Register a customer at `/login`, then create staff accounts:

```bash
uv run python -m scripts.create_account support1 --role support
uv run python -m scripts.create_account admin1 --role admin
```

Use separate browser profiles for each role. Verify these flows against the running services:

1. A customer sees only their orders, starts an order consultation, and receives cited policy answers.
2. Tracking queries use verified order and logistics tools.
3. A ticket is previewed and explicitly confirmed; a support specialist claims it and posts public progress and a final resolution.
4. A human handoff pauses AI responses until the support session is closed.
5. Authorized order updates enforce forward transitions, optimistic version checks, and audit logging.
6. Navigating away during generation and returning restores the same reply without duplicating writes.
7. A second customer cannot access the first customer's orders, conversations, tickets, or generation output.
8. Administrators can assign and supervise work; support specialists handle assigned customer requests.

Do not infer end-to-end success from a page loading. Record which flows were actually exercised.

## Knowledge maintenance

MySQL stores authoritative text. Ingestion writes pending chunks first, then embedding/indexing marks successful chunks done. Retry `make kb-vectorize` to finish pending indexing.

After editing source documents, use `make kb-repatch` followed by `make kb-vectorize`. This preserves chunk identities and knowledge added through review. Review relevance annotations and content snapshots before comparing new evaluation results. The admin knowledge page supports preview, ingestion, indexing, and draft review. Extracting conversations does not itself publish knowledge.

`make kb-reset` is destructive maintenance: it clears knowledge tables and the configured active index. It is not required for ordinary document updates.

## Optional observability

```bash
make langfuse-up
```

Open [Langfuse](http://localhost:3000). Set `LANGFUSE_INIT_USER_PASSWORD` in your private `.env` before starting the stack. The initial email defaults to `admin@commerceagent.local`; customize `LANGFUSE_INIT_USER_*` for your deployment. No initial password is embedded in Compose or documentation. Create project API keys in Langfuse, then configure `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and `LANGFUSE_BASE_URL` in `.env` and restart the application to enable trace export. For unattended initialization, Compose reads `LANGFUSE_INIT_PROJECT_PUBLIC_KEY` and `LANGFUSE_INIT_PROJECT_SECRET_KEY`, falling back to the configured application keys; no keys are embedded in the repository. `LANGFUSE_INIT_*` creates missing resources and does not modify existing accounts. Keep initialization project keys aligned with application export keys. The Langfuse stack uses its own `LANGFUSE_DATABASE_URL`.

Customer token accounting is stored locally in `data/runtime/model_usage.sqlite` even without Langfuse. The dashboard's USD input/output token prices are operator planning assumptions rather than billing settings. Missing usage is not counted as free usage.

## Classifier

```bash
make roberta-audit
make roberta-train
make roberta-eval
make roberta-export
make classifier-up
```

Training/export commands install the optional ML dependency group and may download model assets. Validate English schema/version, model, tokenizer, threshold, and ONNX parity before setting `TOPIC_CLASSIFIER_ENABLED=true`. The frozen synthetic dataset is not independently reviewed human gold. See [classifier documentation](data/roberta/README.md).

## Troubleshooting

- **Search is empty:** verify the active collection, source chunk count, pending count, embedding dimensions, and Milvus readiness in `/kb`.
- **Provider errors:** check the compatible endpoint root, model access, and credentials. Intent failures surface as unavailable service with a support option.
- **Stale order update:** refresh and submit with the current version; an HTTP 409 protects concurrent edits.
- **Incomplete benchmark:** restore dependencies, then use the corresponding `CONTINUE=1` command. A configuration mismatch requires a new run.
- **Interrupted generation after restart:** retain the saved partial response and resend or hand off; the service does not blindly replay writes.

The development task runner and background generation use process-local task ownership. Deploy one application process until shared worker coordination is implemented. Tests requiring MySQL must use an isolated test database.
