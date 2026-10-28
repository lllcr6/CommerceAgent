export PYTHONUTF8 = 1

.PHONY: help kb-repatch dev test eval eval-check judge-check seed eval-memory kb-preview kb-build kb-vectorize kb-mine eval-retrieval seed-conv eval-mining kb-reset milvus-up milvus-down smoke-rag eval-rag smoke-interrupt mcp-up mcp-down langfuse-up langfuse-down
.PHONY: roberta-audit roberta-golden roberta-corpus roberta-dataset roberta-train roberta-eval roberta-export roberta-threshold-scan classifier-up classifier-down classify-pool
.PHONY: bench-rag bench-agent bench-report

bench-rag:  ## Paired retrieval ablation with three repeats and bootstrap intervals
	PYTHONPATH=. uv run python -m scripts.benchmarks.rag_ablation --repeats 3 --concurrency 3
	PYTHONPATH=. uv run python -m scripts.benchmarks.publish_admin

bench-agent:  ## Authenticated SSE benchmark: 12 three-turn scenarios, three repeats
	PYTHONPATH=. uv run python -m scripts.benchmarks.run_agent_evaluation --repeats 3 --concurrency 6 $(if $(CONTINUE),--continue,)

bench-report:  ## Republish the current Agent summary without model calls
	PYTHONPATH=. uv run python -m scripts.benchmarks.analyze_agent
	PYTHONPATH=. uv run python -c 'from scripts.benchmarks.publish_admin import publish_agent; publish_agent()'

help:  ## List documented targets
	@grep -E '^[a-z][a-z0-9-]*:.*?## ' $(MAKEFILE_LIST) \
	  | sed 's/:.*## /\t/' | sort | awk -F'\t' '{printf "  %-22s %s\n", $$1, $$2}'

langfuse-up:
	docker compose -p commerceagent-langfuse -f docker-compose.langfuse.yml up -d
	@echo "Starting Langfuse: http://localhost:3000"
	@echo "Local account: set LANGFUSE_INIT_USER_EMAIL and LANGFUSE_INIT_USER_PASSWORD in .env"
	@echo "First startup takes about 2-3 minutes. Set your Langfuse project keys in .env:"
	@echo "  LANGFUSE_PUBLIC_KEY=<your-langfuse-public-key>"
	@echo "  LANGFUSE_SECRET_KEY=<your-langfuse-secret-key>"
	@echo "  LANGFUSE_BASE_URL=http://localhost:3000"

langfuse-down:
	docker compose -p commerceagent-langfuse -f docker-compose.langfuse.yml down

calibrate-confidence:  ## Calibrate evidence confidence (requires indexed knowledge and providers)
	PYTHONPATH=. uv run python scripts/calibrate_confidence.py

flywheel:  ## Normalize and deduplicate unanswered questions into the review queue
	PYTHONPATH=. uv run python scripts/flywheel_pipeline.py

flywheel-samples:  ## Validate normalization and deduplication against labeled examples
	PYTHONPATH=. uv run python scripts/validate_flywheel_samples.py

eval-flywheel:  ## Show completed RAG experiment history; no evaluation or model calls
	PYTHONPATH=. uv run python scripts/eval_flywheel.py

cost-report:  ## Export local customer token usage by intent (DAYS=window length)
	PYTHONPATH=. uv run python scripts/cost_by_intent.py --days $(or $(DAYS),7)

roberta-golden:  ## Validate independently reviewed topic labels when available
	PYTHONPATH=. uv run python scripts/roberta/validate_golden.py

roberta-corpus:  ## Generate/resume English family-scoped messages (uses model API tokens)
	PYTHONPATH=. uv run python -m scripts.roberta.english_dataset --generate

roberta-dataset:  ## Offline leakage audit and frozen English train/validation/test export
	PYTHONPATH=. uv run python scripts/roberta/build_dataset.py

roberta-audit:  ## Validate frozen English splits and leakage invariants; no API calls
	PYTHONPATH=. uv run python -m scripts.roberta.validate_dataset

roberta-train:  ## Train English RoBERTa on frozen train/validation partitions (ML dependencies)
	PYTHONPATH=. uv run --group ml python scripts/roberta/train.py

roberta-eval:  ## Evaluate frozen English test set; per-topic metrics and error review
	PYTHONPATH=. uv run --group ml python scripts/roberta/evaluate.py

roberta-export:  ## Export English ONNX; verify Torch parity on validation texts
	PYTHONPATH=. uv run --group ml python scripts/roberta/export_onnx.py

roberta-threshold-scan:  ## Replay validation-only threshold selection (requires English classifier on :8110)
	PYTHONPATH=. uv run python scripts/roberta/scan_threshold_replay.py

classifier-up:  ## English ONNX inference service on :8110
	@mkdir -p log data/runtime
	@PYTHONPATH=. nohup uv run --group ml python scripts/roberta/serve.py > log/classifier.log 2>&1 & echo $$! > data/runtime/classifier.pid
	@sleep 2 && curl -sf http://127.0.0.1:8110/healthz >/dev/null && echo "Classifier started on :8110 (PID in data/runtime/classifier.pid)" || echo "Startup failed; see log/classifier.log"

