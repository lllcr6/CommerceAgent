import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Depends, Request
from fastapi.responses import JSONResponse
from app.auth import router as auth_router, administrator
from app.api.service import router as service_router
from app.api.tickets import router as tickets_router
from app.api.orders import router as orders_router
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.acceptance import router as acceptance_router
from app.api.actions import router as actions_router
from app.api.admin import router as admin_router
from app.api.agent import router as agent_router
from app.api.chat import router as chat_router
from app.api.conversations import router as conversations_router
from app.api.extract import router as extract_router
from app.api.feedback import router as feedback_router
from app.api.jobs import router as jobs_router
from app.api.kb import router as kb_router
from app.api.observability import router as observability_router
from app.api.rageval import router as rageval_router
from app.api.review import router as review_router
from app.api.topics import router as topics_router
from app.graph import runtime


_applog = logging.getLogger("app")
if not _applog.handlers:
    _fmt = logging.Formatter("%(levelname)s:%(name)s:%(message)s")
    _h = logging.StreamHandler()
    _h.setFormatter(_fmt)
    _applog.addHandler(_h)


    _log_dir = Path(__file__).resolve().parent.parent / "log"
    _log_dir.mkdir(parents=True, exist_ok=True)
    _fh = logging.FileHandler(_log_dir / "app.log", encoding="utf-8")
    _fh.setFormatter(_fmt)
    _applog.addHandler(_fh)
_applog.setLevel(logging.INFO)
_applog.propagate = False

