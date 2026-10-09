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


def _proxy_hops(value: str | None) -> int | None:
    """RATE_LIMIT_PROXY_HOPS as a count of trusted proxies, or None when unset or not a count."""
    try:
        hops = int((value or "").strip())
    except ValueError:
        return None
    return hops if hops >= 0 else None


class BaseConfig:
    # Flask / session
    SECRET_KEY = os.environ.get("SECRET_KEY")

    # Database — SQLite for the demo, written to stay PostgreSQL-compatible.
    # A bare relative SQLite name is stored in Flask's instance/ folder (auto-created).
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///qvault.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Dev/demo convenience: create tables + seed on startup (production would use migrations).
    # An admin script opening a live database it must not write to at startup turns it off
    # (plan D28, scripts/link_treasury.py).
    AUTO_CREATE_DB = os.environ.get("AUTO_CREATE_DB", "true").lower() == "true"

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
    # Decision reminders and "due within 24 hours" warnings (plan R4); safe to run at any rate.
    NOTIFICATION_REMINDER_CRON = os.environ.get("NOTIFICATION_REMINDER_CRON", "*/15 * * * *")
    # A key becomes due for rotation this many days after it is created.
    KEY_MAX_AGE_DAYS = int(os.environ.get("KEY_MAX_AGE_DAYS", "90"))
    # A device's bearer token stops being accepted this many days after enrolment. The server
    # cannot rotate a key whose private half it has never held, so custody is time-bounded on the
    # token instead of the key: re-enrol to continue. See ADR-0016.
    DEVICE_TOKEN_MAX_AGE_DAYS = int(os.environ.get("DEVICE_TOKEN_MAX_AGE_DAYS", "90"))

    # Sign-in, sign-up and phone pairing are rate limited per client address, in this process
    # (qvault/security/rate_limit.py). Behind a reverse proxy set RATE_LIMIT_PROXY_HOPS to the
    # number of proxies in front (Azure Container Apps' ingress: 1; Cloudflare proxying in front
    # of it: 2), or every visitor shares one bucket. Production refuses to start without it.
    RATE_LIMIT_ENABLED = os.environ.get("RATE_LIMIT_ENABLED", "true").lower() == "true"
    RATE_LIMIT_PROXY_HOPS = _proxy_hops(os.environ.get("RATE_LIMIT_PROXY_HOPS")) or 0
    # Sign-ups (both forms together) per client address per hour. Raise it for a live demo where
    # an audience signs up from one network: they all share one address.
    RATE_LIMIT_SIGNUP_PER_HOUR = int(os.environ.get("RATE_LIMIT_SIGNUP_PER_HOUR", "10"))

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
    # The witness key this log trusts, as the 16 hex characters the witness prints on startup
    # (the value ``python -m qvault.verify --expect-witness`` takes). Set: a co-signature from any
    # other key is refused and shown as a mismatch. Unset: any key is accepted, as before, and
    # admins see that the key isn't pinned. Never learnt from the witness: only this setting pins.
    WITNESS_KEY_FINGERPRINT = os.environ.get("WITNESS_KEY_FINGERPRINT") or None
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

    # The adversary lab (ADR-0021). The stored report is written by
    # ``scripts/run_attack_lab.py`` and is the only source for the database-backed attacks --
    # those forge rows and edit ledger entries, so they must never run against a live database.
    # The /attack page re-runs the algorithm-level attacks in-request, which need no database.
    ATTACK_REPORT_PATH = os.environ.get(
        "ATTACK_REPORT_PATH", str(_REPO_ROOT / "docs" / "attack-lab" / "latest.json")
    )
    ATTACK_LAB_ENABLED = os.environ.get("ATTACK_LAB_ENABLED", "false").lower() == "true"
    # Wall-clock cap on an in-request lab run. The Shor simulation is the expensive part (a
    # ~1s state-vector transform per order-finding round), so the cap exists to stop an admin
    # tying up the single worker rather than to bound anything unbounded.
    ATTACK_LAB_BUDGET_S = float(os.environ.get("ATTACK_LAB_BUDGET_S", "45"))

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

    # On-chain execution (docs/plans/onchain-execution.md). OFF everywhere by default, tests
    # included, and it stays off until every row of the plan's phone-parity checklist passes
    # (plan D15): while it is off no payment decision can be created from the web or the API.
    # Verifying or displaying a payment decision that already exists never depends on it.
    ONCHAIN_EXECUTION_ENABLED = (
        os.environ.get("ONCHAIN_EXECUTION_ENABLED", "false").lower() == "true"
    )

    # Treasury limits (plan D38). One relayer wallet pays for every vault, so a loop or a mistake
    # must not be able to empty it: no chain work starts that would take the relayer below the
    # reserve, and a vault pays for a treasury at most once per cooldown.
    TREASURY_RELAYER_RESERVE_WEI = int(
        os.environ.get("TREASURY_RELAYER_RESERVE_WEI", 15_000_000_000_000_000)
    )
    TREASURY_LINK_COOLDOWN_DAYS = int(os.environ.get("TREASURY_LINK_COOLDOWN_DAYS", 30))
    TREASURY_TICK_SECONDS = int(os.environ.get("TREASURY_TICK_SECONDS", 60))
    # Where the app writes the public record of the treasuries it links and reconfigures (plan
    # Phase 9). Unset: the committed chain/deployments/<network>.json. "none" turns it off.
    TREASURY_RECORD_PATH = os.environ.get("TREASURY_RECORD_PATH") or ""


