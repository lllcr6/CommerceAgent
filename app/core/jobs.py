"""Run allowlisted Make targets from the admin dashboard. Clients cannot supply commands, arguments, or paths."""
import asyncio
import contextlib
import datetime as dt
import logging
import os
import signal
import json
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = REPO_ROOT / "log" / "acceptance"
TAIL_LINES = 400


@dataclass(frozen=True)
class JobSpec:
    name: str
    title: str
    argv: tuple[str, ...]
    needs: str
    heavy: bool = False


JOBS: dict[str, JobSpec] = {
    j.name: j for j in (

        JobSpec("kb-preview", "Preview source documents and chunks", ("make", "kb-preview"), "Local preview; does not write to the database"),
        JobSpec("kb-build", "Build knowledge base (documents → pending chunks)", ("make", "kb-build"), "Requires MySQL"),
        JobSpec("kb-mine", "Mine conversations (extract answers → deduplicate → review)", ("make", "kb-mine"),
                "Requires MySQL and a chat model", heavy=True),
        JobSpec("kb-vectorize", "Index chunks (embed → Milvus → mark indexed)", ("make", "kb-vectorize"),
                "Requires MySQL, an embedding provider, and Milvus"),


        JobSpec("kb-repatch", "Update changed document chunks in place", ("make", "kb-repatch"),
                "Requires MySQL; index pending chunks afterward"),
        JobSpec("seed-conv", "Seed sample conversations", ("make", "seed-conv"), "Requires the Docker MySQL container"),

        JobSpec("eval-rag", "Evaluate RAG (compare four strategies)", ("make", "eval-rag"),
                "Requires an indexed corpus, Milvus, and a chat model; may take several minutes", heavy=True),
        JobSpec("eval-rag-continue", "Continue RAG evaluation", ("make", "eval-rag", "CONTINUE=1"),
                "Reuses successful calls only when models, data, prompts, and configuration match", heavy=True),
        JobSpec("bench-agent", "Agent evaluation", ("make", "bench-agent"),
                "Creates synthetic test conversations and uses model API credits", heavy=True),
        JobSpec("bench-agent-continue", "Continue Agent evaluation", ("make", "bench-agent", "CONTINUE=1"),
                "Reuses completed conversations and recovers pending requests; failed conversations restart separately", heavy=True),

        JobSpec("cost-report", "Cost by intent", ("make", "cost-report"),
                "Reads local customer usage records; no model calls"),
        JobSpec("eval-flywheel", "Read completed RAG evaluation history", ("make", "eval-flywheel"),
                "Reads completed run reports; no model calls", heavy=True),
        JobSpec("calibrate-confidence", "Confidence threshold calibration", ("make", "calibrate-confidence"),
                "Requires an indexed corpus, Milvus, and a reranker; may take several minutes", heavy=True),

        JobSpec("roberta-golden", "Validate golden examples", ("make", "roberta-golden"), "Requires independently reviewed English gold labels"),
        JobSpec("roberta-corpus", "Generate or resume the English training corpus", ("make", "roberta-corpus"),
                "Requires a chat model and frozen source families", heavy=True),
        JobSpec("roberta-dataset", "Export and audit frozen English dataset partitions", ("make", "roberta-dataset"),
                "Offline; requires frozen English source data", heavy=True),
        JobSpec("roberta-train", "Fine-tune the classifier", ("make", "roberta-train"),
                "Requires ML dependencies; may take several minutes", heavy=True),
        JobSpec("roberta-eval", "Evaluate the test set", ("make", "roberta-eval"), "Requires ML dependencies and trained weights"),
        JobSpec("roberta-export", "Export ONNX and verify parity", ("make", "roberta-export"),
                "Requires ML dependencies and trained weights", heavy=True),
        JobSpec("roberta-threshold-scan", "Run the classifier threshold scan", ("make", "roberta-threshold-scan"),
                "Requires the classifier service on port 8110"),
        JobSpec("classifier-up", "Start classifier service", ("make", "classifier-up"), "Requires an exported ONNX model"),
        JobSpec("classifier-down", "Stop classifier service", ("make", "classifier-down"), "—"),
        JobSpec("classify-pool", "Batch classification", ("make", "classify-pool"),
                "Requires MySQL and the classifier on port 8110"),
        JobSpec("classify-pool-force", "Classify pending questions (including partial batches)",
                ("make", "classify-pool", "FORCE=1"), "Requires MySQL and the classifier on port 8110"),
    )
}


@dataclass
class JobRun:

    """Process-local job status and watcher handles. Saved logs and artifact timestamps survive service restarts."""
    status: str = "idle"          # idle | running | ok | failed | stopped
    pid: int | None = None
    started_at: str | None = None
    finished_at: str | None = None
    returncode: int | None = None
    proc: asyncio.subprocess.Process | None = field(default=None, repr=False)
    watcher: asyncio.Task | None = field(default=None, repr=False)


