"""Q-Vault application package and factory.

``create_app`` wires configuration, the crypto-agile registry, the database, authentication,
CSRF, and blueprints. Tables are created and the database seeded (algorithm_config + genesis
ledger entry) on startup for dev/demo convenience.

**Nothing is imported at module level.** ``qvault.verify`` and ``qvault.transparency`` are meant
to run on a third party's machine with neither Flask nor a database installed, and every import
here would be inherited by ``import qvault.verify``. Keeping the factory's dependencies inside the
factory is what makes ``tests/test_verifier_purity.py`` able to assert that, rather than merely
document it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only, never executed at runtime
    from flask import Flask

__version__ = "0.1.0"


def _glassbox_actor() -> str | None:
    """Who triggered the request being traced, for the trace header.

    A display name, never an email or an id: the trace page is a demonstration surface that gets
    projected onto a wall and screenshotted into a dissertation, and it should not be the one
    place in the product that leaks an address.
    """
    try:
        from flask_login import current_user

        if current_user.is_authenticated:
            return current_user.display_name or f"user {current_user.id}"
    except Exception:  # noqa: BLE001 - no session, no actor; never fail a request over a label
        return None
    return None


def create_app(config_name: str | None = None) -> Flask:
    from flask import Flask, jsonify, request
    from werkzeug.exceptions import HTTPException

    from config import get_config

    from .crypto import build_registry
    from .extensions import csrf, db, login_manager

    app = Flask(__name__)
    app.config.from_object(get_config(config_name))
    app.config.setdefault("VERSION", __version__)

    # Build the crypto-agile registry exactly once and attach it to the app. Every service
    # resolves providers from here by alg_id — never by importing a backend directly.
    registry = build_registry(prefer=app.config["CRYPTO_BACKEND"])
    app.extensions["crypto"] = registry

    # --- Extensions -------------------------------------------------------
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    @login_manager.user_loader
    def load_user(user_id: str):
        from .models.user import User

        return db.session.get(User, int(user_id))

    # --- Blueprints -------------------------------------------------------
    from .blueprints.account import bp as account_bp
    from .blueprints.admin import bp as admin_bp
    from .blueprints.api import bp as api_bp
    from .blueprints.approvals import bp as approvals_bp
    from .blueprints.auth import bp as auth_bp
    from .blueprints.core import bp as core_bp
    from .blueprints.docs import bp as docs_bp
    from .blueprints.glassbox import bp as glassbox_bp
    from .blueprints.ledger import bp as ledger_bp
    from .blueprints.record import bp as record_bp
    from .blueprints.vaults import bp as vaults_bp
    from .blueprints.verify import bp as verify_bp

    app.register_blueprint(core_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(approvals_bp)
    app.register_blueprint(vaults_bp)
    app.register_blueprint(ledger_bp)
    app.register_blueprint(account_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(docs_bp)
    app.register_blueprint(verify_bp)
    # Every route inside 404s unless GLASSBOX_ENABLED, so registering it unconditionally keeps
    # one gate in one place rather than splitting it between here and the blueprint.
    app.register_blueprint(glassbox_bp)
    # The public record of a shared decision. GET-only and session-free, so it needs neither
    # login_required nor a CSRF exemption -- there is no form here to forge.
    app.register_blueprint(record_bp)
    # Public verification takes no session and writes nothing, so there is no state for a CSRF
    # token to protect — and requiring one would break `curl -F bundle=@decision.json /verify/`,
    # which is how anyone would actually script a check.
    csrf.exempt(verify_bp)

    app.register_blueprint(api_bp)
    # The mobile client authenticates with a bearer token in a header, which a browser never
    # attaches to a cross-site request. There is no ambient authority for a forged POST to ride
    # on, so a CSRF token here would only be a second copy of the token already in the header.
    # This holds ONLY while no /api/ view is reachable by session cookie — enforced mechanically
    # by the before_request in qvault/blueprints/api.py, not by convention.
    csrf.exempt(api_bp)

    @app.errorhandler(HTTPException)
    def _json_errors_under_api(exc):
        """Return JSON for /api/ failures; leave the HTML surface byte-for-byte unchanged.

        Registered app-wide rather than on the blueprint because a 404 or 405 raised during URL
        *matching* has no blueprint to attribute it to — ``request.blueprint`` is None — so a
        blueprint-scoped handler would never fire for an unknown /api/ path, and a mobile client
        would get an HTML error page where it expected JSON. Returning ``exc`` unchanged for
        everything else reproduces Werkzeug's default page exactly.
        """
        if not request.path.startswith("/api/"):
            return exc
        return (
            jsonify(
                ok=False,
                code=(exc.name or "error").lower().replace(" ", "_"),
                error=exc.description,
            ),
            exc.code,
        )

    # Two things every template may need: the navigation badge ("3 waiting on you"), and whether
    # this deployment is a demonstration instance. Both are computed once per request here rather
    # than threaded through every render_template call — `demo_enabled` in particular is a global
    # configuration predicate, and passing it by hand meant the signed-out pages that needed it
    # silently rendered without it.
    @app.context_processor
    def _inject_globals():
        from flask_login import current_user

        from .security.demo_gate import demo_enabled

        globals_ = {
            "demo_enabled": demo_enabled(),
            # The rail needs to know whether to offer /trace at all. Read from config rather than
            # from a url_for probe, so the link and the blueprint's 404 gate agree by sharing one
            # source of truth instead of two.
            "glassbox_enabled": bool(app.config.get("GLASSBOX_ENABLED")),
        }
        if current_user.is_authenticated:
            from .services import inbox_service

            globals_["pending_count"] = inbox_service.awaiting_signature(current_user)
        return globals_

    # --- Glass box: record what the cryptography did, for the /trace page (ADR-0020) ----------
    # An operation is opened for *every* request, because whether a request does any cryptography
    # is not knowable in advance, and closed in teardown — which runs even when the view raises,
    # so a failed vote is traced rather than lost. `close_operation` discards operations that
    # recorded no steps, so opening one unconditionally costs a dataclass that is immediately
    # thrown away, and only requests that actually did cryptographic work reach the page.
    #
    # Registered here rather than in a blueprint: the steps worth seeing are appended by
    # `after_request` (the head anchor and the Merkle checkpoint), which is outside every
    # blueprint's view function.
    @app.before_request
    def _open_glassbox_operation():
        from flask import g, request

        from . import glassbox

        g.glassbox = glassbox.open_operation(
            request.endpoint or request.path, kind="request", actor=_glassbox_actor()
        )

    @app.teardown_request
    def _close_glassbox_operation(exc):
        from flask import g

        from . import glassbox

        glassbox.close_operation(g.pop("glassbox", None), failed=exc is not None)

    # --- Database: create tables + seed config/genesis --------------------
    from .services.bootstrap_service import init_database

    init_database(app)

    # --- SYSTEM head anchor + Merkle checkpoint: re-sign once per request that appended entries.
    # Doing it here (rather than inside append()) keeps a single anchor per logical operation and
    # never re-signs a same-seq hash change (a rewrite), so tampering stays detectable.
    #
    # The checkpoint is a second, stronger commitment over the same head (ADR-0015): the anchor
    # says "this head is mine", the checkpoint says "and here is a root you can prove single
    # entries against". Both are best-effort — a failure to sign must never fail a user's request,
    # and a *stalled* checkpoint sequence is itself the tamper signal, so swallowing the error
    # here loses nothing that verification would not surface anyway.
    @app.after_request
    def _anchor_ledger_head(response):
        from flask import request

        if request.endpoint == "static":
            return response
        from .services import checkpoint_service, ledger_service

        try:
            ledger_service.maybe_anchor()
            checkpoint_service.maybe_checkpoint()
        except Exception:  # noqa: BLE001 - anchoring must never break the response
            db.session.rollback()
        return response

    # --- Scheduler: automated key rotation + proposal-expiry sweep --------
    from .scheduler import init_scheduler

    init_scheduler(app)

    return app
