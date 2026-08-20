"""The independent witness — what it co-signs, and everything it refuses.

ADR-0005 recorded truncation as an accepted, undetectable limitation, on the reasoning that a
self-contained anchor cannot notice its own store losing rows. These tests are the argument that
the limitation is now retired: the witness holds a high-water mark outside the database, and every
way of moving backwards past it is enumerated here.

The witness is exercised through its real HTTP surface (Flask's test client, so no sockets) rather
than by calling into its internals, because the interface is the security boundary. A test that
reached past the routes would be testing a witness nobody deploys.
"""

from __future__ import annotations

import json
from base64 import b64decode, b64encode

import pytest

from qvault.crypto import build_registry, sha256_hex
from qvault.transparency import (
    checkpoint_bytes,
    consistency_proof,
    leaf_hash,
    merkle_root,
    witness_bytes,
)
from qvault.transparency.statement import checkpoint_statement
from witness.app import create_witness_app

ORIGIN = "qvault.test/ledger"


@pytest.fixture(scope="module")
def registry_mod():
    return build_registry()


@pytest.fixture()
def log_key(registry_mod):
    """A stand-in for the log's SYSTEM key. ML-DSA, as the real one is."""
    provider = registry_mod.signature("ML-DSA-65")
    return provider, provider.keygen()


@pytest.fixture()
def witness(tmp_path, registry_mod):
    """A witness on a fresh store and a fresh key.

    ML-DSA-65 rather than the SLH-DSA default purely for test speed: SLH-DSA signing is ~39 ms,
    and these tests co-sign dozens of times. ``test_the_default_witness_algorithm_differs`` covers
    the real default separately.
    """
    app = create_witness_app(
        state_path=tmp_path / "w.db",
        key_path=tmp_path / "w.json",
        name="witness-under-test",
        alg_id="ML-DSA-65",
    )
    app.testing = True
    return app


@pytest.fixture()
def client(witness):
    return witness.test_client()


# --------------------------------------------------------------------------------------------
# Helpers: build real trees and real checkpoints, so nothing here is signing fabricated hashes.
# --------------------------------------------------------------------------------------------


def leaves(n: int) -> list[bytes]:
    return [leaf_hash(f"entry-{i}".encode()) for i in range(n)]


def statement_for(n: int, *, root: bytes | None = None, origin: str = ORIGIN) -> dict:
    return checkpoint_statement(
        origin=origin,
        tree_size=n,
        root_hash=(root or merkle_root(leaves(n))).hex(),
        head_seq=n - 1,
        head_hash=sha256_hex(f"head-{n}".encode()),
        timestamp=f"2026-08-11T10:{n:02d}:00+00:00",
    )


def offer(client, log_key, statement, *, proof=None, public_key=None, signature=None):
    provider, keypair = log_key
    body = {
        "checkpoint": statement,
        "log_alg_id": "ML-DSA-65",
        "log_public_key_b64": b64encode(public_key or keypair.public_key).decode(),
        "log_signature_b64": b64encode(
            signature
            if signature is not None
            else provider.sign(keypair.secret_key, checkpoint_bytes(statement))
        ).decode(),
        "consistency_proof": [h.hex() for h in (proof or [])],
    }
    return client.post("/cosign", json=body)


def grow(client, log_key, old: int, new: int):
    """Offer a checkpoint at ``new`` with a genuine consistency proof from ``old``."""
    return offer(client, log_key, statement_for(new), proof=consistency_proof(leaves(new), old))


# --------------------------------------------------------------------------------------------
# The happy path
# --------------------------------------------------------------------------------------------


def test_the_first_checkpoint_is_co_signed(client, log_key, registry_mod):
    resp = offer(client, log_key, statement_for(8))
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["tree_size"] == 8 and body["reissued"] is False

    # The signature must verify under the witness's own published key, over the witness's own
    # domain-separated bytes — not the log's.
    provider = registry_mod.signature(body["alg_id"])
    assert provider.verify(
        b64decode(body["public_key_b64"]),
        witness_bytes(witness=body["witness"], statement=statement_for(8)),
        b64decode(body["signature_b64"]),
    )


