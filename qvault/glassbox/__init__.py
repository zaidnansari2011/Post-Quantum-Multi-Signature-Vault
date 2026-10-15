"""The glass box: what the machine did, in the code that did it, as it happens.

Q-Vault's security claims have always been checkable *after the fact* -- the offline verifier, the
witness, the Merkle proofs. What none of that shows is the middle of an operation. A signer types
a password and a counter moves; the canonical bytes, the domain-separation tag, the digest, the
signature, the chain link and the new tree root all happen in the dark.

This package lights that up, and it is careful about what it is claiming. Displaying source code
proves nothing on its own -- a page can print any code it likes. The evidence is the *values*:
every digest shown here comes with the exact bytes that produced it and a shell command that
recomputes it, so a sceptical reader can leave the application entirely and get the same answer.
The code panel is there so they know which function to blame when the numbers disagree.

Three modules, one rule each:

* :mod:`~qvault.glassbox.redaction` -- visibility is opt-in; an unwrapped value is withheld.
* :mod:`~qvault.glassbox.source` -- source is read from the live function object, never stored.
* :mod:`~qvault.glassbox.recorder` -- a step outside an operation is dropped, and nothing here
  can fail the operation it is watching.

An operation is scoped to the *request*, opened and closed by hooks in the application factory.
Service code never manages that lifecycle -- it only names the operation and records steps into
whichever one is open, and a step recorded with none open is silently dropped::

    glassbox.describe(title="Cast vote", kind="sign", subject=proposal.proposal_uuid)

    with glassbox.step("Build the signed message", code=vote_signing_bytes) as s:
        message = vote_signing_bytes(...)
        s.input("payload_hash", glassbox.Digest(proposal.payload_hash))
        s.output("message", glassbox.Text(message))

Disabled by default. See ``GLASSBOX_ENABLED`` in ``config.py`` and ADR-0020.
"""

from __future__ import annotations

from qvault.glassbox.recorder import (
    clear,
    close_operation,
    configure,
    describe,
    enabled,
    open_operation,
    operation,
    since,
    step,
)
from qvault.glassbox.redaction import (
    Digest,
    Hex,
    Json,
    Label,
    Number,
    Opaque,
    RedactionError,
    Text,
    Value,
    Withheld,
)

__all__ = [
    # recording
    "operation",
    "open_operation",
    "close_operation",
    "describe",
    "step",
    "enabled",
    "configure",
    # reading
    "since",
    "clear",
    # presenters -- the vocabulary a call site uses to say what may be shown
    "Digest",
    "Hex",
    "Json",
    "Label",
    "Number",
    "Opaque",
    "Text",
    "Value",
    "Withheld",
    "RedactionError",
]
