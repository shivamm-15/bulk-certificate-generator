"""Runtime configuration, read from environment variables."""
import os
from pathlib import Path


class Settings:
    def __init__(self) -> None:
        self.database_url: str = os.getenv("DATABASE_URL", "sqlite:///./certificates.db")
        self.storage_dir: Path = Path(os.getenv("CERT_STORAGE_DIR", "./generated_certificates"))
        self.max_recipients: int = int(os.getenv("MAX_RECIPIENTS", "1000"))


settings = Settings()
