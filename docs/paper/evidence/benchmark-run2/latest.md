# Q-Vault post-quantum benchmark

Generated 2026-11-18T16:54:10+00:00 · backend `quantcrypt` · CPython 3.13.5 on Windows 11 (AMD64, 12 logical CPUs).

Each figure is the median of up to 500 timed iterations after 3 warm-up rounds, signing 256-byte messages. Every measured operation was checked for correctness.

## Signature algorithms

| Algorithm | Standard | Cat. | Public key | Signature | Keygen (ms) | Sign (ms) | Verify (ms) | Verify/s |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `ECDSA-P256` | FIPS 186-5 - classical, NOT post-quantum | 0 | 91 B | 64 B | 0.028 | 0.059 | 0.078 | 12870 |
| `ML-DSA-65` | FIPS 204 | 3 | 1952 B | 3309 B | 0.778 | 1.425 | 0.611 | 1636 |
| `ML-DSA-87` | FIPS 204 | 5 | 2592 B | 4627 B | 0.835 | 1.536 | 0.706 | 1416 |
| `RSA-2048-PSS` | FIPS 186-5 / RFC 8017 - classical, NOT post-quantum | 0 | 294 B | 256 B | 33.976 | 0.882 | 0.038 | 26178 |
| `SLH-DSA-SHAKE-256f` | SPHINCS+ round 3 (basis of FIPS 205; not interoperable with it) | 5 | 64 B | 49856 B | 2.686 | 40.312 | 1.755 | 570 |

## Key-encapsulation mechanisms

| Algorithm | Standard | Cat. | Public key | Ciphertext | Keygen (ms) | Encaps (ms) | Decaps (ms) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `ML-KEM-768` | FIPS 203 | 3 | 1184 B | 1088 B | 0.665 | 1.036 | 0.739 |
| `RSA-2048-OAEP` | RFC 8017 / SP 800-56B - classical, NOT post-quantum | 0 | 294 B | 256 B | 33.331 | 0.037 | 0.876 |

Sizes are measured from freshly generated keys and real signatures, not quoted from the specification, so they reflect exactly what this system stores.
