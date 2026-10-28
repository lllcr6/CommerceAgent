import httpx

from app.config import settings
from app.core.rerank import _rerank_url


def main() -> None:
    url = _rerank_url()
    payload = {
        "model": settings.rerank_model,
        "query": "Who pays return shipping?",
        "documents": [
            "Standard shipping is free at $49; otherwise it costs $4.95.",
            "For a change-of-mind return within 30 days, the customer pays return shipping.",
            "The Self-Cleaning Litter Box Pro supports automatic cleaning.",
        ],


        "top_n": 3,
    }
    r = httpx.post(url, json=payload,
                   headers={"Authorization": f"Bearer {settings.rerank_api_key}"}, timeout=60)
    r.raise_for_status()
    data = r.json()
    print("Provider response:", data)
    results = data["results"]
    assert results, "The reranker returned no results"
    top = max(results, key=lambda x: x["relevance_score"])
    print(f"Top result index={top['index']} score={top['relevance_score']:.4f}")
    assert top["index"] == 1, "The return shipping question should match the second passage"
    print("PASS: Reranking service is available")


if __name__ == "__main__":
    main()