classifier-down:
	-@kill `cat data/runtime/classifier.pid 2>/dev/null` 2>/dev/null; rm -f data/runtime/classifier.pid
	@echo "Classifier stopped"

classify-pool:  ## Classify pending questions (requires :8110; FORCE=1 includes partial batches)
	PYTHONPATH=. uv run python scripts/roberta/classify_pool.py $(if $(FORCE),--force,)

dev:
	bash ./scripts/dev.sh

dev-down:
	-@$(MAKE) mcp-down
	-@pkill -f "uvicorn app.main:app" 2>/dev/null; echo "Application stopped"

mcp-up:
	@mkdir -p log data/runtime
	@nohup uv run python mcp_servers/logistics_server.py  > log/mcp-logistics.log 2>&1 & echo $$! > data/runtime/mcp-logistics.pid
	@nohup uv run python mcp_servers/aftersales_server.py > log/mcp-aftersales.log 2>&1 & echo $$! > data/runtime/mcp-aftersales.pid
	@sleep 1 && echo "MCP services started: logistics=:8101 aftersales=:8102 (PIDs: data/runtime/*.pid)"

mcp-down:
	-@kill `cat data/runtime/mcp-logistics.pid 2>/dev/null` 2>/dev/null; rm -f data/runtime/mcp-logistics.pid
	-@kill `cat data/runtime/mcp-aftersales.pid 2>/dev/null` 2>/dev/null; rm -f data/runtime/mcp-aftersales.pid
	@echo "MCP services stopped"

milvus-up:
	docker compose up -d etcd minio milvus-standalone
	@echo "Waiting for Milvus health check..."; \
	for i in $$(seq 1 60); do \
	  curl -sf http://localhost:9091/healthz >/dev/null 2>&1 && echo "Milvus OK" && exit 0; \
	  sleep 3; done; echo "Milvus is not ready" && exit 1

milvus-down:
	docker compose stop etcd minio milvus-standalone

smoke-rag:
	PYTHONPATH=. uv run python scripts/smoke_milvus_bm25.py
	PYTHONPATH=. uv run python scripts/smoke_rerank.py

eval-check:  ## Validate relevance annotations against the live index
	PYTHONPATH=. uv run python scripts/validate_rag_eval.py

eval-rag:  ## Evaluate four retrieval strategies; SKIP_GEN=1 omits generation
	PYTHONPATH=. uv run python scripts/eval_rag.py $(if $(SKIP_GEN),--skip-gen,) $(if $(CONTINUE),--continue,)

judge-check:  ## Replay faithfulness cases against human review decisions
	PYTHONPATH=. uv run python scripts/judge_check.py

seed:
	docker compose exec -T mysql sh -c 'exec mysql --default-character-set=utf8mb4 -uroot -proot "$$MYSQL_DATABASE"' < sql/002_faq_seed.sql

test:
	uv run pytest -v

eval:
	uv run python scripts/eval_extract.py


smoke-interrupt:  ## Check graph interrupt/resume and streaming contracts
	uv run python scripts/smoke_interrupt.py


kb-preview:
	PYTHONPATH=. uv run python scripts/show_kb.py

kb-build:
	PYTHONPATH=. uv run python scripts/build_kb.py

kb-vectorize:
	PYTHONPATH=. uv run python scripts/vectorize_kb.py

kb-repatch:
	PYTHONPATH=. uv run python scripts/kb_repatch.py

kb-mine:
	PYTHONPATH=. uv run python scripts/mine_knowledge.py

eval-retrieval:
	PYTHONPATH=. uv run python scripts/eval_retrieval.py

seed-conv:
	docker compose exec -T mysql sh -c 'exec mysql --default-character-set=utf8mb4 -uroot -proot "$$MYSQL_DATABASE"' < sql/004_conversation_seed.sql

eval-mining:
	PYTHONPATH=. uv run python scripts/eval_mining.py

kb-reset:
	docker compose exec -T mysql sh -c 'exec mysql -uroot -proot "$$MYSQL_DATABASE" -e "SET FOREIGN_KEY_CHECKS=0; DELETE FROM knowledge_chunks; DELETE FROM qa_extraction_staging; SET FOREIGN_KEY_CHECKS=1;"'
	PYTHONPATH=. uv run python -c "from app.kb import milvus_client as m; m.drop(m.get_client(), m.COLLECTION)"
	@echo "Knowledge tables and search index reset. Next: make kb-build, then make kb-vectorize."

eval-memory:
	uv run python -m scripts.eval_memory


# English corpus preparation and index publishing.
rag-prepare-en:
	PYTHONPATH=. uv run python -m scripts.prepare_english_rag

rag-check-offline:
	PYTHONPATH=. uv run python -m scripts.validate_rag_eval --offline

kb-english-plan:
	PYTHONPATH=. uv run python -m scripts.index_english_kb

kb-english:
	PYTHONPATH=. uv run python -m scripts.index_english_kb --publish
	PYTHONPATH=. uv run python -m scripts.prepare_english_rag --bind-live
