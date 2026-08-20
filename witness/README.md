# The witness

A small, separate service that watches a Q-Vault transparency log and co-signs its checkpoints —
but only while the log can prove it still contains everything the witness has already seen.

## Why it exists

[ADR-0005](../docs/adr/0005-ledger-head-anchor.md) closed most of the gap in a hash-chained audit
ledger, and then recorded, honestly, what it could not close:

> **Known limitation — truncation/rollback.** Because anchors live in the same store they protect,
> an adversary who deletes tail entries **and** their anchors leaves a shorter, internally
> consistent prefix that still verifies. This is inherent to any self-contained anchor with no
> external monotonic witness.

This is that external monotonic witness. It keeps, outside Q-Vault's database, the size and Merkle
root of the last checkpoint it co-signed. A log that has lost entries cannot produce a consistency
proof from that point, so it stops being witnessed — and the attempt is recorded here, signed by
the log's own key.

## Running it

```
python -m witness --port 5001 --state instance/witness.db --key instance/witness_key.json
```

It prints its key fingerprint on startup. **Publish that fingerprint.** It is what turns "signed by
a witness" into "signed by *the* witness" for anyone checking an exported decision:

```
python -m qvault.verify decision.qvault.json --expect-witness <fingerprint>
```

Point Q-Vault at it and restart:

```
WITNESS_URL=http://127.0.0.1:5001
```

Checkpoints are then offered on a timer (`WITNESS_SYNC_SECONDS`, default 60) rather than during
requests, so a witness that is down costs a growing lag on **Audit → Transparency**, never latency
on a user's write. Visit the witness's own root page to see what it has co-signed and refused.

For the property to mean anything in a real deployment, run it **on different hardware, under a
different operator**. On one laptop it demonstrates the mechanism; it does not deliver the
security, because whoever can rewrite the database can also stop the process and delete its file.

## What it refuses, and why each refusal is an attack

| Refusal | What happened |
| --- | --- |
| `shrank` | The log offered fewer entries than it was already co-signed for — truncation. |
| `fork` | A second, different Merkle root at a size already co-signed — two histories, shown to different people. |
| `inconsistent` | No valid consistency proof from the witness's high-water mark — past entries were rewritten. |
| `key_changed` | A different public key for a known origin — something else is claiming to be this log. |
| `bad_signature` | The checkpoint was not signed by the log's key. Without this check, anyone could park an enormous `tree_size` and lock the real log out permanently. |

Every refusal is stored with the offered checkpoint kept verbatim, so the attempt is evidence
rather than only a rejection.

## Design notes

**It has its own key and its own SQLite file.** That is the entire security property. It shares
*code* with Q-Vault — the RFC 6962 implementation, the statement encodings and the PQC providers
are imported from `qvault.transparency` and `qvault.crypto` — and that is a deliberate trade: two
hand-written implementations of RFC 6962 that disagreed would be a far worse failure than one
shared, exhaustively tested implementation. What is never shared is state or keys. A witness using
Q-Vault's database would be an elaborate way of asking the adversary to check their own work;
`tests/test_witness.py::test_the_witness_stores_nothing_in_the_vault_database` asserts it.

**Trust on first use.** The first public key seen for an origin is pinned as that origin's key
forever. TOFU is a real weakness — a witness that meets a fraudulent log before the real one pins
the wrong key — and it is strictly better than accepting any key at any time. The pinned
fingerprint is shown on the status page so it can be checked by hand against the operator's
published value.

**The witness signs a different statement from the log.** Same six checkpoint fields, different
domain tag (`QVAULT-WITNESS-v1` against `QVAULT-CHECKPOINT-v1`) and the witness's own name inside
the signed bytes. If both signed identical bytes, standing up a witness would hand out the ability
to mint checkpoints to anyone later mistaken for the log.

**Algorithm.** Defaults to ML-DSA-87, where the log uses ML-DSA-65. This was going to be the
hash-based SLH-DSA, for genuine diversity of assumption; `identity.py` records why it is not, and
`--alg SLH-DSA-SHAKE-256f` still selects it.

**The key is a file.** In a deployment that mattered this would be an HSM or a secret manager. The
file is a project-scale stand-in and is not pretended to be more than that — what it does buy is
the property that carries the argument: it is not in Q-Vault's database.
