import asyncio
import re

from app.core.summarizer import summarize_dialog


CASE1_DIALOG = """Customer: Hello, are you there?
Support: Hello! How can I help?
Customer: Where is my cat tree in order 1001?
Support: It has shipped from Los Angeles; the carrier estimates arrival in two days.
Customer: Please call 2025550142 before delivery.
Support: I recorded your request for a call to 2025550142.
Customer: What is the weight capacity?
Support: This cat tree supports up to 33 pounds."""
CASE1_MUST = ["1001", "2025550142", "cat tree"]
CASE1_BAN = ["Hello! How can I help?"]

CASE2_DIALOG = """Customer: Can I return the unopened fountain in order 2002?
Support: When was it delivered?
Customer: Three days ago. I no longer need it.
Support: The standard return window is 30 days; support must review condition and eligibility before approving a refund."""
CASE3_OLD = "Customer asked about cat tree order 1001 and requested a call to 2025550142 before delivery; asked about its 33-pound weight capacity."
CASE3_DIALOG = """Customer: The cat tree arrived but a post is missing.
Support: Please provide a photo and the part details so support can review available options.
Customer: I prefer a replacement post.
Support: I noted the request for order 1001; a shipment has not been confirmed."""
CASE3_MUST = ["1001", "post"]


def check(name: str, summary: str, must=(), ban=(), src_digits: str = "") -> bool:
    ok = True
    problems = []
    if not (20 <= len(summary) <= 800):
        ok, problems = False, problems + [f"Length {len(summary)} is outside [20,800]"]
    for kw in must:
        if kw not in summary:
            ok, problems = False, problems + [f"Missing fact: {kw}"]
    for kw in ban:
        if kw in summary:
            ok, problems = False, problems + [f"Greeting retained: {kw}"]
    if src_digits:
        src_nums = set(re.findall(r"\d{4,}", src_digits))
        for n in set(re.findall(r"\d{4,}", summary)):
            if n not in src_nums:
                ok, problems = False, problems + [f"Invented numeric identifier: {n}"]
    print(f"{'✅' if ok else '❌'} {name} len={len(summary)}")
    print(f"   Summary: {summary}")
    if problems:
        print(f"   Issues: {problems}")
    return ok


async def main():
    results = []
    s1 = await summarize_dialog("", CASE1_DIALOG)
    results.append(check("Case 1: retain facts and omit greetings", s1, must=CASE1_MUST, ban=CASE1_BAN,
                         src_digits=CASE1_DIALOG))
    s2 = await summarize_dialog("", CASE2_DIALOG)
    results.append(check("Case 2: numeric identifiers must come from the source", s2, must=["2002"],
                         src_digits=CASE2_DIALOG))
    s3 = await summarize_dialog(CASE3_OLD, CASE3_DIALOG)
    results.append(check("Case 3: retain relevant facts across summary segments", s3, must=CASE3_MUST,
                         src_digits=CASE3_OLD + CASE3_DIALOG))
    print(f"\n{sum(results)}/{len(results)} passed")
    raise SystemExit(0 if all(results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
