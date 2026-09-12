from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "tracedaai.db"
RULES_PATH = PROJECT_ROOT / "rules.yaml"

KNOWN_AI_PROCESSES = {
    "claude": "Claude Code",
    "cursor": "Cursor",
    "ollama": "Ollama",
    "copilot": "GitHub Copilot",
    "codex": "Codex CLI",
}


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
