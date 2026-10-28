import asyncio
from types import SimpleNamespace

from app.core import summarizer
from app.db import repository as repo


def _msg(mid, role, content="x"):
    return SimpleNamespace(id=mid, role=role, content=content)


def _dialog_rows(n_turns, start_id=1):
    rows, i = [], start_id
    for t in range(n_turns):
        rows.append(_msg(i, "user", f"q{t}"))
        rows.append(_msg(i + 1, "assistant", f"a{t}"))
        i += 2
    return rows


def _small_budget(monkeypatch, sliding: int) -> None:

    monkeypatch.setattr(summarizer.budget, "compute",
                        lambda *a, **k: SimpleNamespace(sliding=sliding))


async def _seed(cid, n_turns=12, content="问题"):
    for t in range(n_turns):
        await repo.append_message(cid, "user", content=f"{content}{t}")
        await repo.append_message(cid, "assistant", content=f"回答{t}")


async def _fake_llm(old_summary, dialog):
    return "摘要"


async def test_summary_boundary_matches_recent_history_anchor(db_session_factory, db_clean, monkeypatch):

    cid = await repo.create_conversation("u1")
    await _seed(cid)
    monkeypatch.setattr(summarizer, "summarize_dialog", _fake_llm)

    msgs = await repo.list_dialog_messages(cid)
    layer1_from = msgs[9].id
    await repo.update_layer1_from(cid, layer1_from)

    await summarizer.run_summary(cid)

    conv = await repo.get_conversation(cid)
    assert conv.summary_upto_msg_id == layer1_from
    segs = await repo.list_summary_segments(cid)
    assert len(segs) == 1


async def test_empty_compressed_history_skips_summary(db_session_factory, db_clean, monkeypatch):

    cid = await repo.create_conversation("u1")
    await _seed(cid)
    monkeypatch.setattr(summarizer, "summarize_dialog", _fake_llm)

    await summarizer.run_summary(cid)

    conv = await repo.get_conversation(cid)
    assert not conv.summary_upto_msg_id
    assert await repo.list_summary_segments(cid) == []


async def test_summary_does_not_repeat_the_same_segment(db_session_factory, db_clean, monkeypatch):
    cid = await repo.create_conversation("u1")
    await _seed(cid, content="问题 订单100")
    monkeypatch.setattr(summarizer, "summarize_dialog", _fake_llm)
    msgs = await repo.list_dialog_messages(cid)
    await repo.update_layer1_from(cid, msgs[9].id)

    await summarizer.run_summary(cid)
    conv = await repo.get_conversation(cid)
    await summarizer.run_summary(cid)
    conv2 = await repo.get_conversation(cid)
    assert conv2.summary == conv.summary
    assert len(await repo.list_summary_segments(cid)) == 1


async def test_compressed_history_within_budget_skips_summary(db_session_factory, db_clean, monkeypatch):

    cid = await repo.create_conversation("u1")
    await _seed(cid)
    _small_budget(monkeypatch, sliding=100_000)
    conv = await repo.get_conversation(cid)
    msgs = await repo.list_dialog_messages(cid)
    await repo.update_layer1_from(cid, msgs[9].id)
    conv = await repo.get_conversation(cid)

    assert not await summarizer._should_summarize(cid, conv)


async def test_compressed_history_over_budget_triggers_summary(db_session_factory, db_clean, monkeypatch):
    cid = await repo.create_conversation("u1")
    await _seed(cid)
    _small_budget(monkeypatch, sliding=20)
    msgs = await repo.list_dialog_messages(cid)
    await repo.update_layer1_from(cid, msgs[9].id)
    conv = await repo.get_conversation(cid)

    assert await summarizer._should_summarize(cid, conv)


async def test_message_count_alone_does_not_trigger_summary(db_session_factory, db_clean, monkeypatch):

    cid = await repo.create_conversation("u1")
    await _seed(cid, n_turns=60)
    _small_budget(monkeypatch, sliding=20)
    conv = await repo.get_conversation(cid)

    assert not await summarizer._should_summarize(cid, conv)


async def test_empty_compressed_history_does_not_schedule_task(db_session_factory, db_clean, monkeypatch):
    cid = await repo.create_conversation("u1")
    await repo.append_message(cid, "user", content="q")
    called = []

    async def fake_run(c):
        called.append(c)
    monkeypatch.setattr(summarizer, "run_summary", fake_run)

    await summarizer.maybe_schedule_summary(cid)
    assert summarizer._running.get(cid) is None and called == []


async def test_maybe_schedule_fires_and_debounces(db_session_factory, db_clean, monkeypatch):
    cid = await repo.create_conversation("u1")
    await _seed(cid, n_turns=2)
    _small_budget(monkeypatch, sliding=20)
    msgs = await repo.list_dialog_messages(cid)
    await repo.update_layer1_from(cid, msgs[-1].id)

    gate = asyncio.Event()
    ran = []

    async def slow_run(c):
        ran.append(c)
        await gate.wait()
    monkeypatch.setattr(summarizer, "run_summary", slow_run)

    await summarizer.maybe_schedule_summary(cid)
    await summarizer.maybe_schedule_summary(cid)
    await asyncio.sleep(0)
    assert ran == [cid]
    gate.set()
    await summarizer._running[cid]
    assert cid not in summarizer._running


async def test_maybe_schedule_never_raises_into_reply_path(db_session_factory, db_clean, monkeypatch):

    async def boom(cid):
        raise RuntimeError("db down")
    monkeypatch.setattr(summarizer.repository, "get_conversation", boom)
    await summarizer.maybe_schedule_summary(1)


async def test_maybe_schedule_concurrent_calls_single_task(db_session_factory, db_clean, monkeypatch):

    cid = await repo.create_conversation("u1")
    await _seed(cid, n_turns=2)
    _small_budget(monkeypatch, sliding=20)
    msgs = await repo.list_dialog_messages(cid)
    await repo.update_layer1_from(cid, msgs[-1].id)

    gate = asyncio.Event()
    ran = []

    async def slow_run(c):
        ran.append(c)
        await gate.wait()
    monkeypatch.setattr(summarizer, "run_summary", slow_run)

    await asyncio.gather(summarizer.maybe_schedule_summary(cid),
                         summarizer.maybe_schedule_summary(cid))
    await asyncio.sleep(0)
    assert ran == [cid]
    gate.set()
    await summarizer._running[cid]
    assert cid not in summarizer._running