def test_a_growing_log_keeps_being_co_signed(client, log_key):
    assert offer(client, log_key, statement_for(4)).status_code == 200
    for old, new in ((4, 5), (5, 11), (11, 12), (12, 32), (32, 33)):
        assert grow(client, log_key, old, new).status_code == 200, f"{old} -> {new}"
    assert client.get(f"/state?origin={ORIGIN}").get_json()["tree_size"] == 33


def test_state_reports_the_high_water_mark(client, log_key):
    assert client.get(f"/state?origin={ORIGIN}").get_json()["tree_size"] is None
    offer(client, log_key, statement_for(6))
    state = client.get(f"/state?origin={ORIGIN}").get_json()
    assert state["tree_size"] == 6
    assert state["root_hash"] == merkle_root(leaves(6)).hex()
    assert state["log_key_fingerprint"] is not None


def test_re_offering_the_same_checkpoint_returns_the_same_signature(client, log_key):
    first = offer(client, log_key, statement_for(7)).get_json()
    again = offer(client, log_key, statement_for(7)).get_json()
    assert again["reissued"] is True
    assert again["signature_b64"] == first["signature_b64"]


def test_the_same_tree_restated_is_signed_afresh(client, log_key, registry_mod):
    """Same size and same root, different timestamp — a new statement, not a fork.

    This was a real bug: matching on ``(tree_size, root_hash)`` alone reissued a signature made
    over the *earlier* statement, so what came back verified against nothing the caller held. The
    co-signature was then dropped at the far end and exports shipped unwitnessed, with the witness
    answering 200 to every request.
    """
    original = statement_for(7)
    restated = {**original, "timestamp": "2026-08-11T23:59:00+00:00"}

    first = offer(client, log_key, original).get_json()
    second = offer(client, log_key, restated).get_json()

    assert second["reissued"] is False
    assert second["signature_b64"] != first["signature_b64"]

    provider = registry_mod.signature(second["alg_id"])
    assert provider.verify(
        b64decode(second["public_key_b64"]),
        witness_bytes(witness=second["witness"], statement=restated),
        b64decode(second["signature_b64"]),
    ), "the co-signature must cover the statement that was actually offered"


# --------------------------------------------------------------------------------------------
# Truncation — the ADR-0005 limitation this whole component exists to close
# --------------------------------------------------------------------------------------------


def test_a_truncated_log_is_refused_and_recorded(client, log_key, witness):
    """Delete entries, re-anchor, present a shorter but perfectly consistent log. Refused."""
    assert offer(client, log_key, statement_for(20)).status_code == 200

    resp = offer(client, log_key, statement_for(12))
    assert resp.status_code == 409
    assert "shrank" in resp.get_json()["error"] or "20" in resp.get_json()["error"]

    store = witness.config["WITNESS_STORE"]
    violations = store.violations(ORIGIN)
    assert [v["kind"] for v in violations] == ["shrank"]
    # The offered checkpoint is kept, so the attempt itself is evidence rather than just a refusal.
    assert json.loads(violations[0]["offered_json"])["tree_size"] == 12
    # And the high-water mark is unmoved.
    assert store.latest(ORIGIN)["tree_size"] == 20


def test_truncation_cannot_be_laundered_by_growing_again(client, log_key):
    """The realistic version: truncate to 12, then append until you are back past 20.

    A log at size 24 whose entries 12-23 are new does not contain the tree of 20 that was already
    co-signed, so no consistency proof exists and the witness stays refused. This is the case a
    naive "is the new size bigger?" check would wave through.
    """
    assert offer(client, log_key, statement_for(20)).status_code == 200
    assert offer(client, log_key, statement_for(12)).status_code == 409

    forged = [*leaves(12), *[leaf_hash(f"rewritten-{i}".encode()) for i in range(12, 24)]]
    resp = offer(
        client,
        log_key,
        statement_for(24, root=merkle_root(forged)),
        proof=consistency_proof(forged, 20),
    )
    assert resp.status_code == 409
    assert "provably contain" in resp.get_json()["error"]


# --------------------------------------------------------------------------------------------
# Forks and rewrites
# --------------------------------------------------------------------------------------------


