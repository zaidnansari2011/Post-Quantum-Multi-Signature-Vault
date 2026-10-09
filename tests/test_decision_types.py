"""Decision types (rework plan S13): General, Payment, Production access and Contract.

A typed decision's text is written from its fields, deterministically, as a payment's is from its
payment (plan D24), and the signed format does not change (S9): what is signed is still
``action_text``. The fields are stored beside it, unsigned, and are only ever a way to read the
signed text:

* the generator gives every vector in ``tests/vectors/decision_types.json`` its frozen result, the
  same file the phone's twin is held to (``test_mobile_decision_types.py``), and the text reads
  back into exactly the fields that wrote it, so no two sets of fields write the same text;
* what a person types is made canonical first, forgivingly only where the meaning is certain;
* raising one signs the text its fields write, refuses text of its own and fields that write none,
  and stores the fields beside it; it then passes like any other decision;
* stored fields that do not write the signed text are never shown: the decision reads as General
  on its page, in lists and when raised again;
* New decision offers every type, marks a refused field in words, and raising again keeps the
  type and its fields; the device API raises one, and its detail carries the type and fields;
* the API's additions for the phone (A2, A3, A4, A17): a payment row's amount and the treasury's
  seat, the signer set with names, and when a decision was decided.
"""

from __future__ import annotations

import io
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from test_decision_endings import _team
from test_device_api import _enrol_over_http
from test_payment_decisions import _payment, _vault
from test_vote_eligibility import PASSWORD, payments_on  # noqa: F401 (a fixture)

from qvault.extensions import db
from qvault.models import DecisionFields, Key, Proposal, TreasurySigner
from qvault.services import (
    approval_service,
    auth_service,
    decision_types,
    proposal_service,
    vault_service,
)
from qvault.services.decision_types import FieldsError, check_fields, decision_text, normalise
from qvault.services.proposal_service import FieldsRefused, ProposalError, TypedRequest
from qvault.services.signing import signing_bytes_for

VECTORS = json.loads(
    (Path(__file__).parent / "vectors" / "decision_types.json").read_text(encoding="utf-8")
)
CASES = {case["name"]: case for case in VECTORS["cases"]}


def _args(case):
    return (case["type"], case["fields"]) + ((case["version"],) if "version" in case else ())


def _until(days: float = 30) -> str:
    """An access end ``days`` from now, on the real clock: every test here raises on it too."""
    return (datetime.now(UTC) + timedelta(days=days)).strftime("%Y-%m-%d %H:%M")


def _access(**changes):
    fields = {
        "person": "Elif Kaya",
        "system": "prod-db",
        "level": "read",
        "until": _until(),
        "reason": "Investigate the October billing incident.",
        **changes,
    }
    return {key: value for key, value in fields.items() if value is not None}


CONTRACT = {
    "counterparty": "Calderwood Mutual",
    "subject": "Commercial liability cover for 2027.",
    "amount": "48200.50",
    "currency": "GBP",
    "starts": "2027-01-01",
    "ends": "2027-12-31",
}


def _raise(vault, user, decision_type="access", fields=None, **kwargs):
    fields = (
        fields if fields is not None else (_access() if decision_type == "access" else CONTRACT)
    )
    return proposal_service.create_proposal(
        vault, user, "Typed", "", typed=TypedRequest(decision_type, fields), **kwargs
    )


# --- the generator and the vectors ---------------------------------------------------------------


def test_the_vectors_are_for_this_template_version():
    assert VECTORS["template_version"] == decision_types.TEMPLATE_VERSION == 1
    assert len(CASES) == len(VECTORS["cases"])  # names are unique


@pytest.mark.parametrize("name", list(CASES))
def test_the_server_gives_every_vector_its_frozen_result(name):
    case = CASES[name]
    assert decision_text(*_args(case)) == case.get("text")
    if case["type"] != "payment":
        problem = check_fields(*_args(case))
        expected = case.get("problem")
        assert (None if problem is None else {"field": problem.field, "code": problem.code}) == (
            expected
        )


LABEL_TO_KEY = {
    kind: {spec.label: spec.key for spec in specs} for kind, specs in decision_types.SPECS.items()
}


def _read_back(kind: str, text: str) -> dict:
    """The fields a typed text names, read off its ``Label: value`` lines."""
    fields = {}
    for line in text.split("\n")[1:]:
        label, _, value = line.partition(": ")
        key = LABEL_TO_KEY[kind][label]
        if key == "level":
            value = next(k for k, v in decision_types.ACCESS_LEVELS.items() if v[0] == value)
        elif key == "until":
            value = value.removesuffix(" UTC")
        elif key == "amount":
            currency, _, grouped = value.partition(" ")
            fields["currency"] = currency
            value = grouped.replace(",", "")
        fields[key] = value
    return fields


