# P2 step 1: Approvals, Waiting on others, the decision screen in every state

Shot by `mobile/tools/web-shots/states.py` (web harness, 390 x 844 at 2x) against a disposable
backend on a copy of the demo database. Each decision state is one real decision whose reply is
rewritten in the browser: only UNSIGNED fields change (status, deadline, votes, counts, `can_sign`,
payout, the treasury seat, the planned A1/R5 fields), so the phone's own integrity check still
passes. The `d01*` tampered states change a signed field on purpose and must show the failure.

Folders: `light_1`, `dark_1` (font scale 1.0), `light_2`, `dark_2` (emulated 2.0). `*_full.png` is
the whole scrolled page; kept for `light_1` and `dark_2` only, to keep the folder small.
`audit.json` in each folder is the touch-target audit (every target 48 x 48 or larger, none nested):
0 findings in all four.

| Shot | phone-ux | What it shows |
| --- | --- | --- |
| `a01` | §6.3 | Queue, "Approve on the web" group with the one-time fix, Waiting on others row |
| `a02` | §6.3 | A payment this phone's key holds stays in the main group, with its amount |
| `a03` | §6.3 | Nothing needs your signature, with the waiting-on-others line |
| `a04` | §6.3 | Only web-only payments: "Nothing needs your signature here." |
| `a05`, `a06` | §6.3 | Load failed (never "nothing needs you"), first load |
| `a07` | §6.4 | Waiting on others |
| `a08` | §6.3 | Removed from the workspace |
| `d01a` to `d01c` | §6.6 row 1 | Tampered: hash, display text, display rule; no signing at all |
| `d02*` | row 2 | Needs your signature (general, long text, payment); evidence sheet, Details, overflow |
| `d03` to `d08` | rows 3 to 8 | Raised it (separation of duties), approved, rejected, not an approver, treasury holds another key, signer set and server disagree |
| `d09` to `d15` | rows 9 to 15 | Approved, queued, submitting, paid (with evidence), failed, voided, rejected, expired, withdrawn (opened from Activity) |
| `d16` | row 16 | Closed while you were away (opened from the queue) |
| `d17` | row 17 | Unknown decision type: the signed text alone |
| `d18` | §5.4 | Unknown server status: "Unknown", nothing to sign, never the raw word |
| `d19` | §6.5 item 8 | Four voters with both custodies and two rejection reasons (more than four collapse to three plus "See all"; not shot) |
| `e01` to `e03` | §2.4, §6.6 | Decision gone (404), load failed, loading |
