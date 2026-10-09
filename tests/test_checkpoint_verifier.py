"""The offline check of the log's public signed head (``python -m qvault.verify --checkpoint``).

From the R6 review (2026-10-09): the text output crashed on every witnessed head, which is the
normal production case; a head renamed to look like a decision exited 0; a document of the wrong
shape raised instead of failing; an empty pin matched every key; a "witnessed" head with no
co-signature passed; and the reported origin came from an unsigned field. Each is pinned here.
"""

from __future__ import annotations

import copy
import json
from base64 import b64encode

import pytest

from qvault.crypto import sha256_hex
from qvault.services import checkpoint_service
from qvault.transparency import checkpoint_bytes, witness_bytes
from qvault.verify.__main__ import main
from qvault.verify.checkpoint import verify_checkpoint_document


def _head(client) -> dict:
    return client.get("/transparency/checkpoint.json").get_json()


@pytest.fixture()
def witnessed_doc(client, witnessed):
    checkpoint_service.sync_witness()
    doc = _head(client)
    assert doc["witnessed"] and doc["witnessed"]["witnesses"], "the fixture is witnessed"
    return doc


def _save(tmp_path, doc, name="checkpoint.json"):
    path = tmp_path / name
    path.write_text(json.dumps(doc), encoding="utf-8")
    return str(path)


def _check(registry, doc, **kwargs):
    return verify_checkpoint_document(doc, registry=registry, **kwargs)


def _failed(report) -> set[str]:
    return {c.key for c in report.failures}


# ------------------------------------------------------------------------------ the command line


def test_the_command_line_prints_a_witnessed_head_with_the_witness_named(
    witnessed_doc, tmp_path, capsys
):
    path = _save(tmp_path, witnessed_doc)
    [w] = witnessed_doc["witnessed"]["witnesses"]
    assert main([path, "--checkpoint", "--no-colour"]) == 0
    out = capsys.readouterr().out
    assert "SIGNED HEAD VERIFIED" in out
    assert f"witness key  {w['key_fingerprint']}  (witness-1)" in out