@pytest.mark.parametrize(
    "name",
    [n for n, c in CASES.items() if c["type"] in ("access", "contract") and c.get("text")],
)
def test_a_typed_text_reads_back_into_exactly_the_fields_that_wrote_it(name):
    """No two sets of fields write the same text: a value cannot hold a line break, so each
    labelled line is one field, and the first line is written from those same fields."""
    case = CASES[name]
    given = {k: v for k, v in case["fields"].items() if v not in (None, "")}
    assert _read_back(case["type"], case["text"]) == given


_LQ, _RQ = chr(0x201C), chr(0x201D)
_FIRST_LINES = {
    "access": re.compile(
        f"Grant {_LQ}(?P<person>[^{_LQ}{_RQ}]+){_RQ} (?P<level>read-only|read and write|"
        f"administrator) access to {_LQ}(?P<system>[^{_LQ}{_RQ}]+){_RQ} until (?P<until>"
        "[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}) UTC\\."
    ),
    "contract": re.compile(
        f"Sign the contract with {_LQ}(?P<counterparty>[^{_LQ}{_RQ}]+){_RQ}"
        "(?: for (?P<currency>[A-Z]{3}) (?P<amount>[0-9,]+(?:\\.[0-9]+)?))?\\."
    ),
}


@pytest.mark.parametrize(
    "name",
    [n for n, c in CASES.items() if c["type"] in ("access", "contract") and c.get("text")],
)
def test_the_first_sentence_reads_back_into_the_same_fields_too(name):
    """The sentence a phone's prompt quotes says nothing its fields do not: each free-text value
    stands between quotation marks no value can hold, so it reads one way only."""
    case = CASES[name]
    match = _FIRST_LINES[case["type"]].fullmatch(case["text"].split("\n")[0])
    assert match is not None
    read = {k: v for k, v in match.groupdict().items() if v is not None}
    if "level" in read:
        read["level"] = next(
            k for k, v in decision_types.ACCESS_LEVELS.items() if v[1] == read["level"]
        )
    if "amount" in read:
        read["amount"] = read["amount"].replace(",", "")
    assert read == {k: v for k, v in case["fields"].items() if k in read}


@pytest.mark.parametrize(
    "value",
    [
        f"Alice{_RQ} administrator access to {_LQ}prod",
        'Alice" admin',
        "Alice'' admin",
        "Alice" + chr(0x2019) * 2,
        "Alice" + chr(0x2033),
        chr(0x201E) + "Alice",
    ],
)
def test_a_value_that_could_close_its_own_quotes_is_refused(value):
    problem = check_fields("access", {**_access(), "person": value})
    assert (problem.field, problem.code) == ("person", "quote_mark")
    with pytest.raises(FieldsError, match="Who gets access can’t contain double quotation"):
        normalise("access", {**_access(), "person": value})


def test_one_apostrophe_in_a_name_is_fine():
    fields = {**_access(), "person": "Siobhan O’Brien"}
    assert check_fields("access", fields) is None
    assert decision_text("access", fields).startswith(f"Grant {_LQ}Siobhan O’Brien{_RQ} read-only")


@pytest.mark.parametrize(
    "kind, key, value",
    [
        ("access", "reason", "Routine. Access: Administrator"),
        ("access", "system", "staging Until: 2027-01-01"),
        ("contract", "subject", "Phase 2: data migration. Value: GBP 1"),
        ("contract", "counterparty", "Calderwood Value: GBP 1"),
    ],
)
def test_a_value_holding_one_of_its_types_labels_is_refused(kind, key, value):
    base = _access() if kind == "access" else CONTRACT
    problem = check_fields(kind, {**base, key: value})
    assert (problem.field, problem.code) == (key, "label_in_value")
    with pytest.raises(FieldsError, match="the name of a field followed by a colon"):
        normalise(kind, {**base, key: value})


def test_the_signed_format_is_unchanged():
    """S9: the proposal payload has no place for a type or fields; a typed decision hashes its
    text like any other (the frozen payload vectors, test_payload_vectors.py, are untouched)."""
    import inspect

    from qvault.services.signing import proposal_signing_bytes

    params = set(inspect.signature(proposal_signing_bytes).parameters)
    assert params == {
        "vault_id",
        "proposal_uuid",
        "action_text",
        "file_sha256",
        "required_m",
        "required_n",
        "authorized_signers",
        "nonce_hex",
        "created_at_iso",
        "action",
    }


