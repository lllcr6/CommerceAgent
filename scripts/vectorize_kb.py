"""Embed pending knowledge chunks and upsert the search index idempotently."""
import asyncio

from app.db.base import engine
from app.kb import dualwrite, milvus_client


async def main() -> None:
    client = milvus_client.get_client()
    milvus_client.ensure_collection(client)
    n = await dualwrite.vectorize_pending(client)
    print(f"Indexed {n} pending passages. The search index now contains {milvus_client.count(client)} passages.")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
