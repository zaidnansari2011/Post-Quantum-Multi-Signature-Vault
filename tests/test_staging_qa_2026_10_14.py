"""The staging QA pass of 14 October 2026 (rework-handoff/qa-2026-10-14/QA-REPORT.md).

One test (or a few) per finding, each written to fail on the code the pass found the defect in.
"""

from __future__ import annotations

import csv
import io

from qvault import create_app
from qvault.services import auth_service, vault_service

PASSWORD = "password-123"


# --- F1: the audit CSV streams every row, not just its header -----------------------------------


def test_the_audit_csv_streams_every_row_after_the_request_has_ended():
    """``/ledger/export.csv`` sent its header and then dropped the connection: the rows were
    read in a generator that ran after the request (and its app context, holding the signed-in
    user and the database session) had been torn down. The suite's shared app context hid it, so
    this test makes the request the way a server does, with no context pushed around it, and
    reads the WHOLE body."""
    application = create_app("testing")
    with application.app_context():
        ada = auth_service.register_user("csv-ada@e.com", "Ada Lovelace", PASSWORD)
        vault = vault_service.create_vault(ada, "Streamed", "", 1)
        brij = auth_service.register_user("csv-brij@e.com", "Brij Patel", PASSWORD)
        vault_service.add_member(vault, brij.email, "signer", actor_id=ada.id)
        vault_service.set_threshold(vault, 2, actor_id=ada.id)
        email = ada.email

    client = application.test_client()
    client.post("/login", data={"email": email, "password": PASSWORD})
    response = client.get("/ledger/export.csv")
    assert response.status_code == 200
    body = response.get_data(as_text=True)  # every chunk, to the end of the stream
    rows = list(csv.reader(io.StringIO(body)))
    assert rows[0][:3] == ["seq", "timestamp", "event"]
    events = [row[2] for row in rows[1:]]
    assert "vault_created" in events
    assert "member_added" in events
    assert "vault_threshold_changed" in events
    assert len(rows) >= 5
