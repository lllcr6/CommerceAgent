"""Derive outcome categories without changing the raw HTTP benchmark report."""
import json
from collections import Counter,defaultdict
from scripts.benchmarks.common import load_agent_report, OUT,now,write_report


def analyze(report):
    rejections=[];unexpected=[];handoffs=[];interrupts=[];counts=Counter();models=defaultdict(lambda:{'calls':0,'input_tokens':0,'output_tokens':0,'estimated_cny':0.})
    for session in report['sessions']:
        previous=None
        for turn in session['turns']:
            counts['attempts']+=1
            if turn['terminal']=='done':counts['normal_done']+=1
            if 'request_human' in turn.get('tools',[]):
                handoffs.append({'conversation_id':session['conversation_id'],'turn':turn['turn']})
            if turn['terminal']=='interrupt':
                interrupts.append({'conversation_id':session['conversation_id'],'turn':turn['turn']})
            if turn['error']:
                item={'conversation_id':session['conversation_id'],'turn':turn['turn'],'http_status':turn.get('http_status'),'error':turn['error']}
                if turn.get('http_status')==409 and previous and 'request_human' in previous.get('tools',[]):rejections.append(item)
                else:unexpected.append(item)
            previous=turn
    for usage in report.get('usage',{}).values():
        for call in usage.get('calls',[]):
            model=models[call['model']];model['calls']+=1
            for field in ('input_tokens','output_tokens','estimated_cny'):model[field]+=call[field]
    return {'created_at':now(),'scope':'Derived categories only. Raw observations remain in agent_performance.json. A keyword contract is not task-resolution accuracy.',
            'counts':dict(counts),'handoff_tool_calls':handoffs,'confirmation_interrupts':interrupts,
            'handoff_followup_409_rejections':rejections,'other_errors':unexpected,
            'other_error_rate':len(unexpected)/counts['attempts'] if counts['attempts'] else None,
            'observed_model_usage':dict(models)}


def main():
    report,source=load_agent_report()
    output=analyze(report);output['source_report']=source
    print(write_report('agent_outcomes',output))


if __name__=='__main__':main()
