"""Flask extension singletons, created unbound and initialised in the app factory.

Kept in their own module so any part of the app can import them without triggering a
circular import back into the factory.
"""

from __future__ import annotations

from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect

db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()

login_manager.login_view = "auth.login"
login_manager.login_message_category = "warning"
