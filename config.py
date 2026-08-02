"""Application configuration.

Values are read from the environment (``.env`` is loaded automatically in development).
Production refuses to start without the two critical secrets, so a misconfigured deploy
fails loudly instead of running with insecure defaults.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

_DEV_SECRET = "dev-insecure-secret-key-change-me"


class BaseConfig:
    # Flask / session
    SECRET_KEY = os.environ.get("SECRET_KEY")

    # Database — SQLite for the demo, written to stay PostgreSQL-compatible.
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///instance/qvault.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Crypto-agility defaults (only affect NEW keys; existing artefacts keep their own alg_id)
    CRYPTO_BACKEND = os.environ.get("CRYPTO_BACKEND", "quantcrypt")
    DEFAULT_SIG_ALGORITHM = os.environ.get("DEFAULT_SIG_ALGORITHM", "ML-DSA-65")
    DEFAULT_KEM_ALGORITHM = os.environ.get("DEFAULT_KEM_ALGORITHM", "ML-KEM-768")

    # Server master key — wraps vault-KEM and SYSTEM keys (§4.3). Base64/hex string.
    SERVER_MASTER_KEY = os.environ.get("SERVER_MASTER_KEY")

    # Scheduler cron expressions
    KEY_ROTATION_CRON = os.environ.get("KEY_ROTATION_CRON", "0 3 * * *")
    PROPOSAL_EXPIRY_CRON = os.environ.get("PROPOSAL_EXPIRY_CRON", "*/15 * * * *")

    # The deliberate tamper demonstration is dev/demo only and OFF by default.
    ENABLE_TAMPER_DEMO = os.environ.get("ENABLE_TAMPER_DEMO", "false").lower() == "true"


class DevConfig(BaseConfig):
    DEBUG = True
    SECRET_KEY = BaseConfig.SECRET_KEY or _DEV_SECRET
    ENABLE_TAMPER_DEMO = os.environ.get("ENABLE_TAMPER_DEMO", "true").lower() == "true"


class TestConfig(BaseConfig):
    TESTING = True
    SECRET_KEY = "test-secret-key"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SERVER_MASTER_KEY = "0" * 64
    ENABLE_TAMPER_DEMO = True
    WTF_CSRF_ENABLED = False


class ProdConfig(BaseConfig):
    DEBUG = False

    def __init__(self) -> None:
        missing = [
            name for name in ("SECRET_KEY", "SERVER_MASTER_KEY") if not getattr(BaseConfig, name)
        ]
        if missing:
            raise RuntimeError(
                "Refusing to start: missing required secrets "
                + ", ".join(missing)
                + ". Set them in the environment."
            )


_CONFIGS = {"development": DevConfig, "testing": TestConfig, "production": ProdConfig}


def get_config(name: str | None = None):
    """Return a config object/class by name (defaults to $FLASK_ENV or development)."""
    name = name or os.environ.get("FLASK_ENV", "development")
    cfg = _CONFIGS.get(name, DevConfig)
    return cfg() if isinstance(cfg, type) and name == "production" else cfg
