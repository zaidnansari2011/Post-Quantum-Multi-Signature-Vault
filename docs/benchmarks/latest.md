# Q-Vault post-quantum benchmark

Generated 2026-08-04T15:42:55+00:00 · backend `quantcrypt` · CPython 3.13.5 on Windows 11 (AMD64, 12 logical CPUs).

Each figure is the median of up to 50 timed iterations after 5 warm-up rounds, signing 256-byte messages. Every measured operation was checked for correctness.

## Signature algorithms

| Algorithm | Standard | Cat. | Public key | Signature | Keygen (ms) | Sign (ms) | Verify (ms) | Verify/s |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `ML-DSA-65` | FIPS 204 | 3 | 1952 B | 3309 B | 0.754 | 1.714 | 0.627 | 1596 |
| `ML-DSA-87` | FIPS 204 | 5 | 2592 B | 4627 B | 0.811 | 1.603 | 0.716 | 1398 |
| `SLH-DSA-SHAKE-256f` | FIPS 205 | 5 | 64 B | 49856 B | 2.503 | 38.657 | 1.768 | 566 |

## Key-encapsulation mechanisms

| Algorithm | Standard | Cat. | Public key | Ciphertext | Keygen (ms) | Encaps (ms) | Decaps (ms) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `ML-KEM-768` | FIPS 203 | 3 | 1184 B | 1088 B | 0.636 | 1.017 | 0.734 |

Sizes are measured from freshly generated keys and real signatures, not quoted from the specification, so they reflect exactly what this system stores.
