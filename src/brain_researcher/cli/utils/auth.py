import os
from pathlib import Path
from typing import Optional

TOKEN_PATH = Path.home() / ".brain_researcher" / "token"


def get_token() -> Optional[str]:
    token = os.environ.get("AGENT_TOKEN")
    if token:
        return token.strip()
    try:
        data = TOKEN_PATH.read_text().strip()
        return data or None
    except FileNotFoundError:
        return None


def save_token(token: str) -> Path:
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(token.strip())
    return TOKEN_PATH


def clear_token() -> None:
    try:
        TOKEN_PATH.unlink()
    except FileNotFoundError:
        pass
