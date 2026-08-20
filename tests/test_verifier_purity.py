"""The import boundary that makes "you can check this without us" true.

``qvault.verify`` is meant to run on a stranger's laptop against a file they were emailed. If it
reaches for Flask, SQLAlchemy or a model class, then verifying a decision quietly requires a web
framework, a database driver and — one convenient import later — a database. This is exactly the
kind of property that erodes gradually and invisibly, so it is asserted mechanically rather than
written in a docstring and hoped for.

The check runs in a **subprocess** and inspects ``sys.modules`` afterwards. That catches transitive
imports, which an AST scan of the package's own source would miss: the failure mode in practice is
never ``import flask`` in ``core.py``, it is importing a helper that imports a service that imports
the extensions module.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys

FORBIDDEN = ("flask", "sqlalchemy", "flask_sqlalchemy", "qvault.models", "qvault.extensions")

PROBE = """
import sys
import {module}
loaded = [m for m in {forbidden!r} if m in sys.modules]
print(",".join(loaded))
"""


def _modules_pulled_in_by(module: str) -> list[str]:
    result = subprocess.run(
        [sys.executable, "-c", PROBE.format(module=module, forbidden=FORBIDDEN)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, f"importing {module} failed:\n{result.stderr}"
    return [m for m in result.stdout.strip().split(",") if m]


def test_the_verifier_does_not_pull_in_flask_or_the_database():
    assert _modules_pulled_in_by("qvault.verify") == []


def test_the_transparency_package_does_not_pull_in_flask_or_the_database():
    """The witness imports this, and the witness must not be able to reach Q-Vault's state."""
    assert _modules_pulled_in_by("qvault.transparency") == []


def test_the_cli_does_not_pull_in_flask_or_the_database():
    assert _modules_pulled_in_by("qvault.verify.__main__") == []


def test_importing_the_application_package_alone_starts_nothing():
    """``import qvault`` must stay inert; the factory's dependencies live inside the factory."""
    assert _modules_pulled_in_by("qvault") == []


def test_the_verifier_still_works_without_any_application_configuration(tmp_path):
    """The end-to-end version of the same claim.

    Run from a directory that is not the project, with an environment stripped of every variable
    the application reads — no ``SECRET_KEY``, no ``DATABASE_URL``, no ``SERVER_MASTER_KEY``, no
    ``.env`` in reach. A reader who was sent a bundle has none of those, and must still get an
    answer rather than a configuration error.
    """
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    script = tmp_path / "probe.py"
    script.write_text(
        "from qvault.crypto import build_registry\n"
        "from qvault.verify import verify_bundle\n"
        "report = verify_bundle({'format': 'qvault.decision/1'}, registry=build_registry())\n"
        "print(report.summary)\n",
        encoding="utf-8",
    )
    env = {
        "PYTHONPATH": str(repo_root),
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
    }
    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        cwd=str(tmp_path),
    )
    assert result.returncode == 0, result.stderr
    assert "NOT verified" in result.stdout
