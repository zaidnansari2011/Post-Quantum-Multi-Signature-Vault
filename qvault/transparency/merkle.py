"""RFC 6962 Merkle tree hashing, inclusion proofs and consistency proofs.

Why this exists alongside the hash chain
----------------------------------------
The ledger is already a hash chain, and a chain is enough to detect an edit *if you are willing
to read the whole chain*. Two things it cannot do:

1. **Prove one entry belongs to the log without shipping the log.** Convincing a third party that
   decision #4,102 is in a 100,000-entry ledger means handing them 100,000 entries. A Merkle tree
   proves the same thing with ``ceil(log2(n))`` hashes — 17 of them, about 550 bytes. That is the
   difference between an exported decision being emailable and being a database dump.
2. **Prove the log only ever grew.** A chain lets you check that history is self-consistent, never
   that today's log *contains* the log you were shown last week. A consistency proof does exactly
   that, and it is what lets an outside witness catch the truncation attack that
   :doc:`ADR-0005 <../../docs/adr/0005-ledger-head-anchor>` documented as an accepted non-goal.

The chain is not replaced. Each leaf is the chain's own ``entry_hash``, so the tree is layered
over the chain rather than beside it: an adversary must satisfy both, and a verifier who
recomputes an entry hash from its fields has thereby recomputed the leaf.

Following the RFC exactly
-------------------------
RFC 6962 §2.1 is followed to the byte, including the ``0x00``/``0x01`` domain-separation prefixes
that stop a leaf being reinterpreted as an interior node (without them an attacker can present an
internal node's preimage as a leaf and prove membership of data that was never logged).

The proof *generators* below are transcriptions of the RFC's recursive definitions, which are slow
to run but easy to check against the document. The proof *verifiers* are the iterative form, which
is what a third party actually runs and which shares no code with the generators.
``tests/test_merkle.py`` brute-forces every proof for every tree size up to 33 in both directions,
so a mistake in either implementation cannot pass unnoticed by agreeing with itself.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

# RFC 6962 §2.1 domain separation. Fixed prefixes, never configurable: two logs that disagree
# here produce different roots for identical data, and every proof between them fails.
LEAF_PREFIX = b"\x00"
NODE_PREFIX = b"\x01"

#: The Merkle tree hash of the empty log, ``SHA-256("")``. Q-Vault's ledger always contains the
#: genesis entry, so this should never appear in practice; it is defined because the RFC defines
#: it and because a verifier handed ``tree_size = 0`` must have a defined answer rather than a
#: crash.
EMPTY_ROOT = hashlib.sha256(b"").digest()


def leaf_hash(data: bytes) -> bytes:
    """Hash one leaf's data: ``SHA-256(0x00 || data)``."""
    return hashlib.sha256(LEAF_PREFIX + data).digest()


def hash_children(left: bytes, right: bytes) -> bytes:
    """Hash an interior node: ``SHA-256(0x01 || left || right)``."""
    return hashlib.sha256(NODE_PREFIX + left + right).digest()


def _split(n: int) -> int:
    """The largest power of two strictly less than ``n`` (RFC 6962's ``k``, for ``n > 1``).

    This asymmetric split — rather than halving — is what makes the tree *history independent*:
    the root for the first ``m`` entries is a subtree of the root for ``n > m`` entries, so old
    proofs keep verifying as the log grows.
    """
    return 1 << ((n - 1).bit_length() - 1)


# --------------------------------------------------------------------------------------------
# Tree hash and proof generation — recursive transcriptions of RFC 6962 §2.1.
#
# Each takes the full leaf-hash list plus a [lo, hi) window rather than slicing, so recursion
# costs no copying; at 100k leaves the difference is the difference between comfortable and not.
# --------------------------------------------------------------------------------------------


def _root(leaves: Sequence[bytes], lo: int, hi: int) -> bytes:
    n = hi - lo
    if n == 0:
        return EMPTY_ROOT
    if n == 1:
        return leaves[lo]
    k = _split(n)
    return hash_children(_root(leaves, lo, lo + k), _root(leaves, lo + k, hi))


def merkle_root(leaves: Sequence[bytes]) -> bytes:
    """The Merkle Tree Hash over ``leaves`` (which are already leaf *hashes*)."""
    return _root(leaves, 0, len(leaves))


def _path(leaves: Sequence[bytes], lo: int, hi: int, m: int) -> list[bytes]:
    n = hi - lo
    if n == 1:
        return []
    k = _split(n)
    if m < k:
        return [*_path(leaves, lo, lo + k, m), _root(leaves, lo + k, hi)]
    return [*_path(leaves, lo + k, hi, m - k), _root(leaves, lo, lo + k)]


def inclusion_proof(leaves: Sequence[bytes], index: int) -> list[bytes]:
    """The audit path proving ``leaves[index]`` is in the tree of size ``len(leaves)``.

    Ordered leaf-upward, which is the order :func:`verify_inclusion` consumes it in.
    """
    n = len(leaves)
    if not 0 <= index < n:
        raise IndexError(f"leaf index {index} out of range for a tree of size {n}")
    return _path(leaves, 0, n, index)