def test_two_different_roots_at_the_same_size_is_a_fork(client, log_key, witness):
    """The split-view attack: one history shown to a signer, another to an auditor."""
    assert offer(client, log_key, statement_for(9)).status_code == 200

    other = leaves(9)
    other[3] = leaf_hash(b"a different entry 3")
    resp = offer(client, log_key, statement_for(9, root=merkle_root(other)))

    assert resp.status_code == 409
    assert "fork" in resp.get_json()["error"]
    assert [v["kind"] for v in witness.config["WITNESS_STORE"].violations(ORIGIN)] == ["fork"]


def test_a_consistent_forward_rewrite_is_refused(client, log_key, witness):
    """The attack ADR-0005 *does* catch on-box, caught again here by a party with no master key.

    Editing entry 5 and recomputing every hash forward leaves the chain internally valid. The
    witness never looks at the chain; it asks whether the tree it co-signed at size 10 is still a
    prefix, and it is not.
    """
    assert offer(client, log_key, statement_for(10)).status_code == 200

    rewritten = leaves(30)
    rewritten[5] = leaf_hash(b"entry-5, as the operator wishes it had been")
    resp = offer(
        client,
        log_key,
        statement_for(30, root=merkle_root(rewritten)),
        proof=consistency_proof(rewritten, 10),
    )
    assert resp.status_code == 409
    assert [v["kind"] for v in witness.config["WITNESS_STORE"].violations(ORIGIN)] == [
        "inconsistent"
    ]


def test_a_missing_or_bogus_consistency_proof_is_refused(client, log_key):
    assert offer(client, log_key, statement_for(10)).status_code == 200
    assert offer(client, log_key, statement_for(30)).status_code == 409  # no proof at all
    assert (
        offer(client, log_key, statement_for(30), proof=[leaf_hash(b"nonsense")]).status_code == 409
    )


# --------------------------------------------------------------------------------------------
# Identity: who is allowed to move this log's high-water mark
# --------------------------------------------------------------------------------------------


def test_a_different_log_key_for_a_known_origin_is_refused(client, log_key, registry_mod, witness):
    """Pinned on first use. A second keypair claiming the same origin is not that origin."""
    assert offer(client, log_key, statement_for(5)).status_code == 200

    impostor_provider = registry_mod.signature("ML-DSA-65")
    impostor = impostor_provider.keygen()
    statement = statement_for(6)
    resp = offer(
        client,
        log_key,
        statement,
        proof=consistency_proof(leaves(6), 5),
        public_key=impostor.public_key,
        signature=impostor_provider.sign(impostor.secret_key, checkpoint_bytes(statement)),
    )
    assert resp.status_code == 409
    assert "pinned" in resp.get_json()["error"]
    assert [v["kind"] for v in witness.config["WITNESS_STORE"].violations(ORIGIN)] == ["key_changed"]


def test_an_unsigned_checkpoint_is_refused(client, log_key, witness):
    """Without this, anyone could park an enormous tree_size and lock the real log out for good."""
    resp = offer(client, log_key, statement_for(5), signature=b"\x00" * 64)
    assert resp.status_code == 409
    assert [v["kind"] for v in witness.config["WITNESS_STORE"].violations(ORIGIN)] == [
        "bad_signature"
    ]
    assert witness.config["WITNESS_STORE"].latest(ORIGIN) is None


def test_separate_origins_do_not_interfere(client, log_key):
    """One witness, many logs. A short log B must not be judged against a long log A."""
    assert offer(client, log_key, statement_for(30)).status_code == 200
    other = statement_for(3, origin="qvault.other/ledger")
    assert offer(client, log_key, other).status_code == 200


# --------------------------------------------------------------------------------------------
# The statement itself
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mutate, expect",
    [
        (lambda s: s.pop("timestamp"), "missing"),
        (lambda s: s.update(extra="surprise"), "unexpected"),
        (lambda s: s.update(root_hash="abc"), "64 hex"),
        (lambda s: s.update(root_hash="z" * 64), "not hex"),
        (lambda s: s.update(tree_size="8"), "must be an integer"),
        (lambda s: s.update(head_seq=99), "does not match"),
        (lambda s: s.update(origin=""), "non-empty"),
    ],
)
def test_a_malformed_statement_is_never_co_signed(client, log_key, mutate, expect):
    """The witness signs a serialisation of what it is given, so it must only accept statements it
    fully accounts for — an unrecognised field would otherwise be silently countersigned."""
    statement = statement_for(8)
    mutate(statement)
    resp = offer(client, log_key, statement)
    assert resp.status_code == 400
    assert expect in resp.get_json()["error"]


