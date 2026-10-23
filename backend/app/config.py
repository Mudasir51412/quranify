"""App settings — environment-driven, safe defaults for local dev only."""
import os
from pathlib import Path


class Settings:
    # SQLite for local dev/tests; set DATABASE_URL to a PostgreSQL URL in
    # production, e.g. postgresql+psycopg://user:pass@host:5432/quranify
    database_url: str = os.environ.get("DATABASE_URL", "sqlite:///./quranify.db")
    # Dev default is 32+ bytes (HS256 recommendation); production MUST
    # set JWT_SECRET in the environment.
    jwt_secret: str = os.environ.get("JWT_SECRET", "dev-only-secret-change-me-in-prod-32b")
    jwt_expire_hours: int = int(os.environ.get("JWT_EXPIRE_HOURS", "72"))
    model_id: str = os.environ.get("QURANIFY_MODEL_ID", "basharalrfooh/whisper-small-quran")
    # Transcriber: "whisper" (real model, lazy-loaded) or "fake" (tests/dev)
    transcriber: str = os.environ.get("QURANIFY_TRANSCRIBER", "whisper")
    inference_device: str = os.environ.get("QURANIFY_DEVICE", "auto")  # auto | cpu | cuda
    inference_engine: str = os.environ.get("QURANIFY_ENGINE", "auto")
    warm_model_on_startup: bool = os.environ.get("QURANIFY_WARMUP", "1").strip().lower() not in {"0", "false", "no"}
    optimized_model_dir: str = os.environ.get(
        "QURANIFY_LIVE_MODEL", str(Path(__file__).resolve().parents[2] / "models" / "whisper-small-quran-ct2"))


settings = Settings()
