"""APScheduler integration (Phase 7).

Registers three background jobs — automated key rotation, the proposal-expiry sweep, and the
witness sync — each running inside an application context. The job bodies live in services as
plain functions, so they are equally callable from a test or an admin "run now" button; the
scheduler only decides *when* they run.

The witness sync belongs here rather than in the request path. Offering a checkpoint means an
HTTP round trip to another process, and putting that in ``after_request`` would make every write
wait on a machine that might be down — turning a witness outage into a Q-Vault outage, which is
precisely backwards. On a timer, an unreachable witness costs nothing but a growing lag, which is
what the transparency page reports.
"""

from __future__ import annotations

import os

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .extensions import db


def init_scheduler(app):
    """Start the background scheduler unless disabled (tests) or this is the reloader's parent."""
    if not app.config.get("SCHEDULER_ENABLED", False):
        return None
    # Under `flask run --debug` the factory runs in two processes; only the worker (which sets
    # WERKZEUG_RUN_MAIN) should own the scheduler, so jobs are not registered twice.
    # NOTE: this guards the reloader only. A multi-worker deployment (e.g. gunicorn -w N) would
    # start N schedulers → N concurrent rotations; run the app single-worker, or run the scheduler
    # in a dedicated process, for a single owner. Ledger UNIQUE(seq) still prevents corruption.
    if app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return None

    from qvault.services import checkpoint_service, rotation_service

    def _in_context(job):
        def _run():
            with app.app_context():
                try:
                    job()
                except Exception:  # pragma: no cover - a job error must not kill the scheduler
                    db.session.rollback()
                    app.logger.exception("scheduled maintenance job failed")

        return _run

    scheduler = BackgroundScheduler(daemon=True, timezone="UTC")
    scheduler.add_job(
        _in_context(rotation_service.run_key_rotation),
        CronTrigger.from_crontab(app.config["KEY_ROTATION_CRON"], timezone="UTC"),
        id="key_rotation",
        replace_existing=True,
    )
    scheduler.add_job(
        _in_context(rotation_service.expire_stale_proposals),
        CronTrigger.from_crontab(app.config["PROPOSAL_EXPIRY_CRON"], timezone="UTC"),
        id="proposal_expiry",
        replace_existing=True,
    )
    if app.config.get("WITNESS_URL"):
        scheduler.add_job(
            _in_context(checkpoint_service.sync_witness),
            IntervalTrigger(seconds=int(app.config.get("WITNESS_SYNC_SECONDS", 60))),
            id="witness_sync",
            replace_existing=True,
        )
    scheduler.start()
    app.extensions["scheduler"] = scheduler
    return scheduler
