"""Single source inventory shared by CLI ingestion, previews, and the admin UI."""

from app.paths import KNOWLEDGE_DIR


KB_DIR = KNOWLEDGE_DIR


SOURCE_TYPES: dict[str, str] = {
    "product-faq.md": "faq",
    "returns-policy.md": "policy",
    "after-sales-manual.md": "manual",
    "product-specs.md": "spec",
    "member-benefits.md": "policy",
    "billing-shipping.md": "policy",
}


CONTENT_TYPES: tuple[str, ...] = ("faq", "policy", "manual", "spec")
CONTENT_TYPE_DESC: dict[str, str] = {
    "faq": "Product FAQ: use customer questions as headings",
    "policy": "Store policies: section headings and parent categories",
    "manual": "Support manual: split by section headings",
    "spec": "Product specifications: include model numbers for exact matching",
}
