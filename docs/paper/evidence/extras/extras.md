# Extra measurements (2026-11-18T16:52:16+00:00, commit 5752a11)

## Registry indirection

| alg | lookup (ns) | verify direct median/p95 (us) | via registry median/p95 (us) | lookup % of verify |
|---|---:|---:|---:|---:|
| ECDSA-P256 | 139.8 | 78.4 / 87.5 | 78.7 / 91.3 | 0.1783 |
| ML-DSA-65 | 144.1 | 622.1 / 699.0 | 623.1 / 701.1 | 0.0232 |
| ML-DSA-87 | 143.2 | 707.6 / 778.2 | 706.1 / 787.9 | 0.0202 |
| RSA-2048-PSS | 142.4 | 37.6 / 39.8 | 37.9 / 40.4 | 0.3786 |
| SLH-DSA-SHAKE-256f | 148.8 | 1768.2 / 2025.9 | 1771.2 / 2043.6 | 0.0084 |

## Merkle proofs

| log size | inclusion hashes (bytes) | inclusion verify median/p95 (us) | consistency hashes (bytes) | consistency verify median/p95 (us) |
|---:|---:|---:|---:|---:|
| 100 | 4-7 (224) | 5.4 / 5.5 | 8 (256) | 7.7 / 7.8 |
| 1,000 | 8-10 (320) | 7.5 / 7.7 | 11 (352) | 12.0 / 12.1 |
| 10,000 | 8-14 (448) | 10.3 / 10.6 | 15 (480) | 13.7 / 13.9 |
| 100,000 | 10-17 (544) | 12.9 / 24.0 | 18 (576) | 16.7 / 17.0 |
| 1,000,000 | 12-20 (640) | 14.6 / 15.1 | 21 (672) | 19.4 / 20.1 |
