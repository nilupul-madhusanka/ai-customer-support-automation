import os
from pathlib import Path

from dotenv import load_dotenv
from services.errors import ApplicationError

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


class ConfigurationError(ApplicationError, RuntimeError):
    pass


def project_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def read_only() -> bool:
    return boolean_setting("READ_ONLY", False)


def boolean_setting(name: str, default: bool) -> bool:
    value = os.getenv(name, str(default)).strip().lower()
    if value not in ("true", "false"):
        raise ConfigurationError(f"{name} must be true or false; fix configuration before making changes.")
    return value == "true"


def check_writable() -> None:
    if read_only():
        raise ConfigurationError("READ_ONLY is enabled; processing and review changes are disabled")


def integer_setting(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        raise ConfigurationError(f"{name} must be an integer between {minimum} and {maximum}.") from None
    if not minimum <= value <= maximum:
        raise ConfigurationError(f"{name} must be between {minimum} and {maximum}.")
    return value
