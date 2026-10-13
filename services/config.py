import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


class ConfigurationError(RuntimeError):
    pass


def project_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def read_only() -> bool:
    return os.getenv("DEMO_MODE", "false").lower() == "true"


def check_writable() -> None:
    if read_only():
        raise ConfigurationError("DEMO_MODE is read-only; processing and review changes are disabled")
