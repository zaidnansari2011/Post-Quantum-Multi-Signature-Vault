"""Application configuration.

Values are read from the environment (``.env`` is loaded automatically in development).
Production refuses to start without the two critical secrets, so a misconfigured deploy
fails loudly instead of running with insecure defaults.
"""

from __future__ import annotations

import os
import pathlib

from dotenv import load_dotenv
from sqlalchemy.pool import StaticPool

load_dotenv()

_DEV_SECRET = "dev-insecure-secret-key-change-me"
_REPO_ROOT = pathlib.Path(__file__).resolve().parent


class BaseConfig:
    # Flask / session
    SECRET_KEY = os.environ.get("SECRET_KEY")

    # Database — SQLite for the demo, written to stay PostgreSQL-compatible.
    # A bare relative SQLite name is stored in Flask's instance/ folder (auto-created).
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///qvault.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Dev/demo convenience: create tables + seed on startup (production would use migrations).
    AUTO_CREATE_DB = True

    # Maximum upload size — files are encrypted at rest; larger uploads are rejected (413).
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MiB

    # Crypto-agility defaults (only affect NEW keys; existing artefacts keep their own alg_id)
    CRYPTO_BACKEND = os.environ.get("CRYPTO_BACKEND", "quantcrypt")
    DEFAULT_SIG_ALGORITHM = os.environ.get("DEFAULT_SIG_ALGORITHM", "ML-DSA-65")
    DEFAULT_KEM_ALGORITHM = os.environ.get("DEFAULT_KEM_ALGORITHM", "ML-KEM-768")

    # Server master key — wraps vault-KEM and SYSTEM keys (§4.3). Base64/hex string.
    SERVER_MASTER_KEY = os.environ.get("SERVER_MASTER_KEY")

    # Scheduler (APScheduler) — automated key rotation + proposal-expiry sweep (Phase 7)
    SCHEDULER_ENABLED = os.environ.get("SCHEDULER_ENABLED", "true").lower() == "true"
    KEY_ROTATION_CRON = os.environ.get("KEY_ROTATION_CRON", "0 3 * * *")
    PROPOSAL_EXPIRY_CRON = os.environ.get("PROPOSAL_EXPIRY_CRON", "*/15 * * * *")
    # A key becomes due for rotation this many days after it is created.
    KEY_MAX_AGE_DAYS = int(os.environ.get("KEY_MAX_AGE_DAYS", "90"))
    # A device's bearer token stops being accepted this many days after enrolment. The server
    # cannot rotate a key whose private half it has never held, so custody is time-bounded on the
    # token instead of the key: re-enrol to continue. See ADR-0016.
    DEVICE_TOKEN_MAX_AGE_DAYS = int(os.environ.get("DEVICE_TOKEN_MAX_AGE_DAYS", "90"))

    # The deliberate tamper demonstration is dev/demo only and OFF by default.
    ENABLE_TAMPER_DEMO = os.environ.get("ENABLE_TAMPER_DEMO", "false").lower() == "true"

    # Transparency log (ADR-0015). LOG_ORIGIN names this log inside every signed checkpoint, so
    # a checkpoint from one deployment can never be replayed as another's; change it per instance.
    LOG_ORIGIN = os.environ.get("LOG_ORIGIN", "qvault.local/ledger")
    # The witness is a SEPARATE process holding its own key — see witness/README.md. Unset means
    # "no witness", which is reported honestly rather than hidden: checkpoints are then signed
    # only by the log itself and cannot survive an operator who controls this database.
    WITNESS_URL = os.environ.get("WITNESS_URL")
    WITNESS_TIMEOUT_S = float(os.environ.get("WITNESS_TIMEOUT_S", "3.0"))
    # Offered on a timer, never in the request path: an unreachable witness must cost a growing
    # lag on the transparency page, not latency on every write.
    WITNESS_SYNC_SECONDS = int(os.environ.get("WITNESS_SYNC_SECONDS", "60"))

    # Benchmark (Phase 8). The canonical report is produced offline by
    # ``scripts/run_benchmark.py``; the admin page only renders whatever it finds here.
    BENCHMARK_REPORT_PATH = os.environ.get(
        "BENCHMARK_REPORT_PATH", str(_REPO_ROOT / "docs" / "benchmarks" / "latest.json")
    )
    # A live in-request run is a demo aid, not a measurement: it is capped hard so a page
    # request can never hang the single-worker dev server. The budget is the TOTAL wall clock
    # for the whole run, divided across the operations it measures.
    BENCHMARK_LIVE_MAX_ITERATIONS = int(os.environ.get("BENCHMARK_LIVE_MAX_ITERATIONS", "5"))
    BENCHMARK_LIVE_BUDGET_S = float(os.environ.get("BENCHMARK_LIVE_BUDGET_S", "10"))

    # Glass box (ADR-0020): the live cryptographic trace at /trace. OFF by default and
    # administrator-only when on. It is an instrument for demonstration and for the dissertation,
    # not a product feature -- it prints real intermediate values (canonical payloads, public
    # keys, signatures, Merkle nodes) from live operations, and although the redaction layer is
    # allowlist-based and withholds every secret by construction, the honest default for a page
    # that exists to reveal internals is off.
    GLASSBOX_ENABLED = os.environ.get("GLASSBOX_ENABLED", "false").lower() == "true"
    # Raise on a value traced without a presenter instead of silently withholding it. Defaults to
    # TESTING, so the suite fails on an unwrapped value rather than shipping a redaction that
    # merely happened to be safe.
    GLASSBOX_STRICT = os.environ.get("GLASSBOX_STRICT", "").lower() == "true" or None


class DevConfig(BaseConfig):
    DEBUG = True
    SECRET_KEY = BaseConfig.SECRET_KEY or _DEV_SECRET
    ENABLE_TAMPER_DEMO = os.environ.get("ENABLE_TAMPER_DEMO", "true").lower() == "true"
    GLASSBOX_ENABLED = os.environ.get("GLASSBOX_ENABLED", "true").lower() == "true"


class TestConfig(BaseConfig):
    TESTING = True
    SECRET_KEY = "test-secret-key"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    # Keep the single in-memory DB alive across connections within a test run.
    SQLALCHEMY_ENGINE_OPTIONS = {
        "connect_args": {"check_same_thread": False},
        "poolclass": StaticPool,
    }
    SERVER_MASTER_KEY = "0" * 64
    ENABLE_TAMPER_DEMO = True
    WTF_CSRF_ENABLED = False
    SCHEDULER_ENABLED = False  # tests drive the rotation/expiry jobs directly, no background thread
    LOG_ORIGIN = "qvault.test/ledger"
    WITNESS_URL = None  # tests drive the witness in-process; no sockets in the suite
    # On in the suite so the instrumentation is exercised by every existing test that signs
    # anything -- an unwrapped value or a broken presenter then fails a vote test, loudly, rather
    # than waiting to be discovered on the /trace page during a demonstration.
    GLASSBOX_ENABLED = True
    GLASSBOX_STRICT = True


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
