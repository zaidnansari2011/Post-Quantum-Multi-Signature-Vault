"""Flask blueprints — thin HTTP layer.

Blueprints parse the request, call exactly one service, and render — no crypto, no SQL.
``core`` exists now; auth, vaults, proposals, ledger, keys, admin, and benchmark follow in
later phases (specification §6).
"""
