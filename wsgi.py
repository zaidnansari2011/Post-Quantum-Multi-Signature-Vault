"""WSGI entrypoint.

Run in development with:
    flask --app wsgi run --debug
or point a production WSGI server (gunicorn/waitress) at ``wsgi:app``.
"""

from __future__ import annotations

from qvault import create_app

app = create_app()


if __name__ == "__main__":
    app.run(debug=True)