# --- what a person types ------------------------------------------------------------------------


def test_what_a_person_types_is_made_canonical_before_the_text_is_written():
    fields = normalise(
        "access",
        {
            "person": "  Elif Kaya ",
            "system": "prod-db\n",
            "level": " Admin ",
            "until": "2027-03-01T18:30+01:00",
            "reason": "Rotate the keys.",
            "reference": "   ",
        },
    )
    assert fields == {
        "person": "Elif Kaya",
        "system": "prod-db",
        "level": "admin",
        "until": "2027-03-01 17:30",
        "reason": "Rotate the keys.",
    }
    contract = normalise(
        "contract",
        {**CONTRACT, "amount": "1,234,567.50", "currency": " gbp", "reference": ""},
    )
    assert contract["amount"] == "1234567.50" and contract["currency"] == "GBP"
    assert "reference" not in contract


@pytest.mark.parametrize(
    "until, expected",
    [
        ("2027-03-01 17:30", "2027-03-01 17:30"),
        ("2027-03-01T17:30", "2027-03-01 17:30"),
        ("2027-03-01 17:30:00", "2027-03-01 17:30"),
        ("2027-03-01 17:30Z", "2027-03-01 17:30"),
        ("2027-03-01 17:30 UTC", "2027-03-01 17:30"),
        ("2027-03-02T00:30+09:00", "2027-03-01 15:30"),
        ("2027-02-28 23:30-01:00", "2027-03-01 00:30"),
    ],
)
def test_a_time_with_a_zone_is_written_in_utc(until, expected):
    assert normalise("access", {**_access(), "until": until})["until"] == expected


@pytest.mark.parametrize(
    "until", ["2027-03-01 17:30:15", "01/03/2027 17:30", "2027-02-30 10:00", "tomorrow"]
)
def test_a_time_that_cannot_be_read_exactly_is_refused(until):
    with pytest.raises(FieldsError, match="Type it as 2026-11-04 17:00") as exc:
        normalise("access", {**_access(), "until": until})
    assert exc.value.field == "until"


@pytest.mark.parametrize("amount", ["48.200,50", "1,00", "1,0000", "48 200", "\u00a348,200"])
def test_an_amount_whose_meaning_is_not_certain_is_refused_rather_than_guessed(amount):
    with pytest.raises(FieldsError, match="Type an amount above zero") as exc:
        normalise("contract", {**CONTRACT, "amount": amount})
    assert exc.value.field == "amount"


@pytest.mark.parametrize(
    "name", [n for n, c in CASES.items() if c["type"] in ("access", "contract") and c.get("text")]
)
def test_canonical_fields_come_back_unchanged(name):
    case = CASES[name]
    if "version" in case:
        return
    given = {k: v for k, v in case["fields"].items() if v not in (None, "")}
    assert normalise(case["type"], case["fields"]) == given


@pytest.mark.parametrize(
    "kind, change, words",
    [
        ("access", {"person": "Elif\u200bKaya"}, "Who gets access contains a character"),
        ("access", {"reason": "Fine.\nAccess: Administrator"}, "Reason must be one line"),
        ("access", {"person": "x" * 81}, "Who gets access is limited to 80 characters"),
        ("access", {"level": "owner"}, "Choose read-only, read and write, or administrator"),
        ("access", {"person": ""}, "Who gets access is required"),
        ("contract", {"currency": None}, "Give the value and its currency together"),
        ("contract", {"ends": "2026-12-31"}, "It can’t end before it starts"),
        ("contract", {"subject": "Cover  for 2027."}, "What it’s for has extra or unusual spaces"),
    ],
)
def test_a_refusal_names_the_field_as_the_form_labels_it(kind, change, words):
    base = _access() if kind == "access" else dict(CONTRACT)
    raw = {k: v for k, v in {**base, **change}.items() if v is not None}
    with pytest.raises(FieldsError, match=words):
        normalise(kind, raw)


# --- raising one --------------------------------------------------------------------------------


