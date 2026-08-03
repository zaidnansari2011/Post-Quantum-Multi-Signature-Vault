"""Phase 3 — route-level authorization and the end-to-end encrypted-file download."""

from __future__ import annotations

from qvault.services import auth_service, proposal_service, vault_service

SECRET = b"secret-bytes-1234567890"


def test_vaults_requires_login(client):
    resp = client.get("/vaults/")
    assert resp.status_code == 302  # redirected to the login page


def test_non_member_cannot_view_vault(client):
    owner = auth_service.register_user("o@e.com", "O", "password-123")
    auth_service.register_user("stranger@e.com", "S", "password-123")
    vault = vault_service.create_vault(owner, "Private", "", 1)
    vid = vault.id

    client.post("/login", data={"email": "stranger@e.com", "password": "password-123"})
    # 404 (not 403) so a non-member cannot tell an existing vault from a missing one.
    assert client.get(f"/vaults/{vid}").status_code == 404


def test_member_downloads_decrypted_file(client):
    owner = auth_service.register_user("own@e.com", "Own", "password-123")
    auth_service.register_user("bob@e.com", "Bob", "password-123")
    vault = vault_service.create_vault(owner, "T", "", 1)
    vault_service.add_member(vault, "bob@e.com", "signer", actor_id=owner.id)
    proposal = proposal_service.create_proposal(
        vault, owner, "Release", "do it", file_bytes=SECRET, filename="s.txt"
    )
    vid, pid = vault.id, proposal.proposal_uuid

    # Bob (a different member) logs in and downloads — the vault key decrypts server-side.
    client.post("/login", data={"email": "bob@e.com", "password": "password-123"})
    resp = client.get(f"/vaults/{vid}/proposals/{pid}/file")

    assert resp.status_code == 200
    assert resp.data == SECRET


def test_non_member_cannot_download_file(client):
    owner = auth_service.register_user("own2@e.com", "Own", "password-123")
    auth_service.register_user("intruder@e.com", "I", "password-123")
    vault = vault_service.create_vault(owner, "T", "", 1)
    proposal = proposal_service.create_proposal(
        vault, owner, "Release", "do it", file_bytes=SECRET, filename="s.txt"
    )
    vid, pid = vault.id, proposal.proposal_uuid

    client.post("/login", data={"email": "intruder@e.com", "password": "password-123"})
    assert client.get(f"/vaults/{vid}/proposals/{pid}/file").status_code == 404
