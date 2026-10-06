"""The rules behind the evidence screens: the decision page, the audit log and Verify (rework R2).

Pure functions, no database: each is a rule that must read the same on every screen and that a
test can pin from known inputs. The database work that feeds them lives in
``qvault.services.evidence_service``; ``register`` puts the ones templates need on Jinja.

* ``decision_code``: the short code a person compares between the web and the phone (plan S17).
* ``personal_status``: which word of the closed vocabulary (S6, ``qvault.ui.STATUS``) a decision
  shows to *this* viewer.
* ``approve_consequence`` and ``reject_consequence``: what signing will do, computed from the rule
  rather than written as fixed copy (S4; style tile finding 1).
* ``check_word``: the only three words a check row may say (plan section 6).
* ``entry_integrity``: the audit log's integrity column.
* ``coverage_line``: Verify's "Checked: ..." sentence, built from the checks that actually ran.
* ``decision_text_html``: the decision text with its Ethereum addresses set in mono (section 6),
  without changing a single character of what is copied.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from markupsafe import Markup, escape

# ------------------------------------------------------------------------------ decision code


def decision_code(payload_hash: str) -> str:
    """The first 8 hex characters of the payload hash, upper case, grouped 4 and 4: ``7F3A-91C2``.

    Display only: it is the hash both sides already compute, cut short so it can be read aloud
    and compared by eye. It is not a second hash and nothing signs it (S9, S17).
    """
    head = (payload_hash or "")[:8]
    if len(head) != 8 or not all(c in "0123456789abcdefABCDEF" for c in head):
        raise ValueError("a decision code needs the first 8 hex characters of a payload hash")
    head = head.upper()
    return f"{head[:4]}-{head[4:]}"


# ------------------------------------------------------------------------------ status (S6)

#: A payout's own state (``payout_service.view``) in the closed vocabulary. States that are not a
#: payout yet (``awaiting_approvals``, ``not_paid``) have no word of their own: the decision's word
#: stands. Sending is still Queued until a block confirms it (style tile finding 4); a voided or
#: lapsed payout is Failed, always shown with its reason.
PAYOUT_STATUS = {
    "queued": "queued",
    "submitting": "queued",
    "confirmed": "paid",
    "failed": "failed",
    "voided": "failed",
    "expired": "failed",
}


def payout_status(state: str | None) -> str | None:
    return PAYOUT_STATUS.get(state or "")


def personal_status(
    status: str,
    *,
    can_vote: bool,
    approvals: int,
    required_m: int,
    payout_state: str | None = None,
) -> tuple[str, int | None]:
    """The status key (and count) a decision shows its viewer.

    Open and yours to sign: "Needs your signature". Open otherwise: "Waiting on N", where N is the
    approvals still needed, not people (S6). An approved payment shows how its payout stands once
    one exists. Anything outside the vocabulary is refused rather than shown.
    """
    if status == "open":
        if can_vote:
            return "needs_you", None
        return "waiting", max(required_m - approvals, 0)
    if status == "approved":
        return payout_status(payout_state) or "approved", None
    if status in ("rejected", "expired", "withdrawn"):
        return status, None
    raise ValueError(f"{status!r} is not a decision status")


# ------------------------------------------------------------------------------ consequences (S4)


def _approvals(n: int) -> str:
    return f"{n} more approval{'' if n == 1 else 's'}"


def approve_consequence(
    *, approvals: int, required_m: int, payment: str | None = None
) -> list[str]:
    """What approving does, as sentences. ``payment`` is the amount ("0.25 ETH") for a payment.

    ``approvals`` counts valid approvals only, the same count the rule uses.
    """
    after = approvals + 1
    lines = []
    if after >= required_m:
        if payment:
            lines.append(
                f"Yours completes the approvals. Once you sign, the treasury is asked to pay "
                f"{payment} to the address above."
            )
        else:
            lines.append("Yours completes the approvals. Once you sign, this decision is approved.")
    else:
        lines.append(f"After yours, this still needs {_approvals(required_m - after)}.")
    lines.append(
        "You can't withdraw your signature"
        + (", and a payment can't be reversed once it is sent." if payment else ".")
    )
    return lines


def reject_consequence(*, rejections: int, required_m: int, required_n: int) -> list[str]:
    """What rejecting does. A decision is rejected once rejections exceed N minus M, because the
    approvals it needs can then no longer be reached (``approval_service._finalize_if_decided``).
    So "Rejecting ends this decision for everyone" is only true when this rejection crosses that
    line; in a 2 of 4 vault one rejection changes nothing on its own (style tile finding 1).
    """
    limit = required_n - required_m
    after = rejections + 1
    if after > limit:
        lines = ["Rejecting ends this decision for everyone. It can't be approved after this."]
    else:
        more = limit + 1 - after
        lines = [
            "Rejecting doesn't end this decision on its own. It ends only if "
            f"{more} more approver{' rejects' if more == 1 else 's reject'} it too."
        ]
    lines.append("You can't withdraw your rejection.")
    return lines


# ------------------------------------------------------------------------------ check words


#: The three results a check row may show (plan section 6). Inside technical panels the only
#: result words are Valid and Same as signed; these are never decision statuses.
CHECK_WORDS = {"passed": "Passed", "failed": "Failed", "unavailable": "Unavailable"}


def check_state(ok: bool, skipped: bool = False) -> str:
    """A check that did not run is Unavailable: neither a pass nor a failure."""
    if skipped:
        return "unavailable"
    return "passed" if ok else "failed"


def check_word(state: str) -> str:
    return CHECK_WORDS[state]


def checks_summary(states: list[str]) -> str:
    """ "5 checks passed", "1 of 6 checks failed", "4 checks passed, 1 unavailable"."""
    total = len(states)
    failed = states.count("failed")
    passed = states.count("passed")
    unavailable = states.count("unavailable")
    if not total:
        return "No checks ran"
    if failed:
        return f"{failed} of {total} check{'' if total == 1 else 's'} failed"
    line = f"{passed} check{'' if passed == 1 else 's'} passed"
    if unavailable:
        line += f", {unavailable} unavailable"
    return line


# ------------------------------------------------------------------------------ audit integrity

#: The audit log's integrity column (plan section 5), word and tone.
INTEGRITY = {
    "witnessed": ("Logged and witnessed", "success"),
    "awaiting": ("Awaiting witness", "neutral"),
    "logged": ("Logged", "neutral"),
    "failed": ("Failed", "critical"),
}


def entry_integrity(
    seq: int,
    *,
    chain_break_seq: int | None,
    witnessed_size: int | None,
    witnessed_ok: bool,
    witness_configured: bool,
) -> str:
    """Where one audit entry stands.

    * ``failed``: the hash chain breaks at or before this entry, so nothing from here on can be
      proved; or the witness co-signed a tree this entry should be in and the log no longer
      reproduces that tree (``witnessed_ok`` is the page's one check of that, made by recomputing
      the witnessed root and re-verifying the co-signature).
    * ``witnessed``: inside the newest tree an independent witness co-signed, and that still holds.
    * ``awaiting``: logged, and a witness is configured but has not reached this entry yet.
    * ``logged``: logged, with no witness configured to vouch for it.
    """
    if chain_break_seq is not None and seq >= chain_break_seq:
        return "failed"
    if witnessed_size is not None and seq < witnessed_size:
        return "witnessed" if witnessed_ok else "failed"
    return "awaiting" if witness_configured else "logged"


# ------------------------------------------------------------------------------ Verify's coverage


def _count(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def coverage_line(checks, bundle) -> str | None:
    """What a verification covered, CloudTrail style: "Checked: 3 signatures, 5 log entries,
    witness checkpoint". Only checks that actually ran are named, whatever their result; the rows
    below the line say which passed. ``checks`` is ``Report.checks``; ``bundle`` the parsed file.
    """
    ran = {c.key for c in checks if not c.skipped}
    if not isinstance(bundle, dict) or "content" not in ran:
        return None
    parts = ["the decision text"]
    signatures = bundle.get("signatures")
    if "signatures" in ran and isinstance(signatures, list):
        parts.append(_count(len(signatures), "signature", "signatures"))
    log = bundle.get("log") if isinstance(bundle.get("log"), dict) else {}
    entries = log.get("entries")
    if "log_entries" in ran and isinstance(entries, list):
        parts.append(_count(len(entries), "log entry", "log entries"))
    if "checkpoint" in ran:
        parts.append("the log checkpoint")
    if "witness" in ran:
        parts.append("the witness co-signature")
    if "execution" in ran:
        parts.append("the payment authorisations")
    return "Checked: " + ", ".join(parts) + "."


# ------------------------------------------------------------------------------ times


def _utc(moment: datetime) -> datetime:
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


def parse_stamp(value: str | datetime | None) -> datetime | None:
    """A ledger timestamp (RFC 3339 text) or a datetime, as an aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return _utc(value)
    try:
        return _utc(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except ValueError:
        return None


def precise_time(value: str | datetime | None) -> str:
    """Evidence precision, to the second with its zone: ``Sun 4 Oct 2026, 09:58:42 UTC``."""
    moment = parse_stamp(value)
    if moment is None:
        return ""
    return f"{moment:%a} {moment.day} {moment:%b %Y, %H:%M:%S} UTC"


def short_time(value: str | datetime | None) -> str:
    """A scanning time with its zone, no seconds: ``4 Oct 2026, 09:58 UTC``."""
    moment = parse_stamp(value)
    if moment is None:
        return ""
    return f"{moment.day} {moment:%b %Y, %H:%M} UTC"


# ------------------------------------------------------------------------------ decision text

_ADDRESS = re.compile(r"0x[0-9a-fA-F]{40}(?![0-9a-fA-F])")


def _address_html(address: str) -> str:
    """``0x`` + 40 hex, the first and last 4 bytes in medium weight, an optional break after
    every 10 characters. ``<wbr>`` adds no character, so a copy of the text is unchanged."""
    out = []
    for i, ch in enumerate(address):
        if i in (10, 20, 30, 40):
            out.append("<wbr>")
        if i == 2:
            out.append("<b>")
        if i == 34:
            out.append("<b>")
        out.append(ch)
        if i in (9, 41):
            out.append("</b>")
    return f'<span class="q-addr" translate="no">{"".join(out)}</span>'


def decision_text_html(text: str | None) -> Markup:
    """The decision text, escaped, with each Ethereum address wrapped for mono (plan section 6)."""
    escaped = str(escape(text or ""))
    return Markup(_ADDRESS.sub(lambda m: _address_html(m.group(0)), escaped))


def unix_time(seconds: int | None) -> datetime | None:
    """A payment's ``valid_until`` (unix seconds, as signed) as a UTC datetime."""
    if seconds is None:
        return None
    return datetime.fromtimestamp(int(seconds), UTC)


#: A decision's own log events, as a technical panel names them.
EVENT_WORDS = {
    "proposal_created": "Raised",
    "proposal_signed": "Signed",
    "proposal_approved": "Approved",
    "proposal_rejected": "Rejected",
    "proposal_expired": "Expired",
    "file_encrypted": "File attached",
    "decision_published": "Published",
    "decision_unpublished": "Public link revoked",
    "proposal_executed": "Paid by the treasury",
    "proposal_execution_failed": "Payout failed",
}


def event_words(event_type: str, who: str | None = None) -> str:
    """"Signed by Hassan", "Approved": a log event in words, with the protocol name as a fallback
    quoted in the interface face (plan section 6)."""
    word = EVENT_WORDS.get(event_type)
    if word is None:
        return f"“{event_type}”"
    if who and event_type in ("proposal_created", "proposal_signed"):
        return f"{word} by {'you' if who == 'You' else who}"
    return word


def register(app) -> None:
    app.jinja_env.globals.update(
        ev_code=decision_code,
        ev_check_word=check_word,
        ev_precise=precise_time,
        ev_short=short_time,
        ev_stamp=parse_stamp,
        ev_unix=unix_time,
        ev_event=event_words,
        ev_payout_status=payout_status,
        ev_integrity=INTEGRITY,
    )
    app.jinja_env.filters["decision_text"] = decision_text_html
