"""English topic definitions derived from the shared training/serving schema."""
from dataclasses import dataclass
from app.topic_schema import ID2LABEL, LABEL2ID, NUM_CLASSES, SCHEMA, SEVERITY, TOPIC_NAMES

@dataclass(frozen=True)
class TopicClass:
    name: str
    boundary: str
    examples: tuple[str, ...]
    severity: str

TOPIC_CLASSES = tuple(
    TopicClass(label["id"], label["definition"], (), SEVERITY[label["id"]])
    for label in SCHEMA["labels"]
)

def terminology_table() -> str:
    """Render stable topic IDs and their annotation boundaries for labeling prompts."""
    return "\n".join(f"- {topic.name}: {topic.boundary}" for topic in TOPIC_CLASSES)
