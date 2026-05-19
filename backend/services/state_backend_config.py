import os


DEFAULT_STATE_BACKEND = "file"
DEFAULT_STATE_DIR = os.path.join("data", "runtime")
DEFAULT_STATE_REDIS_URL = "redis://redis:6379/0"


def resolve_state_backend() -> str:
    return (os.getenv("STATE_BACKEND") or DEFAULT_STATE_BACKEND).strip().lower()


def resolve_state_dir() -> str:
    return os.getenv("STATE_DIR", DEFAULT_STATE_DIR)


def resolve_state_redis_url() -> str:
    return os.getenv("STATE_REDIS_URL", DEFAULT_STATE_REDIS_URL)
