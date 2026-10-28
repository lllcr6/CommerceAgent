"""Resolve data paths relative to the repository root."""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"

RAG_DIR = DATA_DIR / "rag"
KNOWLEDGE_DIR = RAG_DIR / "knowledge"
RAG_EVAL_FILE = RAG_DIR / "evaluation" / "questions.jsonl"
RAG_REPORTS_DIR = RAG_DIR / "reports"

ROBERTA_DIR = DATA_DIR / "roberta"
ROBERTA_DATASET_DIR = ROBERTA_DIR / "dataset"
ROBERTA_MODEL_DIR = ROBERTA_DIR / "model"
ROBERTA_ONNX_DIR = ROBERTA_DIR / "onnx"
ROBERTA_REPORTS_DIR = ROBERTA_DIR / "reports"

OBSERVABILITY_REPORTS_DIR = DATA_DIR / "observability" / "reports"
RUNTIME_DIR = DATA_DIR / "runtime"
