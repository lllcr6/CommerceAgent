from pydantic_settings import BaseSettings, SettingsConfigDict

from app.paths import RUNTIME_DIR


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


    chat_model: str


    chat_base_url: str
    chat_api_key: str
    embed_base_url: str = "https://api.siliconflow.cn/v1"
    embed_api_key: str
    rerank_base_url: str = "https://api.siliconflow.cn/v1"
    rerank_api_key: str


    chat_thinking: str = ""
    chat_reasoning_effort: str = ""
    chat_reasoning_split: str = ""

    token_budget: int = 2000
    database_url: str = "mysql+asyncmy://root:root@localhost:3306/commerceagent"
    test_database_url: str = "mysql+asyncmy://root:root@localhost:3306/commerceagent_test"

    embed_model: str = "BAAI/bge-m3"
    milvus_collection: str = "knowledge_en_v1"
    milvus_uri: str = "http://localhost:19530"

    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    recall_top_k: int = 50
    rerank_top_k: int = 10
    subquery_split: bool = True
    rerank_min_score: float = 0.3

    max_agent_steps: int = 6


    checkpointer_db_path: str = str(RUNTIME_DIR / "graph_checkpoints.sqlite")
    topic_classifier_enabled: bool = False  # Enable only after English topic training and validation.


    intent_base_url: str = ""
    intent_api_key: str = ""
    summary_base_url: str = ""
    summary_api_key: str = ""

    judge_model: str = ""
    judge_base_url: str = ""
    judge_api_key: str = ""
    intent_model: str = ""
    intent_small_model: str = ""
    intent_mode: str = "accuracy"
    intent_conf_threshold: float = 0.6

    context_window_max_tokens: int = 0

    summary_model: str = ""

    model_context_window: int = 0

    context_budget_turns: int = 20
    max_user_input_tokens: int = 2000
    max_output_tokens: int = 10000

    system_prompt_tokens: int = 700
    evidence_tokens_per_chunk: int = 350

    layer1_ratio: float = 0.7
    layer2_reply_keep_chars: int = 240
    layer2_tool_keep_tokens: int = 200
    tool_result_max_tokens: int = 3000

    agent_step_ai_tokens: int = 500

    summary_inject_segments: int = 3
    summary_tokens_per_segment: int = 250
    budget_safety_margin: int = 1000
    # Only used when provider token usage is unavailable: four characters per token.

    mcp_logistics_url: str = "http://127.0.0.1:8101/mcp"
    mcp_aftersales_url: str = "http://127.0.0.1:8102/mcp"
    tool_default_timeout: float = 5.0
    mcp_tool_timeout: float = 10.0
    tool_max_retries: int = 2
    demo_ticket_delay_seconds: float = 0.0


    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_base_url: str = ""


    evidence_confidence_threshold: float = 0.30


settings = Settings()
