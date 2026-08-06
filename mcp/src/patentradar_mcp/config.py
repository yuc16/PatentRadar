from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    public_base_url: str
    host: str
    port: int
    debug: bool

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = Path(os.getenv("PATENTRADAR_MCP_DATA_DIR", "data")).resolve()
        public_base_url = os.getenv("PATENTRADAR_PUBLIC_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
        return cls(
            data_dir=data_dir,
            public_base_url=public_base_url,
            host=os.getenv("PATENTRADAR_MCP_HOST", "127.0.0.1"),
            port=int(os.getenv("PATENTRADAR_MCP_PORT", "8000")),
            debug=os.getenv("PATENTRADAR_MCP_DEBUG", "").lower() in {"1", "true", "yes"},
        )
