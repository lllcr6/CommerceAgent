from copy import deepcopy
from app.agent_resume import prepare

def success(n=3):return [{'turn':i,'terminal':'done','error':None} for i in range(1,n+1)]

def test_complete_session_is_unchanged():
    session={'turns':success(),'conversation_id':1}
    before=deepcopy(session)
    assert prepare(session)=='reused'
    assert session==before

def test_partial_good_turns_and_pending_request_are_preserved():
    session={'turns':success(1),'conversation_id':1,'pending':{'turn':2,'request_id':'fixed'}}
    before=deepcopy(session)
    assert prepare(session)=='continue'
    assert session==before

def test_failed_state_restarts_only_affected_conversation_and_preserves_attempt():
    session={'turns':success(1)+[{'turn':2,'error':'sse_error'}],'conversation_id':1}
    assert prepare(session)=='restart_failed_conversation'
    assert session['turns']==[] and session['conversation_id'] is None
    assert session['attempts'][0]['conversation_id']==1

def test_interrupted_state_is_not_retried_automatically():
    session={'turns':[{'turn':1,'terminal':'interrupt','error':None}],'conversation_id':1}
    assert prepare(session)=='blocked'