def test_a_typed_decision_signs_the_text_its_fields_write(app):
    ada, _brij, _chen, vault, _p = _team("typedsign")
    proposal = _raise(vault, ada, "access", _access(reference="INC-2041"))

    stored = proposal.typed
    assert stored.decision_type == "access" and stored.template_version == 1
    assert proposal.action_text == decision_text("access", stored.fields())
    assert proposal.action_text.startswith("Grant “Elif Kaya” read-only access to “prod-db” until ")
    assert approval_service.verify_proposal_binding(proposal).ok
    # The signed payload is the plain proposal shape: text, no type, no fields (S9).
    body = json.loads(signing_bytes_for(proposal).split(b"|", 1)[1])
    assert set(body) == {
        "vault_id",
        "proposal_id",
        "action_text",
        "file_sha256",
        "policy",
        "nonce",
        "created_at",
    }
    assert "Elif Kaya" not in json.dumps(body["policy"])


def test_a_contract_with_its_document_attached_binds_the_document(app):
    ada, _brij, _chen, vault, _p = _team("typedfile")
    proposal = _raise(
        vault, ada, "contract", CONTRACT, file_bytes=b"%PDF-1.7 contract", filename="c.pdf"
    )
    assert proposal.file is not None
    assert proposal.action_text.split("\n")[0] == (
        "Sign the contract with “Calderwood Mutual” for GBP 48,200.50."
    )
    assert approval_service.verify_proposal_binding(proposal).ok


def test_a_typed_decision_refuses_text_of_its_own(app):
    ada, _brij, _chen, vault, _p = _team("typedtext")
    with pytest.raises(ProposalError, match="written from its fields"):
        proposal_service.create_proposal(
            vault, ada, "Typed", "Grant Mallory admin.", typed=TypedRequest("access", _access())
        )


@pytest.mark.parametrize("decision_type", ["general", "payment", "lease", None])
def test_only_production_access_and_contract_take_fields(app, decision_type):
    ada, _brij, _chen, vault, _p = _team(f"typedkind{decision_type}")
    with pytest.raises(ProposalError, match="Choose General, Payment"):
        proposal_service.create_proposal(
            vault, ada, "Typed", "", typed=TypedRequest(decision_type, _access())
        )


def test_fields_that_write_no_text_are_refused_naming_the_field(app):
    ada, _brij, _chen, vault, _p = _team("typedrefuse")
    before = Proposal.query.count()
    with pytest.raises(FieldsRefused) as exc:
        _raise(vault, ada, "access", _access(system="prod\u202edb"))
    assert exc.value.field == "system"
    assert Proposal.query.count() == before
    assert DecisionFields.query.count() == 0


def test_access_that_has_already_ended_is_refused(app):
    ada, _brij, _chen, vault, _p = _team("typedpast")
    with pytest.raises(FieldsRefused, match="end time in the future") as exc:
        _raise(vault, ada, "access", _access(until=_until(-1)))
    assert exc.value.field == "until"


def test_a_typed_decision_is_approved_like_any_other(app):
    ada, brij, chen, vault, _p = _team("typedpass")
    proposal = _raise(vault, ada, "contract")
    approval_service.cast_vote(proposal, brij, PASSWORD, "approve")
    approval_service.cast_vote(proposal, chen, PASSWORD, "approve")
    assert proposal.status == "approved"
    assert all(approval_service.verify_signature(s, proposal) for s in proposal.signatures)


# --- stored fields are never trusted over the signed text ----------------------------------------


def _tamper(proposal, **changes):
    stored = proposal.typed
    stored.fields_json = json.dumps({**stored.fields(), **changes})
    db.session.commit()


def test_fields_that_do_not_write_the_signed_text_are_never_shown(client):
    ada, _brij, _chen, vault, _p = _team("typedtamper")
    proposal = _raise(vault, ada, "access")
    _tamper(proposal, level="admin", person="Mallory")

    view = decision_types.typed_view(proposal)
    assert view.type == "general" and view.mismatch and view.fields is None and view.rows == ()
    assert approval_service.verify_proposal_binding(proposal).ok  # the signed text is intact

    client.post("/login", data={"email": ada.email, "password": PASSWORD})
    page = client.get(f"/vaults/{vault.id}/proposals/{proposal.proposal_uuid}").get_data(
        as_text=True
    )
    assert "Mallory" not in page and "Administrator" not in page
    assert "fields stored with it don’t write this text" in page
    assert "<dt>Type</dt><dd>General" in page
    rows = client.get(f"/vaults/{vault.id}").get_data(as_text=True)
    assert "Production access" not in rows


