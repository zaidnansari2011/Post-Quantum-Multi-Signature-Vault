# ADR-0020 — The glass box: a live, checkable trace of the cryptography

- **Status:** Accepted
- **Date:** 2026-09-08
- **Extends:** [ADR-0011](0011-demonstrability.md), [ADR-0015](0015-transparency-log-and-witness.md)
- **Bounded by:** [ADR-0014](0014-product-not-demonstration.md) — this is the one screen that
  deliberately breaks its "the interface explains nothing" rule, and it is quarantined for it.

## Context

Q-Vault can prove a great deal after the fact. A decision exports as a package a stranger can
check offline; a checkpoint carries an independent witness's co-signature; the ledger recomputes.
All of that answers *"was this decision genuine?"* — a question asked about a finished artefact.

It answers a different question badly: **"is this system actually doing what it says?"** Someone
watching a demonstration sees a password typed and a counter move from 1 to 2. The canonical
signing bytes, the domain-separation tag, the Argon2id derivation, the 3,309-byte ML-DSA
signature, the verification performed before those bytes were allowed to leave the signing
function, the chain link, the new Merkle root — every one of those happens in the dark. The
interface reports conclusions, and a conclusion is exactly what a sceptic will not accept.

The obvious response is a page that shows the source code. On its own that is worthless, and it is
worth being precise about why: **a page can print any code it likes.** Displaying `sign()` is not
evidence that `sign()` ran. A reviewer who accepts a code panel as proof has been persuaded by
typography. If we built only that, we would have built a tautology with syntax highlighting.

## Decision

**Trace real operations as they happen, show the code that ran beside the values it ran on, and
make every derived value independently recomputable off-system.**

The code panel is not the evidence. The *values* are. The code panel exists so a reader who
disagrees with a number knows which function to go and read.

### Three rules, one per module

**`glassbox/redaction.py` — visibility is opt-in.** A value reaches the page only if the call site
wrapped it in a presenter (`Text`, `Hex`, `Digest`, `Json`, `Label`, `Number`). Anything else is
coerced to `Opaque`, which states a length and nothing else. A denylist ("hide anything called
password") fails the first time somebody adds a traced value and forgets to list it, and in a
project about key custody that failure is a vulnerability, not a rendering bug. Under `TESTING`
the coercion becomes an exception, so the suite fails on an unwrapped value rather than shipping a
redaction that merely happened to be safe.

`Withheld` is separate from `Opaque` and exists for a specific reason: for a password, *any*
function of the value is a disclosure. `sha256(password)` is offline-crackable and the length
alone narrows a search. `Opaque` therefore emits no digest by default either — a digest of a
secret is a commitment to it, and lets anyone who can guess the value confirm the guess.

**`glassbox/source.py` — source is read, never stored.** `inspect.getsource` is called on the live
function object the caller is about to invoke, which reads the file the interpreter actually
loaded. The displayed text is the executed text by construction rather than by promise, and
`tests/test_glassbox.py::test_captured_source_matches_the_file_on_disk` reads the repository file
independently and compares.

**`glassbox/recorder.py` — nothing here may change what happened.** Every entry point swallows its
own exceptions; a presenter that raises degrades to `Opaque`. The one deliberate exception is that
a *step's* exception propagates untouched: swallowing that would turn a rejected signature into a
silent success, which is the precise failure this page exists to make impossible.

### Operations are scoped to the request, not to the service call

The head anchor and the Merkle checkpoint are computed in an `after_request` hook, long after
`cast_vote` has returned. An operation that closed with the service call would end immediately
before the most interesting step in it. So `before_request` opens one and `teardown_request`
closes one — and `close_operation` **discards any operation that recorded no steps**. Almost every
request records nothing, so opening one unconditionally costs a dataclass that is thrown away, and
the page becomes a record of cryptographic work rather than an access log. Instrumentation can be
added anywhere without anyone maintaining a list of interesting endpoints.

Context is held in a `contextvars` variable rather than a global, because the scheduler runs
rotation jobs on its own threads while requests are being served, and a global "current operation"
would file a background job's steps under whichever vote happened to be in flight.

### Polling, not streaming

The page polls `/trace/events?after=<cursor>` every 700 ms. SSE would be more elegant and is the
wrong choice here: a held connection occupies a worker for as long as the page is open, and on the
deployed single-worker container one viewer of this page would be enough to stop the application
answering anything else. At 700 ms the difference is imperceptible and a dropped poll costs one
late frame.

The cursor is `min(seq of anything still running) - 1`, not "the highest sequence seen". A naive
cursor renders a slow operation once and never asks for it again, freezing it on screen at
whichever step it had reached — so a vote would appear to stop permanently at Argon2id.

### "Check this yourself"

Every value small enough carries a shell one-liner that recomputes its digest:
`echo -n <hex> | xxd -r -p | sha256sum`. Hex piped through `xxd -r`, not the literal text through
`printf`, because quoting mangles the moment a canonical payload contains a quote or a non-ASCII
character — which is exactly when a reader most wants to check it. This is the affordance that
makes the page evidence: the reader leaves the application entirely and gets the same answer.

## What this page does not show, and says so

The trace shows Python we wrote. It **cannot** show the interior of ML-DSA or SLH-DSA, which are
compiled PQClean binaries invoked through the provider. For those steps it shows the complete call
— message, key, signature, verdict, timing — and the step's own note says the lattice arithmetic
is not visible here.

Stating that plainly is not a weakness of the design. A page that implied it was showing lattice
internals would be caught by the first examiner who looked, and would call every other claim on
the screen into question.

## Consequences

**Good.** The system's most-repeated operation becomes inspectable while it happens. Three claims
that were previously prose in an ADR are now watchable: ADR-0010's verify-before-release runs
visibly on every signature; the hash chain's tamper-evidence is one visible line taking the
previous entry's hash as input; a checkpoint refusing to sign a rewritten tree shows its
consistency proof failing. It also produces the dissertation's figures directly.

**Costs and risks.** The instrumentation lives on the live signing path, so presenter arguments
are constructed whether or not tracing is on — negligible beside an 80 ms Argon2id derivation, but
real. The trace is process-global, so it shows every user's operations to whoever opens it; hence
administrator-only. And it is **off by default** (`GLASSBOX_ENABLED`), on in development and in
the test suite. A page whose entire purpose is to reveal internals should not appear in a
deployment because nobody remembered to remove it, and when the flag is off every route 404s
rather than 403s, so a disabled instrument does not advertise itself.

**Deliberately not done.** No persistence — the buffer is a bounded ring of recent operations, and
the durable record remains the signed ledger. Nothing on this page is authoritative, and nothing
else in the system reads it.
