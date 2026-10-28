from datetime import datetime
import uuid

from sqlalchemy import case, func, select, update

import app.db.base as db
from app.config import settings
from app.db.models import (
    Conversation,
    ConversationSummary,
    EvalRun,
    FaithCase,
    KnowledgeChunk,
    LowConfidenceQuestion,
    Message,
    QaExtractionStaging,
    ReviewQueue,
    Ticket,
    ToolAuditLog,
    TopicClassification,
)

def _gen_ticket_no() -> str:
    return "T" + uuid.uuid4().hex[:30]


async def create_conversation(user_id: str) -> int:
    async with db.async_session() as s:
        conv = Conversation(user_id=user_id)
        s.add(conv)
        await s.commit()
        return conv.id


async def get_conversation(conversation_id: int) -> Conversation | None:
    async with db.async_session() as s:
        return await s.get(Conversation, conversation_id)


async def append_message(
    conversation_id: int,
    role: str,
    content: str | None = None,
    tool_calls: list | None = None,
    tool_call_id: str | None = None,
) -> int:
    async with db.async_session() as s:
        msg = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            tool_calls=tool_calls,
            tool_call_id=tool_call_id,
        )
        s.add(msg)
        await s.commit()
        return msg.id


async def list_messages(conversation_id: int) -> list[Message]:
    async with db.async_session() as s:
        result = await s.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.id)
        )
        return list(result.scalars())


async def create_ticket(conversation_id: int, description: str, ticket_type: str, order_id: str | None = None) -> str:
    async with db.async_session() as s:
        from fastapi import HTTPException
        conv = await s.get(Conversation, conversation_id, with_for_update=True)
        if conv is None:
            raise HTTPException(404, "Conversation not found")
        if conv.status == "closed":
            raise HTTPException(409, "This conversation is closed")
        ticket_no = await add_ticket(s, conv, description, ticket_type, order_id)
        await s.commit()
    return ticket_no


async def add_ticket(s, conv, description, ticket_type, order_id=None):
    """Append a ticket and its workflow inside the caller's transaction."""
    from fastapi import HTTPException
    from app.db.service_models import TicketWorkflow, DemoOrder
    from app.db.ticket_workflow import event
    if order_id:
        order = await s.get(DemoOrder, order_id)
        if not order or order.user_id != conv.user_id:
            raise HTTPException(404, "Order not found")
    ticket_no = _gen_ticket_no()
    s.add(Ticket(ticket_no=ticket_no, conversation_id=conv.id,
                 description=description, ticket_type=ticket_type))
    await s.flush()
    s.add(TicketWorkflow(ticket_no=ticket_no, state="pending", order_id=order_id))
    event(s, ticket_no, conv.user_id, "created", "Ticket created and awaiting assignment.")
    return ticket_no


async def count_messages_after(conversation_id: int, after_id: int | None) -> int:
    """Count messages since the summary anchor. Keep the role filter aligned with summary source messages if tool persistence changes."""
    async with db.async_session() as s:
        q = (select(func.count()).select_from(Message)
             .where(Message.conversation_id == conversation_id))
        if after_id:
            q = q.where(Message.id > after_id)
        return int((await s.execute(q)).scalar_one())


async def list_dialog_messages(conversation_id: int) -> list[Message]:
    """Return customer and assistant messages in database ID order."""
    async with db.async_session() as s:
        result = await s.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id,
                   Message.role.in_(("user", "assistant")))
            .order_by(Message.id)
        )
        return list(result.scalars())


