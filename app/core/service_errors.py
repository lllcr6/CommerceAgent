"""Safe, English user-facing retrieval dependency errors."""
class KnowledgeServiceError(RuntimeError):
    def __init__(self, component: str):
        self.component = component
        label = {'embedding':'embedding service', 'rerank':'reranking service', 'retrieval':'search database'}.get(component, 'retrieval service')
        super().__init__(f'The knowledge {label} is temporarily unavailable. Please try again or contact support.')
