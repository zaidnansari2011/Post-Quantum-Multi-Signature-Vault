"""RFC 6962 Merkle tree: proofs, verification, and the attacks they exist to stop.

These tests carry more weight than most in this project, because the Merkle code is the one piece
whose output is consumed by software we do not control. A signature that fails to verify is a
visible outage; a *proof system that accepts a false proof* is silent, and every downstream claim
about the log rests on it.

So the strategy here is deliberate redundancy in three layers:

1. A **third implementation** of the tree hash, :func:`reference_root`, written bottom-up from the
   binary decomposition of ``n`` rather than by the RFC's top-down recursion. It shares no code
   and no traversal order with the module under test, so the two agreeing is evidence, not an
   echo. (The generators and verifiers in ``merkle.py`` are already independent of each other.)
2. **Exhaustive** rather than sampled coverage: every leaf of every tree size up to 33, and every
   ``(old, new)`` size pair in the same range. 33 crosses two powers of two, which is where the
   incomplete-right-subtree cases live and where an off-by-one in ``_split`` would hide.
3. **Negative** cases for each proof type — a proof that is not checked for length, or that
   ignores the claimed index, still passes every positive test ever written for it.
"""

from __future__ import annotations

import hashlib

import pytest

from qvault.transparency.merkle import (
    EMPTY_ROOT,
    consistency_proof,
    hash_children,
    inclusion_proof,
    leaf_hash,
    merkle_root,
    verify_consistency,
    verify_inclusion,
)

MAX_N = 33  # crosses 16 and 32, so incomplete right subtrees are covered at two scales


def leaves_for(n: int) -> list[bytes]:
    return [leaf_hash(f"entry-{i}".encode()) for i in range(n)]


# --------------------------------------------------------------------------------------------
# An independent tree hash, used as the oracle for everything below.
# --------------------------------------------------------------------------------------------


def _complete_root(chunk: list[bytes]) -> bytes:
    """Root of a complete subtree (length a power of two), folded bottom-up in pairs."""
    level = list(chunk)
    while len(level) > 1:
        level = [hash_children(level[i], level[i + 1]) for i in range(0, len(level), 2)]
    return level[0]


def reference_root(leaves: list[bytes]) -> bytes:
    """RFC 6962's tree hash, derived the other way round.

    A tree of size ``n`` decomposes into complete subtrees whose sizes are the set bits of ``n``,
    largest first, because the RFC always takes the largest power of two below ``n`` as the *left*
    subtree. The root is then those peaks folded right-to-left. Nothing here recurses, and the
    leaves are visited in a different order from the module's version.
    """
    n = len(leaves)
    if n == 0:
        return EMPTY_ROOT
    peaks, i = [], 0
    for bit in range(n.bit_length() - 1, -1, -1):
        size = 1 << bit
        if n & size:
            peaks.append(_complete_root(leaves[i : i + size]))
            i += size
    root = peaks[-1]
    for peak in reversed(peaks[:-1]):
        root = hash_children(peak, root)
    return root


@pytest.mark.parametrize("n", range(1, MAX_N + 1))
def test_tree_hash_matches_an_independently_derived_root(n):
    assert merkle_root(leaves_for(n)) == reference_root(leaves_for(n))


def test_the_empty_tree_is_the_hash_of_nothing():
    assert merkle_root([]) == EMPTY_ROOT == hashlib.sha256(b"").digest()


def test_a_one_leaf_tree_is_its_leaf():
    """RFC 6962: MTH({d0}) is the leaf hash itself, with no interior node wrapped round it."""
    leaves = leaves_for(1)
    assert merkle_root(leaves) == leaves[0]


# --------------------------------------------------------------------------------------------
# Domain separation — the reason for the 0x00 / 0x01 prefixes.
# --------------------------------------------------------------------------------------------


def test_a_node_preimage_cannot_be_passed_off_as_a_leaf():
    """The second-preimage attack the RFC's prefixes exist to prevent.

    Without domain separation, an interior node is ``H(left || right)`` and a leaf is ``H(data)``,
    so an attacker can take the concatenation of two real leaf hashes, call it "one leaf", and
    prove membership of data that was never in the log. With the prefixes the two hash spaces are
    disjoint, and this test pins that: the forged leaf must not collide with the real root.
    """
    a, b = leaf_hash(b"a"), leaf_hash(b"b")
    real_root = merkle_root([a, b])
    forged_leaf = leaf_hash(a + b)  # "the log has one entry, whose data happens to be a||b"
    assert forged_leaf != real_root
    assert hash_children(a, b) == real_root