async def list_conversations(user_id: str, limit: int = 50) -> list[dict]:
    """List customer conversations newest first, with previews and summary status."""
    async with db.async_session() as s:
        convs = list((await s.execute(
            select(Conversation).where(Conversation.user_id == user_id)
            .order_by(Conversation.id.desc()).limit(limit)
        )).scalars())
        out = []
        for c in convs:
            first = (await s.execute(
                select(Message.content)
                .where(Message.conversation_id == c.id, Message.role == "user")
                .order_by(Message.id).limit(1)
            )).scalar()
            out.append({
                "id": c.id, "status": c.status,
                "preview": (first or "(empty conversation)")[:40],
                "has_summary": bool(c.summary),
                "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            })
        return out


async def update_conversation_summary(conversation_id: int, summary: str, upto_msg_id: int) -> None:
    """Atomically update the summary text and its coverage anchor."""
    async with db.async_session() as s:
        conv = await s.get(Conversation, conversation_id)
        if conv is not None:
            conv.summary = summary
            conv.summary_upto_msg_id = upto_msg_id
            await s.commit()


async def update_layer1_from(conversation_id: int, msg_id: int) -> None:
    """Advance the recent-history boundary only when the history budget is exceeded."""
    async with db.async_session() as s:
        conv = await s.get(Conversation, conversation_id)
        if conv is not None:
            conv.layer1_from_msg_id = msg_id
            await s.commit()


async def append_summary_segment(conversation_id: int, from_msg_id: int,
                                 upto_msg_id: int, content: str) -> int:
    """Append an immutable segment and update the conversation anchor and recent-summary projection atomically."""
    async with db.async_session() as s:


        prev = (await s.execute(
            select(ConversationSummary.seq, ConversationSummary.content)
            .where(ConversationSummary.conversation_id == conversation_id)
            .order_by(ConversationSummary.seq.desc())
            .limit(max(settings.summary_inject_segments - 1, 0))
        )).all()
        seq = (prev[0].seq if prev else 0) + 1
        s.add(ConversationSummary(conversation_id=conversation_id, seq=seq,
                                  from_msg_id=from_msg_id, upto_msg_id=upto_msg_id,
                                  content=content))
        conv = await s.get(Conversation, conversation_id)
        if conv is not None:
            conv.summary = "\n".join([*(r.content for r in reversed(prev)), content])
            conv.summary_upto_msg_id = upto_msg_id
        await s.commit()
        return seq


async def list_summary_segments(conversation_id: int, limit: int | None = None) -> list[str]:
    """Return recent summary segments in chronological order."""
    n = settings.summary_inject_segments if limit is None else limit
    async with db.async_session() as s:
        rows = (await s.execute(
            select(ConversationSummary.content)
            .where(ConversationSummary.conversation_id == conversation_id)
            .order_by(ConversationSummary.seq.desc())
            .limit(n)
        )).scalars().all()
        return list(reversed(rows))


async def insert_knowledge_chunk(
    category: str, questions: str, answer: str,
    section_path: str | None = None, content_type: str | None = None,
    is_key_clause: int = 0,
) -> int:
    async with db.async_session() as s:
        row = KnowledgeChunk(
            category=category, questions=questions, answer=answer,
            section_path=section_path, content_type=content_type,
            is_key_clause=is_key_clause,
        )
        s.add(row)
        await s.commit()
        return row.id


async def list_pending_chunks() -> list[KnowledgeChunk]:
    async with db.async_session() as s:
        result = await s.execute(
            select(KnowledgeChunk)
            .where(KnowledgeChunk.vectorize_status == "pending")
            .order_by(KnowledgeChunk.id)
        )
        return list(result.scalars())


async def mark_chunk_vectorized(chunk_id: int, vector_id: str) -> None:
    async with db.async_session() as s:
        row = await s.get(KnowledgeChunk, chunk_id)
        if row is not None:
            row.vector_id = vector_id
            row.vectorize_status = "done"
            await s.commit()


async def set_chunk_neighbors(chunk_id: int, prev_id: int | None, next_id: int | None) -> None:
    async with db.async_session() as s:
        row = await s.get(KnowledgeChunk, chunk_id)
        if row is not None:
            row.prev_chunk_id = prev_id
            row.next_chunk_id = next_id
            await s.commit()


async def list_chunks_by_content_types(content_types) -> list[KnowledgeChunk]:
    """Fetch source-document chunks without selecting knowledge added through review."""
    async with db.async_session() as s:
        result = await s.execute(
            select(KnowledgeChunk)
            .where(KnowledgeChunk.content_type.in_(list(content_types)))
            .order_by(KnowledgeChunk.id)
        )
        return list(result.scalars())


async def repend_chunk_text(chunk_id: int, questions: str, answer: str) -> None:
    """Update a chunk in place and mark it pending for re-embedding, preserving IDs, citations, and neighbor links."""
    async with db.async_session() as s:
        row = await s.get(KnowledgeChunk, chunk_id)
        if row is not None:
            row.questions = questions
            row.answer = answer
            row.vectorize_status = "pending"
            await s.commit()


async def count_chunks_by_status(status: str) -> int:
    async with db.async_session() as s:
        result = await s.execute(
            select(func.count()).select_from(KnowledgeChunk)
            .where(KnowledgeChunk.vectorize_status == status)
        )
        return int(result.scalar_one())


async def list_all_questions() -> list[str]:
    async with db.async_session() as s:
        result = await s.execute(select(KnowledgeChunk.questions))
        return list(result.scalars())


async def count_chunks_by_content_types(content_types) -> int:
    async with db.async_session() as s:
        result = await s.execute(
            select(func.count()).select_from(KnowledgeChunk)
            .where(KnowledgeChunk.content_type.in_(list(content_types)))
        )
        return int(result.scalar_one())


async def knowledge_stats() -> dict:
    """Return chunk counts, indexing states, content types, and key-clause totals."""
    async with db.async_session() as s:
        total = (await s.execute(select(func.count()).select_from(KnowledgeChunk))).scalar_one()
        by_status = {k: int(v) for k, v in (await s.execute(
            select(KnowledgeChunk.vectorize_status, func.count())
            .group_by(KnowledgeChunk.vectorize_status))).all()}
        by_type = {(k or "Unlabeled"): int(v) for k, v in (await s.execute(
            select(KnowledgeChunk.content_type, func.count())
            .group_by(KnowledgeChunk.content_type))).all()}
        key_clause = (await s.execute(
            select(func.count()).select_from(KnowledgeChunk)
            .where(KnowledgeChunk.is_key_clause == 1))).scalar_one()
    return {"total": int(total), "pending": by_status.get("pending", 0),
            "done": by_status.get("done", 0), "by_content_type": by_type,
            "key_clause": int(key_clause)}


async def list_recent_chunks(limit: int = 20) -> list[KnowledgeChunk]:
    async with db.async_session() as s:
        result = await s.execute(
            select(KnowledgeChunk).order_by(KnowledgeChunk.id.desc()).limit(limit)
        )
        return list(result.scalars())


async def list_chunk_pairs() -> list[tuple[str, str]]:
    """Return question/answer pairs for content-aware ingestion deduplication."""
    async with db.async_session() as s:
        result = await s.execute(select(KnowledgeChunk.questions, KnowledgeChunk.answer))
        return [(q, a) for q, a in result.all()]


async def staging_stats() -> dict:
    """Return staging counts, batch totals, and the latest batch."""
    async with db.async_session() as s:
        counts = {k: int(v) for k, v in (await s.execute(
            select(QaExtractionStaging.status, func.count())
            .group_by(QaExtractionStaging.status))).all()}
        batches = (await s.execute(
            select(func.count(func.distinct(QaExtractionStaging.batch_no))))).scalar_one()
        latest = (await s.execute(
            select(QaExtractionStaging.batch_no)
            .order_by(QaExtractionStaging.id.desc()).limit(1))).scalar_one_or_none()
    return {"counts": {k: counts.get(k, 0)
                       for k in ("extracted", "kept", "discarded")},
            "total": sum(counts.values()), "batches": int(batches), "latest_batch": latest}


async def insert_staging(batch_no: str, source_ref: str | None, question: str, answer: str) -> int:
    async with db.async_session() as s:
        row = QaExtractionStaging(
            batch_no=batch_no, source_ref=source_ref, question=question, answer=answer
        )
        s.add(row)
        await s.commit()
        return row.id


async def list_staging_by_status(status: str) -> list[QaExtractionStaging]:
    async with db.async_session() as s:
        result = await s.execute(
            select(QaExtractionStaging)
            .where(QaExtractionStaging.status == status)
            .order_by(QaExtractionStaging.id)
        )
        return list(result.scalars())


async def list_staging_by_ids(ids: list[int], status: str | None = None) -> list[QaExtractionStaging]:
    """Fetch staging rows with an optional status guard to prevent repeated approval or approval of rejected rows."""
    if not ids:
        return []
    async with db.async_session() as s:
        q = select(QaExtractionStaging).where(QaExtractionStaging.id.in_(ids))
        if status is not None:
            q = q.where(QaExtractionStaging.status == status)
        return list((await s.execute(q.order_by(QaExtractionStaging.id))).scalars())


async def set_staging_status(ids: list[int], status: str) -> None:
    if not ids:
        return
    async with db.async_session() as s:
        for i in ids:
            row = await s.get(QaExtractionStaging, i)
            if row is not None:
                row.status = status
        await s.commit()


async def insert_low_confidence(
    conversation_id: int | None, raw_question: str, source: str, reason: str | None,
    retrieved_chunks: list | None = None,
) -> int:
    async with db.async_session() as s:
        row = LowConfidenceQuestion(
            conversation_id=conversation_id, raw_question=raw_question,
            source=source, reason=reason, retrieved_chunks=retrieved_chunks,
        )
        s.add(row)
        await s.commit()
        await s.refresh(row)
        return row.id


async def list_conversations_with_messages() -> list[tuple[int, list[Message]]]:
    """Return conversations and their ordered messages for knowledge mining."""
    async with db.async_session() as s:
        conv_ids = list(
            (await s.execute(select(Conversation.id).order_by(Conversation.id))).scalars()
        )
        out: list[tuple[int, list[Message]]] = []
        for cid in conv_ids:
            msgs = list(
                (await s.execute(
                    select(Message).where(Message.conversation_id == cid).order_by(Message.id)
                )).scalars()
            )
            out.append((cid, msgs))
        return out


async def fetch_unmatched_low_conf(limit: int) -> list[LowConfidenceQuestion]:
    """Fetch unmatched low-confidence questions in ID order."""
    async with db.async_session() as s:
        result = await s.execute(
            select(LowConfidenceQuestion)
            .where(LowConfidenceQuestion.matched_review_id.is_(None))
            .order_by(LowConfidenceQuestion.id).limit(limit)
        )
        return list(result.scalars())


async def list_review_candidates(limit: int = 200) -> list[dict]:
    """Return candidates from all review states, newest first, with a bounded context size."""
    async with db.async_session() as s:
        result = await s.execute(
            select(ReviewQueue.id, ReviewQueue.normalized_question)
            .order_by(ReviewQueue.updated_at.desc()).limit(limit)
        )
        return [{"id": r.id, "normalized_question": r.normalized_question} for r in result]


async def insert_review_item(normalized_question: str, ai_suggested_answer: str | None) -> int:
    async with db.async_session() as s:
        row = ReviewQueue(normalized_question=normalized_question,
                          ai_suggested_answer=ai_suggested_answer)
        s.add(row)
        await s.commit()
        return row.id


async def increment_occurrence(review_id: int) -> None:
    """Atomically increment repeated-question counts without changing a final review decision."""
    async with db.async_session() as s:
        await s.execute(
            update(ReviewQueue)
            .where(ReviewQueue.id == review_id)
            .values(occurrence_count=ReviewQueue.occurrence_count + 1)
        )
        await s.commit()


async def set_matched_review(lcq_id: int, review_id: int) -> None:
    async with db.async_session() as s:
        row = await s.get(LowConfidenceQuestion, lcq_id)
        if row is not None:
            row.matched_review_id = review_id
            await s.commit()


async def list_review_queue(status: str | None) -> list[ReviewQueue]:
    """List knowledge gaps by occurrence count, then recency."""
    async with db.async_session() as s:
        q = select(ReviewQueue).order_by(
            ReviewQueue.occurrence_count.desc(), ReviewQueue.id.desc())
        if status:
            q = q.where(ReviewQueue.review_status == status)
        return list((await s.execute(q)).scalars())


async def get_review_detail(review_id: int) -> tuple[ReviewQueue, list[LowConfidenceQuestion]] | None:
    """Return a gap and its original questions, sources, and evidence snapshots."""
    async with db.async_session() as s:
        item = await s.get(ReviewQueue, review_id)
        if item is None:
            return None
        raws = list((await s.execute(
            select(LowConfidenceQuestion)
            .where(LowConfidenceQuestion.matched_review_id == review_id)
            .order_by(LowConfidenceQuestion.id)
        )).scalars())
        return item, raws


async def update_review_status(review_id: int, status: str, approved_answer: str | None = None) -> bool:
    """Transition pending reviews to a final decision and report whether an update occurred."""
    async with db.async_session() as s:
        row = await s.get(ReviewQueue, review_id)
        if row is None or row.review_status != "pending":
            return False
        row.review_status = status
        if approved_answer is not None:
            row.approved_answer = approved_answer
        await s.commit()
        return True


async def delete_knowledge_chunks(ids: list[int]) -> None:
    """Roll back pending chunks inserted during a failed review publication to prevent duplicate retries."""
    if not ids:
        return
    async with db.async_session() as s:
        for i in ids:
            row = await s.get(KnowledgeChunk, i)
            if row is not None:
                await s.delete(row)
        await s.commit()


async def insert_eval_run(triggered_by: str, dataset_size: int, metrics: dict) -> int:
    async with db.async_session() as s:
        row = EvalRun(triggered_by=triggered_by, dataset_size=dataset_size, metrics=metrics)
        s.add(row)
        await s.commit()
        return row.id


async def list_eval_runs(limit: int = 10) -> list[EvalRun]:
    async with db.async_session() as s:
        result = await s.execute(select(EvalRun).order_by(EvalRun.id.desc()).limit(limit))
        return list(result.scalars())


async def insert_tool_audit(
    conversation_id: int | None,
    tool_call_id: str | None,
    tool_name: str,
    tool_source: str,
    mcp_server: str | None,
    arguments: dict | None,
    result_summary: str | None,
    status: str,
    error_message: str | None,
    retry_count: int,
    duration_ms: int | None,
) -> None:
    """Insert an audit record; callers handle audit failures without blocking tool execution."""
    async with db.async_session() as s:
        s.add(ToolAuditLog(
            conversation_id=conversation_id, tool_call_id=tool_call_id,
            tool_name=tool_name, tool_source=tool_source, mcp_server=mcp_server,
            arguments=arguments, result_summary=result_summary, status=status,
            error_message=error_message, retry_count=retry_count, duration_ms=duration_ms,
        ))
        await s.commit()


def _pool_text_stmt():
    """Prefer normalized questions and fall back to original question text."""
    return (
        select(LowConfidenceQuestion.id, LowConfidenceQuestion.raw_question,
               ReviewQueue.normalized_question)
        .outerjoin(ReviewQueue, LowConfidenceQuestion.matched_review_id == ReviewQueue.id)
        .order_by(LowConfidenceQuestion.id)
    )


async def list_pool_texts() -> list[dict]:
    """Return question-pool text for offline processing."""
    async with db.async_session() as s:
        rows = (await s.execute(_pool_text_stmt())).all()
    return [{"question_id": qid, "text": norm or raw} for qid, raw, norm in rows]


async def list_unclassified_questions(limit: int = 500) -> list[dict]:
    """Fetch normalized, merged questions not yet classified; leave unmatched questions for a later batch."""
    stmt = (
        _pool_text_stmt()
        .outerjoin(TopicClassification,
                   TopicClassification.question_id == LowConfidenceQuestion.id)
        .where(TopicClassification.id.is_(None))
        .where(LowConfidenceQuestion.matched_review_id.is_not(None))
        .limit(limit)
    )
    async with db.async_session() as s:
        rows = (await s.execute(stmt)).all()
    return [{"question_id": qid, "text": norm or raw} for qid, raw, norm in rows]


async def insert_topic_classifications(rows: list[dict]) -> int:
    """Persist question IDs and their predicted topic ID arrays."""
    async with db.async_session() as s:
        s.add_all([TopicClassification(question_id=r["question_id"], labels=r["labels"])
                   for r in rows])
        await s.commit()
    return len(rows)


async def topic_distribution(samples_per_class: int = 3) -> dict:
    """Aggregate counts and examples for all 17 English topic IDs."""
    from app.topic_schema import TOPIC_NAMES

    stmt = (
        select(TopicClassification.labels, LowConfidenceQuestion.raw_question,
               ReviewQueue.normalized_question, TopicClassification.classified_at)
        .join(LowConfidenceQuestion,
              TopicClassification.question_id == LowConfidenceQuestion.id)
        .outerjoin(ReviewQueue, LowConfidenceQuestion.matched_review_id == ReviewQueue.id)
    )
    async with db.async_session() as s:
        rows = (await s.execute(stmt)).all()
    counts = {name: 0 for name in TOPIC_NAMES}
    samples: dict[str, list[str]] = {name: [] for name in TOPIC_NAMES}
    latest = None
    for labels, raw, norm, ts in rows:
        text = norm or raw
        latest = ts if latest is None or ts > latest else latest
        for lb in labels or []:
            if lb in counts:
                counts[lb] += 1

                if len(samples[lb]) < samples_per_class and text not in samples[lb]:
                    samples[lb].append(text)
    return {
        "total": len(rows),
        "latest": latest.isoformat() if latest else None,
        "classes": [{"label": n, "count": counts[n], "samples": samples[n]}
                    for n in TOPIC_NAMES],
    }


async def topic_questions(label: str, page: int = 1, size: int = 20) -> dict:
    """Filter and paginate classified questions consistently across MySQL and SQLite."""
    stmt = (
        select(TopicClassification.question_id, TopicClassification.labels,
               TopicClassification.classified_at, LowConfidenceQuestion.raw_question,
               LowConfidenceQuestion.source, LowConfidenceQuestion.created_at,
               ReviewQueue.normalized_question, ReviewQueue.occurrence_count,
               ReviewQueue.review_status)
        .join(LowConfidenceQuestion,
              TopicClassification.question_id == LowConfidenceQuestion.id)
        .outerjoin(ReviewQueue, LowConfidenceQuestion.matched_review_id == ReviewQueue.id)
        .order_by(TopicClassification.question_id.desc())
    )
    async with db.async_session() as s:
        rows = (await s.execute(stmt)).all()

    hit = [r for r in rows if label in (r[1] or [])]
    size = max(1, min(size, 100))
    pages = max(1, -(-len(hit) // size))
    page = max(1, min(page, pages))
    items = [
        {"question_id": qid, "labels": labels,
         "text": norm or raw, "raw_question": raw,
         "normalized": norm is not None,
         "source": source, "occurrence_count": occ,
         "review_status": status,
         "asked_at": asked.isoformat() if asked else None,
         "classified_at": ts.isoformat() if ts else None}
        for qid, labels, ts, raw, source, asked, norm, occ, status
        in hit[(page - 1) * size: page * size]
    ]
    return {"label": label, "total": len(hit), "page": page, "size": size,
            "pages": pages, "items": items}


async def upsert_faith_case(eval_id: str, bucket: str, query: str, answer: str, reason: str,
                            citations: list | None = None, strategy: str = "hybrid_rerank",
                            judge_model: str | None = None) -> tuple[int, bool]:
    """Update the latest evidence and recurrence count per question. Reopen previously reviewed cases and return (id, reopened)."""
    async with db.async_session() as s:
        row = (await s.execute(
            select(FaithCase).where(FaithCase.eval_id == eval_id))).scalar_one_or_none()
        now = datetime.now()
        if row is None:
            row = FaithCase(eval_id=eval_id, bucket=bucket, query=query, answer=answer,
                            reason=reason, citations=citations, strategy=strategy,
                            judge_model=judge_model, status="unresolved", seen_count=1,
                            first_seen_at=now, last_seen_at=now)
            s.add(row)
            await s.commit()
            return row.id, False
        reopened = row.status != "unresolved"
        row.bucket, row.query, row.answer, row.reason = bucket, query, answer, reason
        row.strategy, row.judge_model = strategy, judge_model
        if citations is not None:
            row.citations = citations
        row.seen_count = (row.seen_count or 0) + 1
        row.last_seen_at = now
        row.status = "unresolved"
        await s.commit()
        return row.id, reopened


async def list_faith_cases(status: str | None = None, page: int = 1,
                           size: int = 5) -> tuple[list[FaithCase], int, dict]:
    """Return paginated cases and per-state counts, unresolved first and newest first."""
    async with db.async_session() as s:
        counts = {k: 0 for k in ("unresolved", "resolved", "dismissed")}
        for st, n in (await s.execute(
                select(FaithCase.status, func.count()).group_by(FaithCase.status))).all():
            counts[st] = int(n)
        q = select(FaithCase)
        if status:
            q = q.where(FaithCase.status == status)
        total = int((await s.execute(
            select(func.count()).select_from(q.subquery()))).scalar_one())
        rows = (await s.execute(
            q.order_by(case((FaithCase.status == "unresolved", 0), else_=1),
                       FaithCase.last_seen_at.desc(), FaithCase.id.desc())
            .limit(size).offset(max(0, (page - 1) * size)))).scalars()
        return list(rows), total, counts


async def faith_case_status_map() -> dict[str, str]:
    """Map evaluation question IDs to current review states for run-specific metrics."""
    async with db.async_session() as s:
        rows = (await s.execute(select(FaithCase.eval_id, FaithCase.status))).all()
        return {eid: st for eid, st in rows}


async def set_faith_case_status(case_id: int, status: str,
                                resolution: str | None = None) -> FaithCase | None:
    """Persist a human review decision. Reopening clears resolution notes and timestamps; API validation requires notes for final decisions."""
    async with db.async_session() as s:
        row = await s.get(FaithCase, case_id)
        if row is None:
            return None
        row.status = status
        if status == "unresolved":
            row.resolved_at, row.resolution = None, None
        else:
            row.resolved_at = datetime.now()
            row.resolution = resolution
        await s.commit()
        await s.refresh(row)
        return row