def _subproof(leaves: Sequence[bytes], lo: int, hi: int, m: int, complete: bool) -> list[bytes]:
    """RFC 6962 ``SUBPROOF``. ``complete`` is the RFC's flag for "the old tree is exactly this
    subtree", in which case its root is already known to the verifier and is not transmitted."""
    n = hi - lo
    if m == n:
        return [] if complete else [_root(leaves, lo, hi)]
    k = _split(n)
    if m <= k:
        return [*_subproof(leaves, lo, lo + k, m, complete), _root(leaves, lo + k, hi)]
    return [*_subproof(leaves, lo + k, hi, m - k, False), _root(leaves, lo, lo + k)]


def consistency_proof(leaves: Sequence[bytes], old_size: int) -> list[bytes]:
    """Prove the tree of size ``old_size`` is a prefix of the tree over all of ``leaves``.

    This is the proof that the log was only ever appended to. A witness holding an old
    ``(size, root)`` and receiving a new one accepts it only if this proof checks out, which is
    what makes silently dropping or rewriting past entries detectable from outside the server.
    """
    n = len(leaves)
    if not 0 <= old_size <= n:
        raise ValueError(f"old_size {old_size} out of range for a tree of size {n}")
    if old_size == 0 or old_size == n:
        return []
    return _subproof(leaves, 0, n, old_size, True)


# --------------------------------------------------------------------------------------------
# Proof verification — the iterative form, and the only part a third party runs.
#
# These deliberately share nothing with the generators above: no helper, no traversal, no
# recursion. A verifier that reused the generator's structure would agree with it about a shared
# mistake, which is precisely the failure a verifier exists to rule out.
# --------------------------------------------------------------------------------------------


def verify_inclusion(
    *,
    leaf: bytes,
    index: int,
    tree_size: int,
    proof: Sequence[bytes],
    root: bytes,
) -> bool:
    """True if ``proof`` shows ``leaf`` sits at ``index`` in the tree of ``tree_size`` with ``root``.

    Note the final ``sn == 0``: it requires the proof to have exactly the right length. Without
    it a truncated proof could stop early on a partially-recomputed value that happened to match,
    so length is treated as part of the claim rather than as a hint.
    """
    if index < 0 or tree_size < 0 or index >= tree_size:
        return False

    # fn walks the leaf's index, sn the last index, both shifted up one level per step; the
    # invariant is that fn == sn exactly when we are on the rightmost (possibly incomplete) node.
    fn, sn = index, tree_size - 1
    computed = leaf
    for sibling in proof:
        if sn == 0:
            return False  # proof is longer than the tree is tall
        if (fn & 1) or (fn == sn):
            computed = hash_children(sibling, computed)
            while fn != 0 and (fn & 1) == 0:
                fn >>= 1
                sn >>= 1
        else:
            computed = hash_children(computed, sibling)
        fn >>= 1
        sn >>= 1
    return sn == 0 and computed == root


def _is_power_of_two(n: int) -> bool:
    return n > 0 and (n & (n - 1)) == 0


def verify_consistency(
    *,
    old_size: int,
    old_root: bytes,
    new_size: int,
    new_root: bytes,
    proof: Sequence[bytes],
) -> bool:
    """True if the log of ``new_size`` provably contains the log of ``old_size`` unchanged.

    A false return is the interesting case, and it has three distinct causes worth naming because
    each is a real attack: the log **shrank** (entries deleted), it **forked** (same size, different
    root — different histories shown to different people), or a past entry was **rewritten** (the
    prefix no longer recomputes).
    """
    if old_size < 0 or new_size < 0 or old_size > new_size:
        return False  # a log that shrank is never consistent, whatever proof accompanies it
    if old_size == new_size:
        return not proof and old_root == new_root
    if old_size == 0:
        return not proof  # every tree extends the empty tree

    if _is_power_of_two(old_size):
        # The old tree is a complete subtree of the new one, so the verifier already holds its
        # root; RFC 6962 omits it from the proof rather than sending it back.
        seed, rest = old_root, list(proof)
    else:
        if not proof:
            return False
        seed, rest = proof[0], list(proof[1:])
    if not rest:
        return False  # extending a tree always needs at least one node

    fn, sn = old_size - 1, new_size - 1
    while fn & 1:
        fn >>= 1
        sn >>= 1

    # One walk, two accumulators: the old root must fall out of the nodes on the old tree's right
    # edge, the new root out of all of them.
    old_computed = new_computed = seed
    for sibling in rest:
        if sn == 0:
            return False
        if (fn & 1) or (fn == sn):
            old_computed = hash_children(sibling, old_computed)
            new_computed = hash_children(sibling, new_computed)
            while fn != 0 and (fn & 1) == 0:
                fn >>= 1
                sn >>= 1
        else:
            new_computed = hash_children(new_computed, sibling)
        fn >>= 1
        sn >>= 1

    return sn == 0 and old_computed == old_root and new_computed == new_root