def test_leaf_and_node_hashes_of_the_same_bytes_differ():
    assert leaf_hash(b"") != hash_children(b"", b"")


# --------------------------------------------------------------------------------------------
# Inclusion proofs — exhaustive.
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("n", range(1, MAX_N + 1))
def test_every_leaf_of_every_tree_proves_inclusion(n):
    leaves = leaves_for(n)
    root = merkle_root(leaves)
    for i in range(n):
        proof = inclusion_proof(leaves, i)
        assert verify_inclusion(
            leaf=leaves[i], index=i, tree_size=n, proof=proof, root=root
        ), f"leaf {i} of {n} failed"


@pytest.mark.parametrize("n", range(1, MAX_N + 1))
def test_inclusion_proofs_are_logarithmic(n):
    """The size claim the whole export format depends on."""
    leaves = leaves_for(n)
    ceil_log2 = (n - 1).bit_length()
    for i in range(n):
        assert len(inclusion_proof(leaves, i)) <= ceil_log2


def test_a_leaf_that_is_not_in_the_log_does_not_verify():
    leaves = leaves_for(16)
    root = merkle_root(leaves)
    proof = inclusion_proof(leaves, 5)
    assert not verify_inclusion(
        leaf=leaf_hash(b"never logged"), index=5, tree_size=16, proof=proof, root=root
    )


def test_a_valid_proof_does_not_verify_at_a_different_index():
    """The index is part of the claim, not a lookup hint — it decides the hashing order."""
    leaves = leaves_for(16)
    root = merkle_root(leaves)
    proof = inclusion_proof(leaves, 5)
    assert not verify_inclusion(leaf=leaves[5], index=6, tree_size=16, proof=proof, root=root)


@pytest.mark.parametrize("mutation", ["truncate", "extend", "corrupt", "reorder"])
def test_a_tampered_inclusion_proof_is_rejected(mutation):
    leaves = leaves_for(21)
    root = merkle_root(leaves)
    proof = inclusion_proof(leaves, 9)
    assert verify_inclusion(leaf=leaves[9], index=9, tree_size=21, proof=proof, root=root)

    if mutation == "truncate":
        bad = proof[:-1]
    elif mutation == "extend":
        bad = [*proof, leaf_hash(b"extra")]
    elif mutation == "corrupt":
        flipped = bytes([proof[0][0] ^ 0x01]) + proof[0][1:]
        bad = [flipped, *proof[1:]]
    else:
        bad = list(reversed(proof))

    assert not verify_inclusion(leaf=leaves[9], index=9, tree_size=21, proof=bad, root=root)


def test_a_proof_of_the_wrong_length_for_the_claimed_size_is_rejected():
    """A tree size that changes the *shape* of the path is caught, because the walk runs out."""
    leaves = leaves_for(21)
    root = merkle_root(leaves)
    proof = inclusion_proof(leaves, 9)
    assert not verify_inclusion(leaf=leaves[9], index=9, tree_size=16, proof=proof, root=root)
    assert not verify_inclusion(leaf=leaves[9], index=9, tree_size=9, proof=proof, root=root)


def test_tree_size_is_only_pinned_up_to_the_shape_of_the_path():
    """A documented property of RFC 6962, recorded here so nobody later mistakes it for a bug.

    An inclusion proof pins the **root** exactly, but the **size** only as far as the left/right
    decisions it induces. Leaf 9 sits in the same position in the tree shape for sizes 20, 21, 22
    and 32 alike, so one proof verifies against all of them. Nothing is forged by this: the root
    still has to match, and the root is what commits to the content.

    It matters only if a verifier lets an attacker choose ``tree_size`` and ``root`` separately.
    Q-Vault never does — both are read from the same signed checkpoint, so they stand or fall
    together under one signature. This test exists to make that dependency explicit rather than
    incidental: if a future change ever sourced the size from anywhere else, this is the property
    that would be silently relied upon.
    """
    leaves = leaves_for(21)
    root = merkle_root(leaves)
    proof = inclusion_proof(leaves, 9)
    for claimed in (20, 21, 22, 32):
        assert verify_inclusion(
            leaf=leaves[9], index=9, tree_size=claimed, proof=proof, root=root
        ), f"size {claimed} shares the path shape of 21"

    # But the true root of a genuinely different log does not match, which is the check that
    # actually carries the weight.
    assert merkle_root(leaves_for(20)) != root


