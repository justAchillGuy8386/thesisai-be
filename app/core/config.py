from typing import List, Union
from pydantic import AnyHttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    PROJECT_NAME: str = "ThesisAI Backend"
    API_V1_STR: str = "/api"
    DEBUG: bool = True
    PORT: int = 8000
    HOST: str = "0.0.0.0"

    # CORS
    CORS_ORIGINS: List[str] = ["http://localhost:3000"]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)

    # Database
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/thesisai"

    # Ollama
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    LLM_MODEL: str = "qwen2.5:7b"
    EMBEDDING_MODEL: str = "bge-m3"

    # Storage paths & Data Lifecycle (Privacy-First)
    STORAGE_DIR: str = str(Path(__file__).resolve().parent.parent.parent / "storage")
    AUDIO_RETENTION_HOURS: int = 24
    AUTO_DELETE_RAW_DOCS: bool = True
    MAX_UPLOAD_SIZE_MB: int = 50
    MAX_AUDIO_SIZE_MB: int = 10

    @property
    def documents_dir(self) -> Path:
        p = Path(self.STORAGE_DIR) / "uploads" / "documents"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def audio_dir(self) -> Path:
        p = Path(self.STORAGE_DIR) / "uploads" / "audio"
        p.mkdir(parents=True, exist_ok=True)
        return p


settings = Settings()
