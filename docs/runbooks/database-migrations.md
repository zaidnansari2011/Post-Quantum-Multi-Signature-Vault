# Runbook — database migrations

For whoever changes Q-Vault's schema or operates one of its databases. Alembic was introduced in
the rework (plan [S8](../plans/saas-rework.md)) because `db.create_all()` creates missing tables
but never changes an existing one, and the workspace layer (Phase R3) has to add columns to tables
that already hold data.

## What there is

- `alembic.ini` and `migrations/` at the repository root. `migrations/env.py` reads the models'
  metadata (`qvault.models`) and the database URL the app would use.
- **`0001_baseline`**: the schema as the models define it at tag `v1-working-2026-10-04`, which
  is the schema every existing database already has.
- **`0002_workspaces`** (plan R3): three new tables (`workspaces`, `workspace_members`,
  `invitations`) and a data step that puts every existing user into one workspace, named
  "Q-Vault": the administrator, or with none the earliest user, as its Owner, everyone else as a
  Member. It changes no existing table and writes no ledger entry. On an empty database it creates
  the tables and nothing else. `workspaces` also holds the separation-of-duties default for new
  vaults (`sod_default`, off, plan S15) and when the getting-started checklist was hidden
  (`checklist_dismissed_at`).
- Startup still runs `db.create_all()` and the test suite still builds its databases that way. A
  database built by `create_all` before the workspace tables existed gets them from `create_all`,
  and the startup step `workspace_service.ensure_default_workspace` then does what the data step
  does, once, while no workspace exists. The two routes leave identical rows
  (`tests/test_migrations.py`).
- `tests/test_migrations.py` holds the two routes together: `upgrade head` must build exactly what
  `create_all` builds, on SQLite and in the SQL it renders for PostgreSQL. A model change without a
  revision fails that test.

## Which database a command acts on

In order: `-x url=...` on the command line; `DATABASE_URL` (with `.env` loaded, as `config.py`
does); `sqlalchemy.url` in `alembic.ini`, unset by default; the app's default,
`sqlite:///qvault.db`. A relative SQLite path means the file in `instance/`, the same file the
development server opens. Run commands from the repository root with the project's interpreter:
`python -m alembic ...`.

## Existing databases are stamped, not upgraded

> **Not yet.** Nothing here is to be run against the live database, or any database the working
> project uses, until the rework is merged and the owner decides to switch (plan §0 and Phase R10).
> Until then nothing on the live system changes: the image it runs has no migrations and does not
> know this table exists.

The live database, the laptop's demo database and every backup were built by `create_all`, so they
already have every table in `0001_baseline`. Upgrading one from nothing would try to create tables
that exist and fail. Instead it is **stamped**: Alembic records that the database is at the
baseline, in a new one-row table, `alembic_version`. No other table is touched.

1. Back up the database first (plan R10, switch procedure).
2. Stamp it and check it. Point `DATABASE_URL` at the database, as for the other operator scripts:

   ```powershell
   $env:DATABASE_URL = "postgresql+psycopg://..."   # the database to stamp
   python -m alembic stamp 0001_baseline
   python -m alembic check
   Remove-Item Env:DATABASE_URL
   ```

   `-x url=...` does the same without the environment variable:
   `python -m alembic -x url=postgresql+psycopg://... stamp 0001_baseline`.
   With neither, the command acts on the laptop's `instance/qvault.db`.

   `check` must print `No new upgrade operations detected.` Anything else means the database is
   not the baseline schema: undo the stamp with `python -m alembic stamp base` (it removes the
   version row and nothing else) and find out why before going on.
3. Then `python -m alembic upgrade head`, which applies only the revisions after the baseline.

**The live Azure database** accepts connections only from Azure services, so its commands run
inside Azure, as a one-off run of the rework image with `DATABASE_URL` already set. The
`qvault-seed` job is that already ([OWNER-ACTIONS §2.9](../OWNER-ACTIONS.md)); its command becomes
`alembic stamp 0001_baseline`, then `alembic check`, then `alembic upgrade head`. The image's
working directory holds `alembic.ini`, so no path is needed.

**Order matters at the switch.** Stamp and upgrade *before* the first start of an image whose
models are ahead of the baseline. That image's startup `create_all` would otherwise create the new
tables itself, the revision that creates them would then fail, and the new columns on old tables
would be missing either way.

Checked on 2026-10-04 against a copy of the laptop's `instance/qvault.db`: all 26 tables, no
differences from the models, and the three partial unique indexes with their exact predicates. It
will stamp cleanly. The live database cannot be checked from here; `check` after the stamp is
that check.

## Changing the schema

1. Change the model.
2. Generate a revision against a database at the head (a scratch one is fine):

   ```powershell
   python -m alembic -x url=sqlite:///scratch.db upgrade head
   python -m alembic -x url=sqlite:///scratch.db revision --autogenerate --rev-id 0002_workspaces -m "Workspaces"
   ```

   Revision ids are `NNNN_slug`, at most 32 characters (the width of `alembic_version`), and the
   file is named after the id. `ruff` and `black` run on the new file as it is written.
3. Read it. Autogenerate is a draft. It does **not** notice a changed partial-index predicate (the
   `WHERE` of `uq_treasury_linked_vault` and its two siblings), it writes a rename as a drop and an
   add, and it never moves data: a new `NOT NULL` column on a table with rows needs a default or a
   data step written by hand. Application column types are written as their storage type
   (`AwareDateTime` as `DateTime(timezone=True)`), so revisions never import `qvault`.
4. Run `python -m pytest tests/test_migrations.py`. It applies every revision to an empty
   database and compares the result with `create_all`, on SQLite and as PostgreSQL SQL.

Revisions are written in batch mode, so one revision runs on SQLite (development, tests), where most
`ALTER`s need a table rebuild, and on PostgreSQL (production), where a batch block is ordinary
`ALTER` statements. For SQLite, `env.py` turns foreign-key enforcement off during a migration, since
a rebuild drops a table other rows point at.