def test_the_witness_signature_does_not_verify_as_a_log_signature(client, log_key, registry_mod):
    """Domain separation across the trust boundary.

    If a witness co-signature verified as a checkpoint signature, standing up a witness would mean
    handing out the ability to mint checkpoints to anyone later mistaken for the log.
    """
    body = offer(client, log_key, statement_for(8)).get_json()
    provider = registry_mod.signature(body["alg_id"])
    assert not provider.verify(
        b64decode(body["public_key_b64"]),
        checkpoint_bytes(statement_for(8)),  # the LOG's bytes
        b64decode(body["signature_b64"]),
    )


# --------------------------------------------------------------------------------------------
# Identity and independence
# --------------------------------------------------------------------------------------------


def test_the_default_witness_algorithm_differs_from_the_logs(tmp_path):
    """The log signs checkpoints with ML-DSA-65; the witness must not default to the same thing.

    This was going to be SLH-DSA, for genuine assumption diversity, and ``witness/identity.py``
    records why it is not: the backend's SLH-DSA is PQClean's SPHINCS+ round-3, which is not
    byte-compatible with the FIPS 205 SLH-DSA the browser verifier implements, so a hash-based
    witness would produce co-signatures no recipient could check offline. It remains selectable
    with ``--alg`` for anyone who prefers that trade.
    """
    from witness.identity import DEFAULT_WITNESS_ALG, load_or_create

    identity = load_or_create(
        tmp_path / "k.json", name="w", registry=build_registry(), alg_id=None
    )
    assert identity.alg_id == DEFAULT_WITNESS_ALG == "ML-DSA-87"
    assert identity.alg_id != "ML-DSA-65", "the witness must not share the log's parameters"


def test_a_hash_based_witness_is_still_available(tmp_path):
    """The diversity option is a flag away, and choosing it must not be broken by the default."""
    from witness.identity import load_or_create

    identity = load_or_create(
        tmp_path / "k.json", name="w", registry=build_registry(), alg_id="SLH-DSA-SHAKE-256f"
    )
    assert identity.alg_id == "SLH-DSA-SHAKE-256f"


def test_the_key_is_stable_across_restarts(tmp_path, registry_mod):
    from witness.identity import load_or_create

    first = load_or_create(tmp_path / "k.json", name="w", registry=registry_mod, alg_id="ML-DSA-65")
    second = load_or_create(tmp_path / "k.json", name="w", registry=registry_mod, alg_id="ML-DSA-65")
    assert first.public_key == second.public_key
    assert first.fingerprint() == second.fingerprint()


def test_changing_the_algorithm_on_an_existing_key_file_is_refused(tmp_path, registry_mod):
    """A silently-regenerated key would invalidate every co-signature already issued."""
    from witness.identity import load_or_create

    load_or_create(tmp_path / "k.json", name="w", registry=registry_mod, alg_id="ML-DSA-65")
    with pytest.raises(SystemExit, match="new identity"):
        load_or_create(tmp_path / "k.json", name="w", registry=registry_mod, alg_id="ML-DSA-87")


def test_the_witness_stores_nothing_in_the_vault_database(witness):
    """The independence claim, asserted rather than assumed.

    If this ever fails, the witness has been wired into the application's session and its memory
    of the log lives in the database the log's operator controls — at which point co-signing is
    theatre.
    """
    import qvault.extensions

    store = witness.config["WITNESS_STORE"]
    assert store.path.endswith("w.db")
    assert "qvault" not in store.path
    assert not hasattr(witness, "extensions") or "sqlalchemy" not in witness.extensions
    assert qvault.extensions.db not in witness.extensions.values()


def test_the_status_page_renders(client, log_key):
    offer(client, log_key, statement_for(5))
    offer(client, log_key, statement_for(2))  # a refusal, so both tables have content
    page = client.get("/").get_data(as_text=True)
    assert "witness-under-test" in page
    assert ORIGIN in page
    assert "shrank" in page
