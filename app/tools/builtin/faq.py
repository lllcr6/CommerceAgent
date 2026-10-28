from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.config import settings
from app.core import query_understanding, retrieval, selfcheck
from app.tools import registry


class FaqInput(BaseModel):
    keyword: str = Field(description="The customer question about policies, rules, or procedures")
    category: str | None = Field(default=None, description="Optional category filter, such as shipping, returns, or product manuals")


@tool(args_schema=FaqInput)
async def query_faq(keyword: str, category: str | None = None) -> dict:
    """Search policy and product evidence with hybrid retrieval and reranking. Cite numbered evidence; refuse unsupported answers when sufficient is false."""
    u = await query_understanding.understand(keyword)
    query = u["standard"]

    bm25_text = query + (" " + " ".join(u["expanded"]) if u["expanded"] else "")

    hits = await retrieval.search_knowledge(
        query, strategy="hybrid_rerank", category=category, bm25_text=bm25_text)


    if category and (not hits or hits[0]["rerank_score"] < settings.rerank_min_score):
        hits = await retrieval.search_knowledge(
            query, strategy="hybrid_rerank", category=None, bm25_text=bm25_text)


    top = hits[0]["rerank_score"] if hits else 0.0
    if not hits or top < settings.rerank_min_score:
        return {"sufficient": False, "source": "retrieval_low_conf",
                "reason": f"Insufficient retrieval evidence (top={top:.3f})", "citations": []}


    ev_texts = [f"{h['question']} {h['answer']}" for h in hits]
    chk = await selfcheck.check_sufficient(query, ev_texts)
    if not chk["useful"]:
        return {"sufficient": False, "source": "self_check",
                "reason": chk["reason"], "citations": []}


    arranged = retrieval.arrange_head_tail(hits)
    citations = [
        {"n": i + 1, "id": h["id"], "section_path": h["section_path"],
         "question": h["question"], "answer": h["answer"], "content_type": h["content_type"]}
        for i, h in enumerate(arranged)
    ]
    evidence = "\n".join(f"[{c['n']}] {c['question']}: {c['answer']}" for c in citations)
    return {"sufficient": True, "evidence": evidence, "citations": citations}


registry.register(registry.spec_from_langchain_tool(
    query_faq, source="builtin", timeout=30.0, max_retries=0))
