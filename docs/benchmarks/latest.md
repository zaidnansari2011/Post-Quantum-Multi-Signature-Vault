# Q-Vault post-quantum benchmark

Generated 2026-09-12T17:43:05+00:00 · backend `quantcrypt` · CPython 3.13.5 on Windows 11 (AMD64, 12 logical CPUs).

Each figure is the median of up to 50 timed iterations after 3 warm-up rounds, signing 256-byte messages. Every measured operation was checked for correctness.

## Signature algorithms

| Algorithm | Standard | Cat. | Public key | Signature | Keygen (ms) | Sign (ms) | Verify (ms) | Verify/s |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `ECDSA-P256` | FIPS 186-5 - classical, NOT post-quantum | 0 | 91 B | 64 B | 0.045 | 0.104 | 0.094 | 10588 |
| `ML-DSA-65` | FIPS 204 | 3 | 1952 B | 3309 B | 0.969 | 1.734 | 0.629 | 1590 |
| `ML-DSA-87` | FIPS 204 | 5 | 2592 B | 4627 B | 0.921 | 2.017 | 1.107 | 903 |
| `RSA-2048-PSS` | FIPS 186-5 / RFC 8017 - classical, NOT post-quantum | 0 | 294 B | 256 B | 44.911 | 0.970 | 0.059 | 17050 |
| `SLH-DSA-SHAKE-256f` | SPHINCS+ round 3 (basis of FIPS 205; not interoperable with it) | 5 | 64 B | 49856 B | 2.898 | 47.962 | 3.031 | 330 |

## Key-encapsulation mechanisms

| Algorithm | Standard | Cat. | Public key | Ciphertext | Keygen (ms) | Encaps (ms) | Decaps (ms) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `ML-KEM-768` | FIPS 203 | 3 | 1184 B | 1088 B | 0.842 | 1.764 | 1.147 |
| `RSA-2048-OAEP` | RFC 8017 / SP 800-56B - classical, NOT post-quantum | 0 | 294 B | 256 B | 37.476 | 0.038 | 1.200 |

Sizes are measured from freshly generated keys and real signatures, not quoted from the specification, so they reflect exactly what this system stores.