def test_the_command_line_json_for_a_witnessed_head_names_each_witness(
    witnessed_doc, tmp_path, capsys
):
    path = _save(tmp_path, witnessed_doc)
    [w] = witnessed_doc["witnessed"]["witnesses"]
    assert main([path, "--checkpoint", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True
    assert report["fingerprints"]["witnesses"] == [
        {"fingerprint": w["key_fingerprint"], "name": "witness-1"}
    ]


def test_a_log_head_given_where_a_decision_is_expected_is_refused(client, tmp_path, capsys):
    doc = _head(client)
    fp = doc["latest"]["checkpoint_signature"]["key_fingerprint"]
    path = _save(tmp_path, doc, "decision-wire-9000.json")
    assert main([path, "--expect-log", fp, "--no-colour"]) == 2
    err = capsys.readouterr().err
    assert "not a decision" in err and "--checkpoint" in err
    # Asked for by name, the same file is checked as what it is.
    assert main([path, "--checkpoint", "--expect-log", fp, "--no-colour"]) == 0


def test_a_decision_given_where_a_log_head_is_expected_is_refused(tmp_path, capsys):
    path = _save(tmp_path, {"format": "qvault.decision/1", "decision": {}}, "checkpoint.json")
    assert main([path, "--checkpoint"]) == 2
    assert "this is a decision" in capsys.readouterr().err


SHAPES = {
    "a list": [1, 2],
    "a string": "x",
    "null": None,
    "a number": 3,
    "latest is a list": {"format": "qvault.checkpoint/1", "latest": [1]},
    "latest is a string": {"format": "qvault.checkpoint/1", "latest": "x"},
    "witnessed is a number": {"format": "qvault.checkpoint/1", "witnessed": 7},
}


def _mutations(base: dict) -> dict:
    def put(path, value):
        doc = copy.deepcopy(base)
        target = doc
        for step in path[:-1]:
            target = target[step]
        target[path[-1]] = value
        return doc

    return {
        "witness is a string": put(("latest", "witnesses"), ["abc"]),
        "witnesses is a string": put(("latest", "witnesses"), "abc"),
        "witness alg is a list": put(
            ("latest", "witnesses"),
            [{"alg_id": ["x"], "public_key_b64": "AA==", "signature_b64": "AA==", "witness": 1}],
        ),
        "checkpoint is a list": put(("latest", "checkpoint"), [1]),
        "signature is a string": put(("latest", "checkpoint_signature"), "x"),
        "alg is a dict": put(("latest", "checkpoint_signature", "alg_id"), {"a": 1}),
        "tree size is a string": put(("latest", "checkpoint", "tree_size"), "12"),
    }


def test_a_document_of_the_wrong_shape_fails_cleanly_and_never_raises(client, registry):
    cases = {**SHAPES, **_mutations(_head(client))}
    for name, doc in cases.items():
        report = _check(registry, doc)  # must not raise
        assert not report.ok, name
        assert report.failures, name
        json.dumps(report.as_dict())  # and the verdict is printable


def test_the_command_line_never_prints_a_traceback_for_a_bad_file(client, tmp_path, capsys):
    cases = {**SHAPES, **_mutations(_head(client))}
    for i, (name, doc) in enumerate(cases.items()):
        path = _save(tmp_path, doc, f"shape-{i}.json")
        for args in ([path, "--checkpoint", "--no-colour"], [path, "--no-colour"]):
            assert main(args) in (1, 2), (name, args)
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    assert main([str(tmp_path / "broken.json"), "--checkpoint"]) == 2
    (tmp_path / "deep.json").write_text("[" * 100_000 + "]" * 100_000, encoding="utf-8")
    assert main([str(tmp_path / "deep.json"), "--checkpoint"]) == 2
    assert "Traceback" not in capsys.readouterr().err


# ------------------------------------------------------------------------------ pins


def test_an_empty_or_short_pin_is_a_usage_error_not_a_match(client, tmp_path, capsys):
    doc = _head(client)
    fp = doc["latest"]["checkpoint_signature"]["key_fingerprint"]
    path = _save(tmp_path, doc)
    for pin in ("", fp[:8], fp[:15], "not-hex-at-all-xx", fp + "0" * 49):
        assert main([path, "--checkpoint", "--expect-log", pin]) == 2, pin
        assert main([path, "--checkpoint", "--expect-witness", pin]) == 2, pin
    assert "16 to 64 hex characters" in capsys.readouterr().err


def test_an_empty_pin_fails_in_the_library_too(client, registry):
    report = _check(registry, _head(client), expect_log="")
    assert "pinned_log" in _failed(report)
    report = _check(registry, _head(client), expect_log="abcd1234")
    assert "pinned_log" in _failed(report)


def test_a_pin_is_compared_on_every_digit_given(client, registry):
    doc = _head(client)
    key = doc["latest"]["checkpoint_signature"]["public_key_b64"]
    from base64 import b64decode

    full = sha256_hex(b64decode(key))
    assert _check(registry, doc, expect_log=full).ok
    assert _check(registry, doc, expect_log=full[:16].upper()).ok
    assert _check(registry, doc, expect_log=full[:40]).ok
    wrong_tail = full[:63] + ("0" if full[63] != "0" else "1")
    assert "pinned_log" in _failed(_check(registry, doc, expect_log=wrong_tail))


# ------------------------------------------------------------------------------ the head's claims


def test_a_witnessed_head_with_no_co_signature_fails(client, registry):
    doc = _head(client)
    doc["witnessed"] = copy.deepcopy(doc["latest"])
    doc["witnessed"]["witnesses"] = []
    doc["witness_configured"] = True
    report = _check(registry, doc)
    assert not report.ok and "witnessed_witness" in _failed(report)


def _resign(registry, head: dict, alg: str = "ML-DSA-65"):
    provider = registry.signature(alg)
    pair = provider.keygen()
    head["checkpoint_signature"].update(
        alg_id=alg,
        public_key_b64=b64encode(pair.public_key).decode(),
        signature_b64=b64encode(
            provider.sign(pair.secret_key, checkpoint_bytes(head["checkpoint"]))
        ).decode(),
        key_fingerprint=sha256_hex(pair.public_key)[:16],
    )
    return pair


def test_the_origin_reported_is_the_signed_one_and_a_different_claim_fails(client, registry):
    doc = _head(client)
    signed = doc["latest"]["checkpoint"]["origin"]
    assert _check(registry, doc).facts["origin"] == signed
    doc["origin"] = "bank.example/ledger"
    report = _check(registry, doc)
    assert not report.ok and "origin" in _failed(report)
    assert report.facts["origin"] == signed


def test_two_heads_that_name_different_logs_fail(witnessed_doc, registry):
    doc = copy.deepcopy(witnessed_doc)
    doc["latest"]["checkpoint"]["origin"] = "other.example/ledger"
    # Re-signed by the same key would need the log's secret; a fresh key makes it self-consistent,
    # so both one_log and one_origin are the checks that catch it.
    _resign(registry, doc["latest"])
    report = _check(registry, doc)
    assert not report.ok
    assert {"one_origin", "one_log"} <= _failed(report)


def test_a_classical_log_key_fails_unless_allowed(client, registry):
    doc = _head(client)
    _resign(registry, doc["latest"], "ECDSA-P256")
    report = _check(registry, doc)
    assert not report.ok and "post_quantum" in _failed(report)
    allowed = _check(registry, doc, allow_classical=True)
    assert allowed.ok, allowed.as_dict()


def test_a_classical_witness_key_fails_unless_allowed(witnessed_doc, registry):
    doc = copy.deepcopy(witnessed_doc)
    head = doc["witnessed"]
    provider = registry.signature("RSA-2048-PSS")
    pair = provider.keygen()
    head["witnesses"] = [
        {
            "witness": "cheap-witness",
            "alg_id": "RSA-2048-PSS",
            "public_key_b64": b64encode(pair.public_key).decode(),
            "signature_b64": b64encode(
                provider.sign(
                    pair.secret_key,
                    witness_bytes(witness="cheap-witness", statement=head["checkpoint"]),
                )
            ).decode(),
        }
    ]
    report = _check(registry, doc)
    assert "post_quantum" in _failed(report)
    assert _check(registry, doc, allow_classical=True).ok


def test_the_command_line_accepts_allow_classical(client, registry, tmp_path):
    doc = _head(client)
    _resign(registry, doc["latest"], "ECDSA-P256")
    path = _save(tmp_path, doc)
    assert main([path, "--checkpoint", "--no-colour"]) == 1
    assert main([path, "--checkpoint", "--allow-classical", "--no-colour"]) == 0