_runs: dict[str, JobRun] = {}


def _run(name: str) -> JobRun:
    return _runs.setdefault(name, JobRun())


def log_path(name: str) -> Path:
    return LOG_DIR / f"{name}.log"


async def start(name: str) -> JobRun:

    """Start an allowlisted job, rejecting overlapping runs that could race on the same artifacts."""
    spec = JOBS[name]
    run = _run(name)
    if name in {'bench-agent','bench-agent-continue'}:
        other=_run('bench-agent-continue' if name=='bench-agent' else 'bench-agent')
        if other.status=='running' or (other.watcher and not other.watcher.done()):
            raise RuntimeError('An Agent evaluation is already running; wait for it to finish or stop it first')
    if name in {"eval-rag", "eval-rag-continue"}:
        other = _run("eval-rag-continue" if name == "eval-rag" else "eval-rag")
        if other.status == "running" or (other.watcher and not other.watcher.done()):
            raise RuntimeError("A RAG evaluation is already running; wait for it to finish or stop it first")
    if run.status == "running" or (run.watcher and not run.watcher.done()):
        raise RuntimeError(f"{spec.title} is already running (PID {run.pid}); wait for it to finish")

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = log_path(name)
    header = (f"$ {' '.join(spec.argv)}\n"
              f"# {dt.datetime.now().isoformat(timespec='seconds')} Started from the admin dashboard\n\n")
    path.write_text(header, encoding="utf-8")
    fh = path.open("a", encoding="utf-8", buffering=1)
    try:
        proc = await asyncio.create_subprocess_exec(
            *spec.argv, cwd=REPO_ROOT, stdout=fh, stderr=asyncio.subprocess.STDOUT,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},

            start_new_session=True,
        )
    except Exception:
        fh.close()
        raise

    run.status, run.pid = "running", proc.pid
    run.started_at = dt.datetime.now().isoformat(timespec="seconds")
    run.finished_at = run.returncode = None
    run.proc = proc
    run.watcher = asyncio.create_task(_watch(name, run, proc, fh))
    logger.info("Admin job started: %s pid=%s argv=%s", name, proc.pid, " ".join(spec.argv))
    return run


async def _watch(name: str, run: JobRun, proc: asyncio.subprocess.Process, fh) -> None:
    try:
        rc = await proc.wait()
    finally:
        with contextlib.suppress(Exception):
            fh.close()
    run.returncode = rc
    run.finished_at = dt.datetime.now().isoformat(timespec="seconds")

    if run.status != "stopped":
        run.status = "ok" if rc == 0 else "failed"
    run.proc = None
    logger.info("Admin job finished: %s rc=%s status=%s", name, rc, run.status)


async def stop(name: str) -> None:
    run = _run(name)
    proc = run.proc
    if run.status != "running" or proc is None:
        raise RuntimeError("This job is not running")
    benchmark_account = None
    if name in {"bench-agent", "bench-agent-continue"}:
        # A CLI run is not this job. Match the child process group before reading
        # its synthetic owner, so stopping one job cannot stop another run.
        from app.paths import RUNTIME_DIR, REPO_ROOT as root
        try:
            marker=json.loads((RUNTIME_DIR/'active_agent_evaluation.json').read_text())
            if marker['process_group']==os.getpgid(proc.pid):
                reports=(root/'data/benchmarks').resolve()
                path=(reports/marker['report']).resolve()
                if path.is_relative_to(reports):
                    benchmark_account=json.loads(path.read_text()).get('meta',{}).get('account')
        except (OSError,ValueError,KeyError):
            logger.info('No active benchmark account to cancel')
    run.status = "stopped"
    with contextlib.suppress(ProcessLookupError):
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    if benchmark_account:
        from app.core import generations
        try:
            await asyncio.wait_for(generations.stop_benchmark_account(benchmark_account),timeout=5)
        except Exception:
            logger.exception('Could not cancel in-flight benchmark responses')
    try:
        await asyncio.wait_for(proc.wait(), timeout=10)
    except TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        await proc.wait()
    if run.watcher:
        await run.watcher


def tail(name: str, lines: int = TAIL_LINES) -> str:
    path = log_path(name)
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    rows = text.splitlines()
    return "\n".join(rows[-lines:])


def status(name: str, with_log: bool = False) -> dict:
    spec, run = JOBS[name], _run(name)
    path = log_path(name)
    out = {
        "name": name, "title": spec.title, "cmd": " ".join(spec.argv),
        "needs": spec.needs, "heavy": spec.heavy,
        "status": run.status, "pid": run.pid,
        "started_at": run.started_at, "finished_at": run.finished_at,
        "returncode": run.returncode,

        "log_mtime": (dt.datetime.fromtimestamp(path.stat().st_mtime)
                      .isoformat(timespec="seconds") if path.exists() else None),
    }
    if with_log:
        out["log"] = tail(name)
    return out


def status_all() -> list[dict]:
    return [status(n) for n in JOBS]
