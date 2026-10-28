"""Single-process generation supervisor. HTTP connections only observe owned tasks.

Snapshots survive navigation and restart. Restarted model invocations are marked
interrupted, never automatically replayed (which could duplicate tool writes).
"""
import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
import app.db.base as db
from app.db.models import Conversation
from app.db.service_models import ChatGeneration

logger = logging.getLogger(__name__)

@dataclass
class LiveRun:
    cid: int
    run_id: str
    frames: list = field(default_factory=list)
    state: str = 'running'
    changed: asyncio.Event = field(default_factory=asyncio.Event)
    stop_reason: str | None = None

_live: dict[str,LiveRun] = {}
_tasks: dict[str,asyncio.Task] = {}

def _error(message):
    return ['data: '+json.dumps({'event':'actions','items':[{'type':'transfer_human'}]},ensure_ascii=False)+'\n\n',
            'event: error\n', 'data: '+json.dumps({'message':message},ensure_ascii=False)+'\n\n']

async def start(cid, uid, source_factory, *, resume=False, request_id=None):
    """Commit the run before starting it; reject duplicate generation per conversation."""
    run_id=request_id or uuid.uuid4().hex
    async with db.async_session() as s:
        conv=await s.get(Conversation,cid,with_for_update=True)
        if not conv or conv.user_id!=uid:
            raise HTTPException(404,'Conversation not found.')
        row=await s.get(ChatGeneration,cid)
        if request_id and row and row.run_id == request_id:
            return row.run_id  # Benchmark retry observes the same producer; never starts another.
        if conv.status!='active':
            raise HTTPException(409,'This conversation is closed or in human support.')
        if row and row.state=='running':
            raise HTTPException(409,"A reply is being generated. Wait for it to finish.")
        if row and row.state=='waiting' and not resume:
            raise HTTPException(409,"Select an order or confirm the ticket first, or start a new conversation.")
        if resume and row and row.state!='waiting':
            raise HTTPException(409,"No reply is awaiting confirmation. Refresh the conversation.")
        if row:
            result=await s.execute(update(ChatGeneration).where(
                ChatGeneration.conversation_id==cid, ChatGeneration.run_id==row.run_id,
                ChatGeneration.state!='running').values(run_id=run_id,state='running',frames=[]))
            if result.rowcount!=1:
                raise HTTPException(409,"The generation record changed. Refresh the conversation.")
        else:
            s.add(ChatGeneration(conversation_id=cid,run_id=run_id,state='running',frames=[]))
        try:
            await s.commit()
        except IntegrityError:
            await s.rollback()
            raise HTTPException(409,"A reply is being generated. Wait for it to finish.")
    live=LiveRun(cid,run_id)
    _live[run_id]=live
    # asyncio task lifetime is independent of Starlette's request cancellation scope.
    task=asyncio.create_task(_consume(live,source_factory),name='chat-generation-'+run_id)
    _tasks[run_id]=task
    def finished(t):
        _tasks.pop(run_id,None);_live.pop(run_id,None)
        if not t.cancelled():
            exc=t.exception()
            if exc:logger.error("Background generation task failed: run=%s",run_id,exc_info=exc)
    task.add_done_callback(finished)
    return run_id

async def _save(live):
    async with db.async_session() as s:
        row=await s.get(ChatGeneration,live.cid)
        if row and row.run_id==live.run_id:
            row.frames=list(live.frames);row.state=live.state
            await s.commit()

async def _consume(live,source_factory):
    saved=time.monotonic()
    failed=False;waiting=False
    try:
        async for frame in source_factory():
            live.frames.append(frame)
            if 'event: error' in frame:failed=True
            if frame.startswith('data: '):
                try:
                    data=json.loads(frame[6:])
                    if isinstance(data,dict) and data.get('event')=='interrupt':waiting=True
                except (ValueError,TypeError):pass
            live.changed.set()
            if time.monotonic()-saved>=.3:
                await _save(live);saved=time.monotonic()
        live.state='failed' if failed else 'waiting' if waiting else 'completed'
    except asyncio.CancelledError:
        live.state='failed'
        live.frames.extend(_error(live.stop_reason or "The service is restarting and interrupted this reply. Resend your message or contact support."))
    except Exception:
        logger.exception("Background generation failed: cid=%s",live.cid)
        live.state='failed';live.frames.extend(_error("Replies are temporarily unavailable. Try again later or contact support."))
    finally:
        try:await _save(live)
        finally:live.changed.set()

async def snapshot(cid):
    async with db.async_session() as s:
        row=await s.get(ChatGeneration,cid)
        if not row:return None
        live=_live.get(row.run_id)
        return {'run_id':row.run_id,'state':live.state if live else row.state,
                'frames':list(live.frames) if live else list(row.frames),'conversation_id':cid}

async def stream(cid,run_id):
    """Replay then follow. Disconnect cancels this observer, never the producer."""
    cursor=0
    while True:
        live=_live.get(run_id)
        if live:
            live.changed.clear()
            frames=live.frames;state=live.state
        else:
            snap=await snapshot(cid)
            if not snap or snap['run_id']!=run_id:
                for f in _error("The generation record changed. Refresh the conversation."):yield f
                return
            frames=snap['frames'];state=snap['state']
        while cursor<len(frames):
            frame=frames[cursor];cursor+=1;yield frame
        if state!='running':
            producer=_tasks.get(run_id)
            if producer:
                await asyncio.shield(producer)
            return
        if live:
            try:await asyncio.wait_for(live.changed.wait(),timeout=15)
            except asyncio.TimeoutError:yield ': keep-alive\n\n'
        else:
            await asyncio.sleep(.3)

async def recover_interrupted():
    """Called once at startup of the local single-process application."""
    async with db.async_session() as s:
        rows=(await s.scalars(select(ChatGeneration).where(ChatGeneration.state=='running'))).all()
        for row in rows:
            row.state='failed';row.frames=list(row.frames)+_error("The service restarted and interrupted the previous reply. Resend your message or contact support.")
        await s.commit()

async def shutdown():
    tasks=list(_tasks.values())
    if not tasks:return
    _,pending=await asyncio.wait(tasks,timeout=10)
    for task in pending:task.cancel()
    if pending:await asyncio.gather(*pending,return_exceptions=True)


async def stop_benchmark_account(uid):
    """Cancel only running generations owned by this specific synthetic account.

    Called from the admin job stop handler, never inferred from a client disconnect.
    """
    if not uid.startswith('bench_'):
        raise ValueError('Only synthetic benchmark accounts may be stopped here')
    async with db.async_session() as session:
        rows=(await session.scalars(select(ChatGeneration).join(
            Conversation,Conversation.id==ChatGeneration.conversation_id).where(
                Conversation.user_id==uid,ChatGeneration.state=='running'))).all()
    tasks=[]
    for row in rows:
        task=_tasks.get(row.run_id)
        if task and not task.done():
            live=_live.get(row.run_id)
            if live:live.stop_reason='Evaluation stopped by the administrator.'
            task.cancel();tasks.append(task)
    if tasks:await asyncio.gather(*tasks,return_exceptions=True)
    return len(tasks)
