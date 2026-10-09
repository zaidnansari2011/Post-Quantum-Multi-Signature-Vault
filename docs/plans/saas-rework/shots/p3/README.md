# P3 shots: Vaults, the treasury change, New decision and vault, Activity, Account, onboarding

Shot on 2026-10-09 by `mobile/tools/web-shots/p3.py` (390 x 844 at 2x) against a disposable backend
on a copy of the demo database. First screen only. `light_1` and `dark_1` hold every shot; `light_2`
and `dark_2` (emulated 2.0 text) hold the screens whose layout at large text is worth reviewing.
Every PNG is a 256-colour palette image, as P2's are (152 PNGs, 6.7 MB). The touch-target audit
(every target 48 x 48 or larger, none nested) ran on every shot: 729 targets in `light_1`, 781 in
`dark_1`, 164 in each of `light_2` and `dark_2`, 0 findings. The 2.0 sets are `o01`, `a10`, `a11`,
`v02`, `t02`, `t02b`, `n04`, `n06`, `nv03`, `ac01`, `acc02` and `d20`.

**How the states are made.** As in P2, a state is one real record whose reply is rewritten in the
browser, changing only UNSIGNED fields (status, votes, `can_sign`, `raised_by`, rule changes, a
member's key, the treasury change's state and seat), so the phone's own checks still pass. On
purpose: `t01` gives a treasury change a digest the phone does not derive, `d21` changes a typed
decision's level after the hash was taken, and `n10` changes the text of a decision on its way to
the server, so it stores something other than what was typed. The treasury change's digest in
every other state is computed by `qvault.chain.digest.reconfigure_digest`, so the phone's check
passes for real. A Production access decision is raised through the API for `d20`. Nothing is
signed or sent to the chain: approve sheets are opened and cancelled.

| Shot | phone-ux | What it shows |
| --- | --- | --- |
| `o01` to `o05` | §6.2 | Sign in; missing fields said under each; a wrong password under the password field; a 429 "Too many attempts. Try again in 9 minutes."; "Forgot password?" |
| `o06`, `o07` | §6.2 | This phone gets its own key; Key created with the fingerprint |
| `o08` | §6.2, I-9 | A phone with no screen lock is refused, with the way to set one |
| `o09` | §6.2, §6.22 | The first visit: "You're in Q-Vault. You approve in ..." |
| `a10` | §6.3, §6.15 | A treasury change in the queue, by when it runs out; the headline says "items", never calls it a decision |
| `a11`, `a11b` | §6.4 | Waiting on others: one you raised (who can still act, Remind beside the row), one that can't pass (the server's reason); the reminder sent |
| `a12`, `v06` | §6.22 | An auditor: no plus, no Create a vault |
| `v01` | §6.13 | Vaults: rule and your part, "1 needs you", Create a vault last |
| `v02` to `v05` | §6.14, §6.15 | Vault: the rule, your part, separation of duties, the latest rule change; Members (a member with no key), the treasury sheet with its change, History |
| `t01` to `t09` | §6.15 | The treasury change: tampered (no signing), needs you, its approve sheet and checks, the password key's seat, you approved, keys registering, applying, voided |
| `n01` to `n07` | §6.16 | New decision: no vault yet, the picker, what's missing, a payment (EIP-55 checked, the address in fours, the balance), its review, Production access, the discard sheet |
| `n09`, `n10` | §6.16, I-5 | Raised as entered; raised and stored differently, so the decision opens tampered and offers nothing to sign |
| `nv01` to `nv04` | §6.17 | New vault, the people sheet, a rule that could pass nothing under separation of duties, the review |
| `ac01` to `ac03` | §6.12 | Your decisions: sections, outcomes and your part; Decided; a search with no match |
| `acc01` to `acc09` | §6.18 | Account with the workspace role; This phone (app lock switch); Key details; Other devices; a device; removing it; Treasury approvals; Notifications (before R8); Help and about |
| `l01` | §6.1 | App lock: Q-Vault is locked (the prompt was cancelled) |
| `d20`, `d20b` | §6.21, S13 | A typed decision's card from the verified rows; the signed text one tap away |
| `d21` | §6.6 row 1 | A typed field changed after signing: refused as `type_text` |
| `d22`, `d22b` | §6.21 | The overflow with Withdraw; the withdraw sheet |
| `d23`, `d23b` | §6.6 row 3 | You raised it under separation of duties: Remind in the bar; the reminder sent |
| `d24`, `d25` | §6.21 | The discussion row; the thread (a mention, an address that is not a link, a deleted comment) |
| `d26` | R5 | Can't pass: the server's reason, no quorum sentence |
