import asyncio

from openai import AsyncOpenAI

from app.config import settings


async def main() -> None:
    client = AsyncOpenAI(base_url=settings.embed_base_url, api_key=settings.embed_api_key)
    resp = await client.embeddings.create(model=settings.embed_model, input=["How much is postage?", "How are shipping charges calculated?"])
    dims = [len(d.embedding) for d in resp.data]
    print(f"Returned {len(resp.data)} vectors; dimensions={dims}")
    assert dims and dims[0] == 1024, f"Expected 1024 dimensions; got {dims}"
    print("PASS: Configured embedding provider returned 1024-dimensional vectors")


if __name__ == "__main__":
    asyncio.run(main())