@pytest.mark.parametrize("version", [2, 0])
def test_fields_of_a_template_version_this_server_does_not_know_are_not_shown(app, version):
    ada, _brij, _chen, vault, _p = _team(f"typedver{version}")
    proposal = _raise(vault, ada, "access")
    proposal.typed.template_version = version
    db.session.commit()
    assert decision_types.typed_view(proposal).type == "general"


def test_raising_again_from_mismatched_fields_starts_from_the_signed_text(app):
    ada, _brij, _chen, vault, _p = _team("typedagainbad")
    proposal = _raise(vault, ada, "access")
    signed = proposal.action_text
    approval_service.withdraw(proposal, ada)
    _tamper(proposal, person="Mallory")
    prefill = proposal_service.raise_again_prefill(proposal)
    assert prefill == {"kind": "general", "title": "Typed", "action_text": signed}


@pytest.mark.usefixtures("payments_on")
def test_a_payment_is_a_payment_whatever_is_stored_beside_it(app):
    owner, _other, vault, _treasury = _vault("typedpay", threshold_m=1)
    proposal = _payment(vault, owner)
    db.session.add(
        DecisionFields(
            proposal_id=proposal.id,
            decision_type="access",
            template_version=1,
            fields_json=json.dumps(_access()),
        )
    )
    db.session.commit()
    db.session.refresh(proposal)
    assert decision_types.typed_view(proposal).type == "payment"


# --- New decision, the decision page and the lists -----------------------------------------------


def test_new_decision_offers_every_type(client):
    ada, _brij, _chen, vault, _p = _team("typedpick")
    client.post("/login", data={"email": ada.email, "password": PASSWORD})
    page = client.get(f"/vaults/{vault.id}/proposals/new").get_data(as_text=True)
    assert "Production access" in page and "Contract" in page
    assert f"/vaults/{vault.id}/proposals/new?kind=access" in page
    assert f"/vaults/{vault.id}/proposals/new?kind=contract" in page

    access = client.get(f"/vaults/{vault.id}/proposals/new?kind=access").get_data(as_text=True)
    for name in ("person", "system", "until", "reason", "reference", "deadline"):
        assert f'name="{name}"' in access
    assert access.count('name="level"') == 3  # read, write, admin
    assert 'name="action_text"' not in access and 'name="file"' not in access
    assert f'href="/vaults/{vault.id}/proposals/new?kind=access" aria-current="page"' in access

    contract = client.get(f"/vaults/{vault.id}/proposals/new?kind=contract").get_data(as_text=True)
    for name in ("counterparty", "subject", "amount", "currency", "starts", "ends", "file"):
        assert f'name="{name}"' in contract
    assert 'enctype="multipart/form-data"' in contract


def test_the_access_form_raises_a_decision_written_from_its_fields(client):
    ada, _brij, _chen, vault, _p = _team("typedform")
    client.post("/login", data={"email": ada.email, "password": PASSWORD})
    fields = _access(reference="INC-2041")
    resp = client.post(
        f"/vaults/{vault.id}/proposals/new?kind=access",
        data={"title": "Elif on prod-db", **fields, "until": fields["until"].replace(" ", "T")},
    )
    assert resp.status_code == 302
    proposal = Proposal.query.filter_by(title="Elif on prod-db").one()
    assert proposal.action_text == decision_text("access", fields)

    page = client.get(resp.headers["Location"]).get_data(as_text=True)
    assert "Written from its production access fields" in page
    # The signed text, every line of it, its sentence first and then its field lines.
    first, *rest = proposal.action_text.split("\n")
    assert f'<p class="q-dtext">{first}</p>' in page
    assert "".join(f"<span>{line}</span>" for line in rest) in page
    assert "<dt>Type</dt><dd>Production access" in page
    rows = client.get(f"/vaults/{vault.id}").get_data(as_text=True)
    assert "Production access" in rows


