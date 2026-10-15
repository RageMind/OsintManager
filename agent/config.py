"""Read and save local application settings."""
import os
from pathlib import Path
from dataclasses import dataclass

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"
DEFAULTS = {
    "OPENAI_BASE_URL": "https://api.openai.com/v1",
    "OPENAI_API_KEY": "",
    "OPENAI_MODEL": "",
    "APP_TOKEN": "",
    "UI_HOST": "127.0.0.1",
    "UI_PORT": "8000",
    "DATABASE_PATH": "data/manager.sqlite3",
    "REPORT_DIR": "reports",
    "OSINT_ALLOWED_HOSTS": "github.com,bing.com,duckduckgo.com",
    "OSINT_MAX_PAGES": "5",
    "OSINT_TIMEOUT": "20",
    "OSINT_MAX_CHARS": "12000",
    "OSINT_DELAY": "0.7",
    "LLM_TIMEOUT": "60",
    "LLM_RETRIES": "4",
    "GAME_FPS": "2",
    "GAME_MEMORY": "12"
}
PROMPTS = ("planner", "extractor", "game_state", "game_decision")
SECRETS = ("OPENAI_API_KEY", "APP_TOKEN")

def values():
    data = dict(DEFAULTS)
    if ENV.exists():
        for line in ENV.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() in data:
                value = value.strip().strip('"').strip("'")
                data[key.strip()] = value
    return {k: os.environ.get(k, v) for k, v in data.items()}

def update(changes):
    data = values()
    for key, value in changes.items():
        if key not in data or not isinstance(value, str) or any(x in value for x in "\r\n\0"):
            raise ValueError("Invalid setting")
        if key in SECRETS and value == "********":
            continue
        if key in ("UI_PORT", "OSINT_MAX_PAGES", "OSINT_TIMEOUT", "OSINT_MAX_CHARS", "LLM_TIMEOUT", "LLM_RETRIES", "GAME_MEMORY"):
            if not value.isdigit() or int(value) <= 0:
                raise ValueError("Must be positive: " + key)
        data[key] = value
    ENV.write_text("".join(k + "=" + v + "\n" for k, v in data.items()), encoding="utf-8")
    try:
        ENV.chmod(0o600)
    except OSError:
        pass

def public_values():
    return {k: ("********" if k in SECRETS and v else v) for k, v in values().items()}

def get_prompt(name):
    if name not in PROMPTS:
        raise ValueError("Unknown prompt")
    return (ROOT / "prompts" / (name + ".md")).read_text(encoding="utf-8")

def update_prompt(name, content):
    if name not in PROMPTS or not isinstance(content, str) or not content.strip() or len(content) > 20000:
        raise ValueError("Invalid prompt")
    (ROOT / "prompts" / (name + ".md")).write_text(content, encoding="utf-8")

@dataclass(frozen=True)
class Settings:
    base_url: str
    api_key: str
    model: str
    token: str
    host: str
    port: int
    database: Path
    reports: Path
    hosts: frozenset[str]
    max_pages: int
    timeout: int
    max_chars: int
    delay: float
    llm_timeout: int
    retries: int
    fps: float
    game_memory: int

    @classmethod
    def load(cls):
        v = values()
        def path(key):
            p = Path(v[key]).expanduser()
            return p if p.is_absolute() else ROOT / p
        return cls(
            v["OPENAI_BASE_URL"].rstrip("/"), v["OPENAI_API_KEY"], v["OPENAI_MODEL"],
            v["APP_TOKEN"], v["UI_HOST"], int(v["UI_PORT"]),
            path("DATABASE_PATH"), path("REPORT_DIR"),
            frozenset(x.strip().lower() for x in v["OSINT_ALLOWED_HOSTS"].split(",") if x.strip()),
            min(20, int(v["OSINT_MAX_PAGES"])), int(v["OSINT_TIMEOUT"]),
            min(40000, int(v["OSINT_MAX_CHARS"])), float(v["OSINT_DELAY"]),
            int(v["LLM_TIMEOUT"]), min(8, int(v["LLM_RETRIES"])),
            min(5, float(v["GAME_FPS"])), min(100, int(v["GAME_MEMORY"]))
        )
