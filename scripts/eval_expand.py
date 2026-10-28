import asyncio

from app.core.query_understanding import expand_queries

CASES = ["Can I return the pet fountain?", "Can I request a refund for the defective feeder in order 1001?", "How do I request warranty support for a broken litter box?"]


async def main():
    for q in CASES:
        qs = await expand_queries(q)
        print(f"{'✅' if len(qs) == 3 else '⚠️'} {q!r} -> {qs}(count={len(qs)})")
    print("\nExpect three distinct queries preserving key entities. Record missing or invalid structured outputs as failures.")


if __name__ == "__main__":
    asyncio.run(main())