def test_an_out_of_range_index_is_rejected_rather_than_crashing():
    leaves = leaves_for(8)
    root = merkle_root(leaves)
    assert not verify_inclusion(leaf=leaves[0], index=8, tree_size=8, proof=[], root=root)
    assert not verify_inclusion(leaf=leaves[0], index=-1, tree_size=8, proof=[], root=root)
    with pytest.raises(IndexError):
        inclusion_proof(leaves, 8)


# --------------------------------------------------------------------------------------------
# Consistency proofs — exhaustive over every (old, new) pair.
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("new_size", range(1, MAX_N + 1))
def test_every_prefix_of_every_tree_proves_consistency(new_size):
    leaves = leaves_for(new_size)
    new_root = merkle_root(leaves)
    for old_size in range(1, new_size + 1):
        old_root = merkle_root(leaves[:old_size])
        proof = consistency_proof(leaves, old_size)
        assert verify_consistency(
            old_size=old_size,
            old_root=old_root,
            new_size=new_size,
            new_root=new_root,
            proof=proof,
        ), f"{old_size} -> {new_size} failed"


def test_consistency_with_itself_needs_no_proof():
    leaves = leaves_for(12)
    root = merkle_root(leaves)
    assert consistency_proof(leaves, 12) == []
    assert verify_consistency(
        old_size=12, old_root=root, new_size=12, new_root=root, proof=[]
    )


def test_a_log_that_shrank_is_never_consistent():
    """Truncation — the attack ADR-0005 recorded as undetectable without an external witness.

    No proof can rescue it, so the check is on the sizes themselves before any hashing happens.
    """
    leaves = leaves_for(20)
    big_root = merkle_root(leaves)
    small_root = merkle_root(leaves[:10])
    proof = consistency_proof(leaves, 10)
    assert not verify_consistency(
        old_size=20, old_root=big_root, new_size=10, new_root=small_root, proof=proof
    )


def test_a_fork_at_the_same_size_is_rejected():
    """Two different histories of equal length — the split-view attack, where a log shows one
    story to a signer and another to an auditor."""
    a = leaves_for(9)
    b = leaves_for(9)
    b[4] = leaf_hash(b"a different entry 4")
    assert not verify_consistency(
        old_size=9,
        old_root=merkle_root(a),
        new_size=9,
        new_root=merkle_root(b),
        proof=[],
    )


def test_a_rewritten_prefix_breaks_consistency():
    """The consistent forward-rewrite: history edited, then every hash recomputed. The chain is
    satisfied by it; the consistency proof against a previously-witnessed root is not."""
    original = leaves_for(24)
    old_root = merkle_root(original[:10])

    rewritten = list(original)
    rewritten[3] = leaf_hash(b"entry-3 as the operator wishes it had been")
    new_root = merkle_root(rewritten)
    proof = consistency_proof(rewritten, 10)

    assert not verify_consistency(
        old_size=10, old_root=old_root, new_size=24, new_root=new_root, proof=proof
    )


@pytest.mark.parametrize("old_size", [8, 10])  # a power of two, and not one: different proof shapes
def test_a_tampered_consistency_proof_is_rejected(old_size):
    leaves = leaves_for(26)
    old_root, new_root = merkle_root(leaves[:old_size]), merkle_root(leaves)
    proof = consistency_proof(leaves, old_size)

    def check(p):
        return verify_consistency(
            old_size=old_size, old_root=old_root, new_size=26, new_root=new_root, proof=p
        )

    assert check(proof)
    assert not check(proof[:-1])
    assert not check([*proof, leaf_hash(b"extra")])
    assert not check([bytes([proof[0][0] ^ 0xFF]) + proof[0][1:], *proof[1:]])
    assert not check([])


def test_the_empty_proof_only_extends_the_empty_tree():
    leaves = leaves_for(7)
    root = merkle_root(leaves)
    assert verify_consistency(
        old_size=0, old_root=EMPTY_ROOT, new_size=7, new_root=root, proof=[]
    )
    assert not verify_consistency(
        old_size=3,
        old_root=merkle_root(leaves[:3]),
        new_size=7,
        new_root=root,
        proof=[],
    )


def test_consistency_proof_rejects_an_out_of_range_size():
    leaves = leaves_for(5)
    with pytest.raises(ValueError):
        consistency_proof(leaves, 6)
