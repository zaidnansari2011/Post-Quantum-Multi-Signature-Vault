"""Expand an ML-DSA-65 public key into the form ``ZKNOX_dilithium65`` reads on-chain.

A FIPS 204 public key is ``rho (32 B) || t1 (6 x 320 B)``. Verifying against it directly would
make every on-chain verification run ExpandA (30 polynomials of SHAKE128 rejection sampling) and
six NTTs, which is most of the cost. ZKNox's verifier instead reads a precomputed key:

* ``A_hat[i][j] = RejNTTPoly(rho || j || i)``, the matrix already in the NTT domain (FIPS 204
  Alg. 32/30),
* ``t1_hat[i] = NTT(t1[i] * 2^13)``, the other factor of FIPS 204 Alg. 8 step 9,
* ``tr = SHAKE256(pk, 64)``,

each polynomial packed eight coefficients to a 256-bit word, low coefficient in the low bits.
At 36,864 bytes the expanded key exceeds EIP-170's contract size limit, so it is stored as two
halves (rows 0-2 and 3-5, each carrying ``tr``) of exactly 20,160 bytes.

This is a port of ``js/mldsa65.js`` at the pinned ETHDILITHIUM commit. Three checks keep it
honest: a reference vector produced by that JS and FIPS 204's own zeta table (both in
``tests/test_chain_primitives.py``), and — the one that matters — Foundry verifying a quantcrypt
signature against a key expanded by this module (``chain/test/QVaultTreasury.t.sol``).

**Expansion is not verification.** Nothing here checks a signature, and a wrong blob fails
closed: the contract simply rejects every signature made by the real key.
"""

from __future__ import annotations

import hashlib

from eth_abi import encode

Q = 8_380_417
N = 256
D = 13
K = 6  # rows of A (ML-DSA-65)
L = 5  # columns of A (ML-DSA-65)
RHO_BYTES = 32
T1_POLY_BYTES = 320  # 256 coefficients x 10 bits
PUBLIC_KEY_BYTES = RHO_BYTES + K * T1_POLY_BYTES  # 1952
TR_BYTES = 64
HALF_BYTES = 20_160
BLOB_BYTES = 2 * HALF_BYTES
_ZETA = 1753  # primitive 512th root of unity mod q (FIPS 204 section 7.5)


def _bitrev8(m: int) -> int:
    return int(f"{m:08b}"[::-1], 2)


# zetas[k] = zeta^brv8(k) mod q. tests/test_chain_primitives.py pins entries against FIPS 204.
ZETAS = tuple(pow(_ZETA, _bitrev8(k), Q) for k in range(N))


def _ntt(coefficients: list[int]) -> list[int]:
    """FIPS 204 Algorithm 41, coefficients in [0, q)."""
    w = [c % Q for c in coefficients]
    m = 0
    length = 128
    while length >= 1:
        for start in range(0, N, 2 * length):
            m += 1
            zeta = ZETAS[m]
            for j in range(start, start + length):
                t = zeta * w[j + length] % Q
                w[j + length] = (w[j] - t) % Q
                w[j] = (w[j] + t) % Q
        length //= 2
    return w


def _rej_ntt_poly(rho: bytes, i: int, j: int) -> list[int]:
    """FIPS 204 Algorithm 30 for ``A_hat[i][j]``: seed ``rho || j || i``, SHAKE128, 3-byte draws.

    hashlib's SHAKE is not streaming, but ``digest(n)`` is always a prefix of the same stream, so
    asking for more bytes on the rare exhaustion reproduces an incremental reader exactly.
    """
    xof = hashlib.shake_128(rho + bytes((j, i)))
    out: list[int] = []
    size = 840  # 280 draws; each is accepted with probability q / 2^23 ~ 0.999
    offset = 0
    stream = xof.digest(size)
    while len(out) < N:
        if offset + 3 > len(stream):
            size *= 2
            stream = xof.digest(size)
        t = int.from_bytes(stream[offset : offset + 3], "little") & 0x7F_FFFF
        offset += 3
        if t < Q:
            out.append(t)
    return out


