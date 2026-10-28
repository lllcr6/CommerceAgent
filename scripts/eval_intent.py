"""Evaluate English intent boundaries against the configured provider.

Run: python -m scripts.eval_intent. This makes live model calls; unit tests do not.
"""
import asyncio
from collections import Counter
from app.core.intent import INTENTS, classify

SAMPLES = [
 ('Where is order alice-1001?', 'shipping'),
 ('Has my order shipped yet?', 'shipping'),
 ("I'm furious. Where is my package?", 'shipping'),
 ('Tracking says delivered, but there is nothing here.', 'shipping'),
 ('What did I buy in order alice-1001?', 'order_status'),
 ('Cancel order alice-1001.', 'order_status'),
 ('Can you change my shipping address?', 'order_status'),
 ('Which harness fits a dog with a 24-inch chest?', 'product_policy'),
 ('What is your return policy?', 'product_policy'),
 ('Who pays return shipping?', 'product_policy'),
 ('How long is the electronics warranty?', 'product_policy'),
 ('Can I return the fountain I bought?', 'return_refund'),
 ('Please start a return for order alice-1001.', 'return_refund'),
 ('Is my litter box still within its trial?', 'return_refund'),
 ('My feeder stopped working. What can I check?', 'warranty_support'),
 ('Can you repair my broken fountain?', 'warranty_support'),
 ('My camera disconnects every day.', 'warranty_support'),
 ('Your service has been awful. I want to complain.', 'complaint'),
 ('This is ridiculous.', 'complaint'),
 ('Can I speak to someone?', 'human_support'),
 ('Open a ticket about the dog bed.', 'human_support'),
 ('The litter box is smoking. Get a human to help.', 'human_support'),
 ('Hey, are you there?', 'chitchat'),
 ('Thanks, have a nice day!', 'chitchat'),
 ('Write me a poem.', 'other'),
 ('Can you debug my Python application?', 'other'),
]

async def main():
    passed=invalid=0
    confusion=Counter()
    for query,expected in SAMPLES:
        result=await classify(query)
        got=result['intent'];conf=result['confidence']
        valid=got in INTENTS and isinstance(conf,float) and 0<=conf<=1
        invalid+=not valid;passed+=got==expected
        confusion[expected,got]+=1
        print(f'{"PASS" if got==expected else "FAIL"} {query!r} -> {got} ({conf:.3f}); expected {expected}')
    history='Customer: Where is order alice-1001?\nSupport: It has shipped.\nCustomer: I want to return it.\nSupport: We can check eligibility.'
    drift=await classify('Where is it right now?',history)
    print(f'Intent switch back to shipping: {drift["intent"]}')
    print(f'Accuracy: {passed}/{len(SAMPLES)}; invalid schema: {invalid}. Live model results are nondeterministic.')
    if invalid:raise SystemExit(1)

if __name__=='__main__':asyncio.run(main())
