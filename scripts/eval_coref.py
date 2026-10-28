"""English reference-resolution smoke evaluation; calls the configured provider.

Check entities and preserved intent, not just whether a sentence changed.
Run: python -m scripts.eval_coref
"""
import asyncio
from app.core.coref import resolve

# history, query, required identifiers, unchanged, eligibility question
CASES=[
 ('Customer: I bought order alice-1001, the MH-W20 fountain.\nSupport: What would you like to know?',
  'Can I return it?', ['alice-1001','MH-W20'],False,True),
 ('Customer: Order alice-2002 is a MH-DH20 harness.\nSupport: How can I help?',
  'What size is that one?', ['MH-DH20'],False,False),
 ('Customer: I have orders alice-1001 and alice-2002.',
  'Can I return it?',[],True,True),
 ('Customer: I bought a fountain in order alice-1001.',
  'What is your general return policy?',[],True,True),
 ('','Who pays return shipping?',[],True,True),
 ('','Does MH-CAM1 support 5 GHz Wi-Fi?', ['MH-CAM1'],True,True),
 ('Customer: I ordered a harness first and a leash second.',
  'What is the length of the second item?', ['leash'],False,True),
]

async def main():
    passed=0
    for history,query,required,unchanged,question in CASES:
        result=await resolve(query,history)
        ok=all(token.casefold() in result.casefold() for token in required)
        ok=ok and (result==query if unchanged else result!=query)
        if question:ok=ok and result.rstrip().endswith('?')
        if query.startswith('Can I return'):ok=ok and not result.casefold().startswith(('submit','start','process'))
        passed+=ok
        print(f'{"PASS" if ok else "FAIL"} {query!r} -> {result!r}')
    print(f'Checks: {passed}/{len(CASES)}. Provider failures can fall back to the original question; this is not an uptime or production-accuracy benchmark.')

if __name__=='__main__':asyncio.run(main())