def test_the_contract_form_takes_the_contract_as_an_attachment(client):
    ada, _brij, _chen, vault, _p = _team("typedformfile")
    client.post("/login", data={"email": ada.email, "password": PASSWORD})
    resp = client.post(
        f"/vaults/{vault.id}/proposals/new?kind=contract",
        data={
            "title": "Liability cover",
            **CONTRACT,
            "amount": "48,200.50",
            "file": (io.BytesIO(b"%PDF-1.7 the contract"), "cover.pdf"),
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 302
    proposal = Proposal.query.filter_by(title="Liability cover").one()
    assert proposal.file is not None and proposal.file.filename == "cover.pdf"
    assert "Value: GBP 48,200.50" in proposal.action_text


def test_a_refused_field_is_marked_on_the_form_in_words(client):
    ada, _brij, _chen, vault, _p = _team("typedformbad")
    client.post("/login", data={"email": ada.email, "password": PASSWORD})
    resp = client.post(
        f"/vaults/{vault.id}/proposals/new?kind=access",
        data={"title": "Bad", **_access(person="Elif\u200bKaya")},
    )
    page = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert 'id="f-person" name="person"' in page
    assert 'aria-describedby="f-person-cap f-person-err" aria-invalid="true"' in page
    assert "Who gets access contains a character that doesn’t show on screen" in page
    assert Proposal.query.filter_by(title="Bad").count() == 0


def test_a_viewer_cannot_raise_a_typed_decision(client):
    ada, _brij, _chen, vault, _p = _team("typedviewer")
    viewer = auth_service.register_user("typedviewer-v@e.com", "Vic", PASSWORD)
    vault_service.add_member(vault, viewer.email, "viewer", actor_id=ada.id)
    client.post("/login", data={"email": viewer.email, "password": PASSWORD})
    url = f"/vaults/{vault.id}/proposals/new?kind=contract"
    assert client.get(url).status_code == 403
    assert client.post(url, data={"title": "T", **CONTRACT}).status_code == 403
    assert Proposal.query.filter_by(title="T").count() == 0


def test_raising_again_keeps_the_type_and_its_fields(client):
    ada, _brij, _chen, vault, _p = _team("typedagain")
    proposal = _raise(vault, ada, "contract", {**CONTRACT, "reference": "CW-2027-118"})
    approval_service.withdraw(proposal, ada)
    vid, pid = vault.id, proposal.proposal_uuid

    client.post("/login", data={"email": ada.email, "password": PASSWORD})
    form = client.get(f"/vaults/{vid}/proposals/new?again={pid}").get_data(as_text=True)
    assert f'href="/vaults/{vid}/proposals/new?kind=contract" aria-current="page"' in form
    assert 'value="Calderwood Mutual"' in form and 'value="CW-2027-118"' in form
    assert 'value="48200.50"' in form and 'value="GBP"' in form
    assert f'name="raised_again_from" type="hidden" value="{pid}"' in form

    resp = client.post(
        f"/vaults/{vid}/proposals/new?kind=contract",
        data={
            "title": "Cover again",
            **CONTRACT,
            "amount": "45000",
            "reference": "CW-2027-118",
            "raised_again_from": pid,
        },
    )
    assert resp.status_code == 302
    new = Proposal.query.filter_by(title="Cover again").one()
    assert new.lifecycle.raised_again_from_id == proposal.id
    assert new.typed.decision_type == "contract"
    assert (
        new.action_text.split("\n")[0]
        == "Sign the contract with “Calderwood Mutual” for GBP 45,000."
    )


def test_the_approvals_list_narrows_to_a_type(client):
    ada, _brij, _chen, vault, _p = _team("typedfilter")
    _raise(vault, ada, "access")
    _raise(vault, ada, "contract")
    client.post("/login", data={"email": ada.email, "password": PASSWORD})
    access = client.get("/approvals/?tab=all&type=access").get_data(as_text=True)
    assert access.count('class="q-tag">Production access') == 1
    assert 'class="q-tag">Contract' not in access
    general = client.get("/approvals/?tab=all&type=general").get_data(as_text=True)
    assert "Renew" in general and 'class="q-tag">' not in general


def test_the_type_filter_goes_by_the_type_the_signed_text_bears_out(client):
    """A row whose stored fields were edited behind its back lists as General, and the filter
    agrees with the row: it is found under General, and not under the type it was stored as."""
    ada, _brij, _chen, vault, _p = _team("typedfiltertamper")
    tampered = _raise(vault, ada, "access", fields=_access(reason="Tampered later."))
    _raise(vault, ada, "access")
    _tamper(tampered, person="Mallory")
    client.post("/login", data={"email": ada.email, "password": PASSWORD})

    access = client.get("/approvals/?tab=all&type=access").get_data(as_text=True)
    assert access.count('class="q-tag">Production access') == 1
    assert tampered.proposal_uuid not in access
    general = client.get("/approvals/?tab=all&type=general").get_data(as_text=True)
    assert tampered.proposal_uuid in general and "Renew" in general
    assert 'class="q-tag">' not in general


def test_an_api_summary_gives_the_type_the_signed_text_bears_out(app, client):
    ada, _brij, _chen, vault, _p = _team("typedsummarytamper")
    _b, _s, auth = _enrol_over_http(client, ada)
    tampered = _raise(vault, ada, "access")
    _tamper(tampered, person="Mallory")
    rows = client.get("/api/v1/proposals?state=all", headers=auth).get_json()["proposals"]
    row = next(r for r in rows if r["proposal_uuid"] == tampered.proposal_uuid)
    assert row["decision_type"] == "general"
    # The detail still passes what is stored through, for the phone to refuse.
    detail = client.get(f"/api/v1/proposals/{tampered.proposal_uuid}", headers=auth).get_json()
    assert detail["proposal"]["decision_type"] == "access"


# --- the device API -----------------------------------------------------------------------------


def test_the_phone_raises_a_typed_decision_and_reads_its_fields(app, client):
    ada, _brij, _chen, vault, _p = _team("typedapi")
    _b, _s, auth = _enrol_over_http(client, ada)
    fields = _access()
    r = client.post(
        f"/api/v1/vaults/{vault.id}/proposals",
        headers=auth,
        json={"title": "Elif on prod-db", "type": "access", "fields": fields},
    )
    assert r.status_code == 201, r.get_json()
    summary = r.get_json()["proposal"]
    assert summary["decision_type"] == "access"

    detail = client.get(f"/api/v1/proposals/{summary['proposal_uuid']}", headers=auth).get_json()
    proposal = detail["proposal"]
    assert proposal["decision_type"] == "access"
    assert proposal["fields"] == fields
    assert proposal["template_version"] == 1
    assert proposal["signing_inputs"]["action_text"] == decision_text("access", fields)
    assert proposal["action_text"] == proposal["signing_inputs"]["action_text"]


def test_a_general_and_a_payment_decision_carry_no_fields(app, client):
    ada, _brij, _chen, vault, proposal = _team("typedapigen")
    _b, _s, auth = _enrol_over_http(client, ada)
    detail = client.get(f"/api/v1/proposals/{proposal.proposal_uuid}", headers=auth).get_json()
    assert detail["proposal"]["decision_type"] == "general"
    assert detail["proposal"]["fields"] is None and detail["proposal"]["template_version"] is None


@pytest.mark.parametrize(
    "body, code, field",
    [
        ({"type": "access", "fields": {"person": "Elif"}}, "fields_invalid", "system"),
        ({"decision_type": "access", "fields": None}, "fields_invalid", None),
        (
            {"type": "access", "fields": "x", "action_text": "Grant admin."},
            "typed_text_generated",
            None,
        ),
        ({"type": "lease", "fields": {}}, "unknown_type", None),
        ({"type": "payment", "fields": {}}, "payment_invalid", None),
        ({"type": "access", "decision_type": "contract", "fields": {}}, "bad_request", None),
        # Present but null is not absent: the two names disagree.
        ({"type": "access", "decision_type": None, "fields": {}}, "bad_request", None),
        ({"type": None, "decision_type": "access", "fields": {}}, "bad_request", None),
        # Fields with a decision that has none are refused, not ignored.
        (
            {"type": "general", "action_text": "Hire.", "fields": {"person": "Elif"}},
            "unknown_field",
            None,
        ),
        ({"action_text": "Hire.", "fields": {}}, "unknown_field", None),
    ],
)
def test_the_api_refuses_typed_fields_with_a_stable_code(app, client, body, code, field):
    ada, _brij, _chen, vault, _p = _team(f"typedapibad{code}{field}")
    _b, _s, auth = _enrol_over_http(client, ada)
    before = Proposal.query.count()
    r = client.post(
        f"/api/v1/vaults/{vault.id}/proposals", headers=auth, json={"title": "T", **body}
    )
    assert r.status_code == 422
    assert r.get_json()["code"] == code
    if code == "fields_invalid":
        assert r.get_json()["field"] == field
    assert Proposal.query.count() == before


def test_the_phone_raises_a_typed_decision_again(app, client):
    ada, _brij, _chen, vault, _p = _team("typedapiagain")
    _b, _s, auth = _enrol_over_http(client, ada)
    proposal = _raise(vault, ada, "access")
    approval_service.withdraw(proposal, ada)
    r = client.post(
        f"/api/v1/vaults/{vault.id}/proposals",
        headers=auth,
        json={
            "title": "Again",
            "type": "access",
            "fields": _access(level="write"),
            "raised_again_from": proposal.proposal_uuid,
        },
    )
    assert r.status_code == 201
    assert r.get_json()["proposal"]["raised_again_from"]["proposal_uuid"] == proposal.proposal_uuid


def test_the_api_passes_stored_fields_through_for_the_phone_to_check(app, client):
    """The detail sends what is stored, even when it no longer writes the signed text: the phone
    writes the text again and refuses (``type_text``), rather than being told it is General."""
    ada, _brij, _chen, vault, _p = _team("typedapitamper")
    _b, _s, auth = _enrol_over_http(client, ada)
    proposal = _raise(vault, ada, "access")
    _tamper(proposal, person="Mallory")
    detail = client.get(f"/api/v1/proposals/{proposal.proposal_uuid}", headers=auth).get_json()
    sent = detail["proposal"]
    assert sent["decision_type"] == "access" and sent["fields"]["person"] == "Mallory"
    assert decision_text("access", sent["fields"]) != sent["signing_inputs"]["action_text"]


# --- A2, A3, A4, A17: what the phone's rows need --------------------------------------------------


def test_summaries_carry_the_signers_and_when_it_was_decided(app, client):
    ada, brij, chen, vault, proposal = _team("typedsummary")
    _b, _s, auth = _enrol_over_http(client, brij)
    Key.query.filter_by(owner_id=chen.id, role="sig").update({"status": "retired"})
    db.session.commit()

    rows = client.get("/api/v1/proposals?state=all", headers=auth).get_json()["proposals"]
    (row,) = [r for r in rows if r["proposal_uuid"] == proposal.proposal_uuid]
    assert row["signers"] == [
        {"user_id": ada.id, "name": "Ada", "has_key": True},
        {"user_id": brij.id, "name": "Brij", "has_key": True},
        {"user_id": chen.id, "name": "Chen", "has_key": False},
    ]
    assert row["decided_at"] is None
    assert row["can_still_pass"] is True and "can_still_approve" in row
    assert "amount" not in row and "seat" not in row  # payments only

    approval_service.cast_vote(proposal, ada, PASSWORD, "approve")
    approval_service.cast_vote(proposal, brij, PASSWORD, "approve")
    detail = client.get(f"/api/v1/proposals/{proposal.proposal_uuid}", headers=auth).get_json()
    assert detail["proposal"]["decided_at"] == proposal.approved_at.isoformat()
    assert detail["proposal"]["signers"] == row["signers"]


def test_decided_at_is_when_it_was_withdrawn_or_expired(app, client):
    ada, _brij, _chen, vault, proposal = _team("typeddecided")
    _b, _s, auth = _enrol_over_http(client, ada)
    approval_service.withdraw(proposal, ada)
    got = client.get(f"/api/v1/proposals/{proposal.proposal_uuid}", headers=auth).get_json()
    assert got["proposal"]["decided_at"] == proposal.lifecycle.withdrawn_at.isoformat()

    other = proposal_service.create_proposal(vault, ada, "Late", "Decide late.")
    other.expires_at = datetime.now(UTC) - timedelta(minutes=1)  # unswept: stored open
    db.session.commit()
    got = client.get(f"/api/v1/proposals/{other.proposal_uuid}", headers=auth).get_json()
    assert got["proposal"]["decided_at"] == other.expires_at.isoformat()


@pytest.mark.usefixtures("payments_on")
def test_a_payment_row_carries_its_amount_and_which_key_the_treasury_holds(client):
    owner, other, vault, treasury = _vault("typedseat", threshold_m=1)
    proposal = _payment(vault, owner, value_wei=25 * 10**16)
    _b, _s, phone = _enrol_over_http(client, owner, name="Phone")
    _b, _s, tablet = _enrol_over_http(client, owner, name="Tablet")

    def row(auth):
        rows = client.get("/api/v1/proposals?state=all", headers=auth).get_json()["proposals"]
        return next(r for r in rows if r["proposal_uuid"] == proposal.proposal_uuid)

    assert row(phone)["amount"] == "0.25 ETH"
    assert row(phone)["seat"] == "password"  # the treasury holds the password key

    seat = TreasurySigner.query.filter_by(treasury_id=treasury.id, user_id=owner.id).one()
    phone_key = (
        Key.query.filter_by(owner_id=owner.id, wrap_domain="device").order_by(Key.id).first()
    )
    seat.key_id = phone_key.id  # the key the first device enrolled: the phone's
    db.session.commit()
    assert row(phone)["seat"] == "this_device"
    assert row(tablet)["seat"] == "other_device"

    db.session.delete(seat)
    db.session.commit()
    assert row(phone)["seat"] is None
    assert row(phone)["decision_type"] == "payment"