logger = logging.getLogger(__name__)
_STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Warm the search collection before serving requests; warmup failure does not block startup."""
    try:
        from app.core import retrieval
        for _ in range(15):
            hits = await retrieval.search_knowledge("return shipping fees", strategy="bm25", top_k=1)
            if hits:
                logger.info("Milvus warmup complete; collection is searchable")
                break
            await asyncio.sleep(1)
        else:
            logger.warning("Milvus warmup timed out after 15s; continuing startup")
    except Exception:
        logger.warning("Milvus warmup failed; continuing startup", exc_info=True)
    from app.bootstrap import initialize_service_tables
    await initialize_service_tables()
    from app.core import generations
    await generations.recover_interrupted()
    from app.tools import registry as tool_registry
    tool_registry.scan_builtin()
    _check_context_budget()
    await runtime.init_graph()
    try:
        yield
    finally:
        await generations.shutdown()
        await runtime.close_graph()


def _check_context_budget() -> None:
    """Validate that fixed overhead and a peak ReAct turn fit the model window at startup."""
    from app.core import budget
    b = budget.compute()
    if b.healthy:
        logger.info("Context budget %s", budget.describe(b))
    else:
        logger.error("Insufficient context budget: window %s cannot fit fixed overhead %s plus peak turn %s. Increase the model window or reduce MAX_AGENT_STEPS / TOOL_RESULT_MAX_TOKENS / MAX_OUTPUT_TOKENS / RERANK_TOP_K. %s",
                     b.window, b.fixed, b.peak, budget.describe(b))


app = FastAPI(title="Paw & Hearth", version="0.1.0", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(service_router)
app.include_router(tickets_router)
app.include_router(orders_router)
app.include_router(actions_router)
app.include_router(chat_router)
app.include_router(extract_router, dependencies=[Depends(administrator)])
app.include_router(agent_router)
app.include_router(conversations_router)
app.include_router(feedback_router)
app.include_router(review_router, dependencies=[Depends(administrator)])
app.include_router(topics_router, dependencies=[Depends(administrator)])
app.include_router(acceptance_router, dependencies=[Depends(administrator)])
app.include_router(kb_router, dependencies=[Depends(administrator)])
app.include_router(rageval_router, dependencies=[Depends(administrator)])
app.include_router(observability_router, dependencies=[Depends(administrator)])
app.include_router(admin_router, dependencies=[Depends(administrator)])
app.include_router(jobs_router, dependencies=[Depends(administrator)])


app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> FileResponse:
    return FileResponse(_STATIC_DIR / "favicon.ico", media_type="image/x-icon")


@app.get("/apple-touch-icon.png", include_in_schema=False)
@app.get("/apple-touch-icon-precomposed.png", include_in_schema=False)
async def apple_touch_icon() -> FileResponse:
    return FileResponse(_STATIC_DIR / "apple-touch-icon.png", media_type="image/png")


@app.get("/", include_in_schema=False)
async def chat_page() -> FileResponse:
    return FileResponse(_STATIC_DIR / "index.html")


@app.get("/admin", include_in_schema=False)
async def admin_page() -> FileResponse:
    """Serve the operations dashboard."""
    return FileResponse(_STATIC_DIR / "admin.html")


@app.get("/kb", include_in_schema=False)
async def kb_page() -> FileResponse:
    """Serve knowledge ingestion and search tools."""
    return FileResponse(_STATIC_DIR / "kb.html")


@app.get("/rag-eval", include_in_schema=False)
async def rageval_page() -> FileResponse:
    """Serve retrieval evaluation reports and controls."""
    return FileResponse(_STATIC_DIR / "rageval.html")


@app.get("/review", include_in_schema=False)
async def review_page() -> FileResponse:
    """Serve the knowledge review queue."""
    return FileResponse(_STATIC_DIR / "review.html")


@app.get("/observability", include_in_schema=False)
async def observability_page() -> FileResponse:
    """Serve usage, evaluation trends, and confidence calibration."""
    return FileResponse(_STATIC_DIR / "observability.html")


@app.get("/topics", include_in_schema=False)
async def topics_page() -> FileResponse:
    """Serve topic distributions."""
    return FileResponse(_STATIC_DIR / "topics.html")


@app.get("/topics/questions", include_in_schema=False)
async def topic_questions_page() -> FileResponse:
    """Serve paginated questions for a topic."""
    return FileResponse(_STATIC_DIR / "topic-questions.html")


@app.get("/acceptance", include_in_schema=False)
async def acceptance_page() -> FileResponse:
    """Serve classifier validation status."""
    return FileResponse(_STATIC_DIR / "acceptance.html")


@app.get("/acceptance/eval", include_in_schema=False)
async def acceptance_eval_page() -> FileResponse:
    """Serve classifier metrics and threshold scans."""
    return FileResponse(_STATIC_DIR / "acceptance-eval.html")


@app.get("/acceptance/data", include_in_schema=False)
async def acceptance_data_page() -> FileResponse:
    """Serve dataset lineage and model artifacts."""
    return FileResponse(_STATIC_DIR / "acceptance-data.html")


@app.get("/acceptance/errors", include_in_schema=False)
async def acceptance_errors_page() -> FileResponse:
    """Serve classifier error review."""
    return FileResponse(_STATIC_DIR / "acceptance-errors.html")


@app.middleware("http")
async def role_pages(request: Request, call_next):
    """HTML navigation uses the same role boundary as API operations."""
    from posixpath import normpath
    from fastapi import HTTPException
    from fastapi.responses import RedirectResponse
    from app.auth import current_user
    homes = {"user": "/", "support": "/support", "admin": "/admin"}
    pages = {"/": {"user"}, "/orders": {"user"}, "/support": {"support"},
             "/tickets": set(homes)}
    admin_pages = {"admin", "kb", "rag-eval", "review", "observability", "topics",
                   "topics/questions", "acceptance", "acceptance/eval", "acceptance/data", "acceptance/errors"}
    pages.update({"/" + page: {"admin"} for page in admin_pages})
    static_pages = {"/static/index.html": "/", "/static/orders.html": "/orders",
                    "/static/support.html": "/support", "/static/tickets.html": "/tickets"}
    static_pages.update({"/static/" + page.replace("/", "-") + ".html": "/" + page for page in admin_pages})
    static_pages.update({"/static/rageval.html": "/rag-eval", "/static/topic-questions.html": "/topics/questions"})
    path = normpath(request.url.path)
    path = static_pages.get(path, path)
    if path in pages:
        try:
            user = await current_user(request)
        except HTTPException as exc:
            if exc.status_code != 401:
                raise
            return RedirectResponse("/login", status_code=303)
        if user.role not in pages[path]:
            return RedirectResponse(homes.get(user.role, "/login"), status_code=303)
    return await call_next(request)


@app.middleware("http")
async def same_origin_writes(request: Request, call_next):
    # Cookies are HttpOnly + SameSite strict; also reject foreign browser origins.
    from urllib.parse import urlparse
    origin = request.headers.get("origin")
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and origin:
        if urlparse(origin).netloc != request.headers.get("host"):
            return JSONResponse({"detail": "Cross-site writes are not allowed"}, status_code=403)
    return await call_next(request)

@app.get("/login", include_in_schema=False)
async def login_page():
    return FileResponse(_STATIC_DIR / "login.html")

@app.get("/support", include_in_schema=False)
async def support_page():
    return FileResponse(_STATIC_DIR / "support.html")


@app.get("/tickets", include_in_schema=False)
async def tickets_page():
    return FileResponse(_STATIC_DIR / "tickets.html")


@app.get("/orders", include_in_schema=False)
async def orders_page() -> FileResponse:
    return FileResponse(_STATIC_DIR / "orders.html")
