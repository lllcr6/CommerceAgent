"""Extract and deduplicate conversation knowledge into staging. Human approval is required before publication."""
import asyncio

from app.kb import mining


async def main() -> None:
    stats = await mining.mine()
    print(f"Conversation mining complete: {stats}. Kept answers await human review; no knowledge has been published.")


if __name__ == "__main__":
    asyncio.run(main())