class DevConfig(BaseConfig):
    DEBUG = True
    SECRET_KEY = BaseConfig.SECRET_KEY or _DEV_SECRET
    ENABLE_TAMPER_DEMO = os.environ.get("ENABLE_TAMPER_DEMO", "true").lower() == "true"
    GLASSBOX_ENABLED = os.environ.get("GLASSBOX_ENABLED", "true").lower() == "true"
    ATTACK_LAB_ENABLED = os.environ.get("ATTACK_LAB_ENABLED", "true").lower() == "true"


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
    # Many tests sign in and up far more often than a person would; tests/test_rate_limit.py
    # turns the limiter on where it is the subject.
    RATE_LIMIT_ENABLED = False
    LOG_ORIGIN = "qvault.test/ledger"
    WITNESS_URL = None  # tests drive the witness in-process; no sockets in the suite
    WITNESS_KEY_FINGERPRINT = None  # a test that pins sets it; never the developer's .env value
    # On in the suite so the instrumentation is exercised by every existing test that signs
    # anything -- an unwrapped value or a broken presenter then fails a vote test, loudly, rather
    # than waiting to be discovered on the /trace page during a demonstration.
    GLASSBOX_ENABLED = True
    GLASSBOX_STRICT = True
    ATTACK_LAB_ENABLED = True
    # Off, as in production: a test that creates a payment decision turns it on explicitly.
    ONCHAIN_EXECUTION_ENABLED = False
    # Never the committed record: a test that wants one points this at a temporary file.
    TREASURY_RECORD_PATH = "none"


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
        # Read now, not from the class: a wrong guess either way is a security fault (one bucket
        # for every visitor, or a bucket each client chooses), so there is no default to fall
        # back on. 0 is accepted when it is said explicitly.
        hops = _proxy_hops(os.environ.get("RATE_LIMIT_PROXY_HOPS"))
        if hops is None:
            raise RuntimeError(
                "Refusing to start: set RATE_LIMIT_PROXY_HOPS to the number of reverse proxies in "
                "front of the app (1 behind Azure Container Apps' ingress, 2 with Cloudflare "
                "proxying in front of it, 0 with none). Without it the rate limiter either counts "
                "every visitor as one or lets each client choose its own address."
            )
        self.RATE_LIMIT_PROXY_HOPS = hops


_CONFIGS = {"development": DevConfig, "testing": TestConfig, "production": ProdConfig}


def get_config(name: str | None = None):
    """Return a config object/class by name (defaults to $FLASK_ENV or development)."""
    name = name or os.environ.get("FLASK_ENV", "development")
    cfg = _CONFIGS.get(name, DevConfig)
    return cfg() if isinstance(cfg, type) and name == "production" else cfg
