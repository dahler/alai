import json
from pydantic_settings import BaseSettings
from pydantic import field_validator
from functools import lru_cache


class Settings(BaseSettings):
    # Application
    APP_NAME: str = "ALAI"
    DEBUG: bool = False

    # Database
    DATABASE_URL: str = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/alai"
    )

    # JWT
    JWT_SECRET_KEY: str = "your-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_MINUTES: int = 60 * 24 * 7  # 7 days

    # Microsoft OAuth
    MICROSOFT_CLIENT_ID: str = ""
    MICROSOFT_CLIENT_SECRET: str = ""
    MICROSOFT_TENANT_ID: str = "common"
    MICROSOFT_REDIRECT_URI: str = "http://localhost:8000/api/auth/callback"

    # Ollama
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_TEXT_MODEL: str = "gemma3:4b"  # For chat responses
    OLLAMA_VISION_MODEL: str = "qwen2.5vl"  # For requests with images
    OLLAMA_ROUTER_MODEL: str = "gemma3:1b"  # Small model for routing
    OLLAMA_AGENT_MODEL: str = "qwen2.5:14b"  # For agent/planner tasks
    OLLAMA_EMBEDDING_MODEL: str = "bge-m3"  # For RAG embeddings

    # External LLM Providers (optional)
    # Falls back to Ollama if both are empty.
    ANTHROPIC_API_KEY: str = ""   # https://console.anthropic.com
    OPENAI_API_KEY: str = ""      # https://platform.openai.com

    # Tavily (Web Search)
    TAVILY_API_KEY: str = ""  # Get from https://tavily.com

    # Feature Flags
    ENABLE_KNOWLEDGE_GRAPH: bool = False

    # RAG Settings
    RAG_CHUNK_SIZE: int = 500  # Characters per chunk
    RAG_CHUNK_OVERLAP: int = 50  # Overlap between chunks
    RAG_TOP_K: int = 3  # Number of chunks to retrieve
    RAG_EMBEDDING_DIM: int = 1024  # bge-m3 output dimension

    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    # Anonymous Session
    ANONYMOUS_SESSION_COOKIE: str = "alai_session"

    # Docling remote server (optional — set to Mac Mini IP to offload parsing)
    # e.g. DOCLING_SERVER_URL=http://192.168.1.50:7777
    DOCLING_SERVER_URL: str = ""

    # File Upload
    UPLOAD_DIR: str = "./uploads"
    MAX_FILE_SIZE: int = 10 * 1024 * 1024  # 10MB

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return [origin.strip() for origin in v.split(",")]
        return v

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