def _decode_t1(public_key: bytes) -> list[list[int]]:
    """FIPS 204 pkDecode for ``t1``: six polynomials of 10-bit little-endian coefficients."""
    polys = []
    for i in range(K):
        start = RHO_BYTES + i * T1_POLY_BYTES
        packed = int.from_bytes(public_key[start : start + T1_POLY_BYTES], "little")
        polys.append([(packed >> (10 * c)) & 0x3FF for c in range(N)])
    return polys


def _pack(coefficients: list[int]) -> list[int]:
    """Eight 32-bit fields per word: coefficient ``8w + f`` sits at bit ``32 f`` of word ``w``."""
    words = [0] * (N // 8)
    for index, c in enumerate(coefficients):
        words[index // 8] |= c << (32 * (index % 8))
    return words


def _check_length(public_key: bytes) -> None:
    if len(public_key) != PUBLIC_KEY_BYTES:
        raise ValueError(
            f"an ML-DSA-65 public key is {PUBLIC_KEY_BYTES} bytes, got {len(public_key)}"
        )


def tr_of(public_key: bytes) -> bytes:
    """``tr = SHAKE256(pk, 64)`` (FIPS 204 Alg. 8 step 6), the value every verification hashes."""
    _check_length(public_key)
    return hashlib.shake_256(public_key).digest(TR_BYTES)


def expand_public_key(public_key: bytes) -> tuple[list, list, bytes]:
    """Return ``(a_hat, t1_hat, tr)``: packed 6x5x32 words, packed 6x32 words, 64 bytes."""
    _check_length(public_key)
    rho = public_key[:RHO_BYTES]
    a_hat = [[_pack(_rej_ntt_poly(rho, i, j)) for j in range(L)] for i in range(K)]
    t1_hat = [_pack(_ntt([(c << D) % Q for c in poly])) for poly in _decode_t1(public_key)]
    return a_hat, t1_hat, tr_of(public_key)


def _half(a_rows: list, tr: bytes, t1_rows: list) -> bytes:
    half = encode(
        ["bytes", "bytes", "bytes"],
        [encode(["uint256[][][]"], [a_rows]), tr, encode(["uint256[][]"], [t1_rows])],
    )
    if len(half) != HALF_BYTES:  # pragma: no cover - fixed shapes; guards a future edit
        raise AssertionError(f"key half is {len(half)} bytes, expected {HALF_BYTES}")
    return half


def onchain_key_blob(public_key: bytes) -> bytes:
    """The ``setKey`` argument for ``public_key``: ``half0 || half1``, 40,320 bytes."""
    a_hat, t1_hat, tr = expand_public_key(public_key)
    return _half(a_hat[0:3], tr, t1_hat[0:3]) + _half(a_hat[3:6], tr, t1_hat[3:6])


def key_halves(blob: bytes) -> tuple[bytes, bytes]:
    """Split a blob into the two SSTORE2 payloads the verifier writes, for read-back checks."""
    if len(blob) != BLOB_BYTES:
        raise ValueError(f"a key blob is {BLOB_BYTES} bytes, got {len(blob)}")
    return blob[:HALF_BYTES], blob[HALF_BYTES:]


def pointer_code(half: bytes) -> bytes:
    """The runtime code SSTORE2 deploys for one half: a STOP byte, then the data.

    The leading ``0x00`` makes the pointer contract halt if anyone calls it. It is also exactly
    what ``eth_getCode`` returns, which is how a registration is checked by reading it back.
    """
    return b"\x00" + half


def pointer_codehashes(blob: bytes) -> tuple[bytes, bytes]:
    """``(codehash0, codehash1)``: what each key pointer's ``EXTCODEHASH`` must be (plan D17)."""
    from qvault.chain.evm import keccak256

    first, second = key_halves(blob)
    return keccak256(pointer_code(first)), keccak256(pointer_code(second))
