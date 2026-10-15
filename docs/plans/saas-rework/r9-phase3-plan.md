# R9 Phase 3 build plan: your approvers replace your key (route b)

**Status:** written 2026-10-15, before code. The owner deferred Phase 3 until after the live switch
(14 Oct); the switch is done, so it is built now. **Design:** [recovery-design.md](recovery-design.md)
§8 (route b), §4 (shared machinery), §9 (exports), §14 ⚑8 (the owner's rules), §15 (Phase 3 tests).
This file is the order of work and the choices the design left open; the design stays the authority.

**Branch:** `rework/r9-phase3` from `saas-rework` (after the black formatting commit), in worktree
`q-vault-r9k`. Alembic `0013_recovery_quorum` (new tables only). **Flag:** `RECOVERY_APPROVERS_ENABLED`,
default off in every environment; turning it on in live is the owner's call (OWNER-ACTIONS).

## What already exists (Phases 1 and 2)

`RecoveryRequest` with `route='quorum'` and the states `claimed`, `approving`, `waiting` (in the
one-open-request index); compare-and-set cancel and complete; password-proof cancels; transactional,
unarchivable notices to the person, managers and co-signers (in-app, email, push); the Home and
phone banners with Cancel; `'lost'` keys; the §7 treasury check; `credential_epochs`; the
`recover` rate-limit bucket; lineage in exports with the "approvers" label in `verify/core.py`.

## Order of work

1. **Data.** `recovery_vault_snapshots` (request, vault, M, N, signer ids as sorted JSON,
   `requester_can_approve` at start) and `recovery_decisions` (request, vault, proposal). Claim
   material on the request or a side table: link token hash (32 random bytes, domain-separated
   SHA-256, 24 h), claim-code tag (`master_key` tag with its own domain, like the phone code),
   tries (5). Migration test: new tables only, baseline untouched.
2. **Start** (`recovery_service.start_replacement`, web only: a manager's job, plan S26).
   On the person's member row, "Start a key replacement", behind the flag. Who: an owner or admin
   of a workspace whose vaults the person signs in, not the person; a co-signer only when the person
   is the only manager. Refuse, with one honest reason each, unless for every vault the person signs
   in: a signer other than the person and the starter exists; threshold and signer set unchanged
   in the last 72 h (ledger timestamps); the §7 treasury check passes. Refuse if the person signs
   in no vault, or has an open request. Snapshot each vault. State `started` (24 h to claim),
   `recovery_requested` {route: quorum, started_by}. The starter sees the link and an 8-character
   claim code once (kit alphabet), with "read the code aloud; never send it".
3. **Claim** (`/recover/claim/<token>`, unauthenticated, `recover` bucket, CSRF). Shows who
   started it; takes the claim code and a new password (same strength rules and wording as
   sign-up). Makes the pending ML-DSA-65 key and the request code (design §8.2). Five wrong codes
   end the request (`expired`, reason `wrong_codes`), each try committed before comparing.
   Logs `recovery_claimed`; state `approving` (7 days); §4.5 notices; raises the decisions.
4. **Decisions** (`recovery_service.raise_replacement`). One per vault, a new S13 type
   `key_replacement` ("Key replacement") whose text is generated from the snapshot and the claim
   (design §8.3, warning inside the signed text), in `decision_types.py` and its phone twin
   `mobile/src/logic/decisionTypes.ts` with shared vectors, so a phone writes the text again and
   refuses to sign a mismatch. Signers = snapshot minus the person; M' = min(M, N - 1); creator =
   the starter. Ordinary VOTE bytes; votable on web and phone; no new signed format. Not raisable
   from the ordinary "New decision" form.
5. **Progress.** Any decision rejected ends the request (`rejected`). All approved starts the 72 h
   `waiting` (`recovery_waiting` with proposal uuids). Any change to an affected vault's threshold
   or membership while open, including removing the person, cancels (hook in `vault_service`).
   The 7-day approving window expires the request and closes its open decisions.
6. **Completion** (scheduler `tick` and lazily on status). Re-checks design §4.2 and §8.3 per
   vault: decision still tallies approved (`approval_service.tally`, re-verifying votes and ledger
   binding); at least one counted approval from someone other than the starter; signed text equals
   the text regenerated from the snapshot and the `recovery_claimed` key hash; snapshot still
   matches the vault; the person signs in no vault outside the set; the treasury check. Then the
   new key becomes active, old password keys become `'lost'`, the kit is revoked (`lost`
   reason as Phase 2), epoch bumped, `recovery_completed`, notices.
7. **Cancel** from everyone design §4.2 names (the person's password proof and phones burn the
   kit as before; managers, co-signers and the starter do not), web and phone.
8. **Screens.** Web: start dialog on Members, starter's one-time link + code page, claim page,
   status page, banner wording for route b, the forgotten-password page's approvers line (only
   when the flag is on; "not built" text goes). Phone: the decision type renders and signs with
   its warning, banners show route b with Cancel (phone parity: the approver's jobs; starting stays
   on the web). Screenshots of each new screen, light and dark, into `shots/r9/phase3/`.
9. **Exports.** A replacement decision exports and verifies offline unchanged; a later vote with
   the new key prints the lineage line naming the approvers' decisions.
10. **Docs.** Design §18 "Phase 3 as built" (every silent choice, safer reading), plan R9 box and
    progress log row, OWNER-ACTIONS entry (turn the flag on in live; hand test with two teammates).

## Choices made here (the design was silent)

- **Separation-of-duties vaults (S15, `requester_can_approve = False`):** the starter is the
  decision's requester, so their approval is not counted there. The start check then requires M'
  approvers among the snapshot minus the person and the starter. Safer: the vault's own rule wins.
- **Vaults where M' = 1** (2-of-2, or 1-of-N): the one approval must be from a non-starter; the
  starter alone never completes, whatever the vault's rule.
- **The person's own votes** on the replacement are impossible: they are not a signer of it.
- **Flag off** hides every entry point and refuses the routes (404 on claim), and an open request
  made while it was on still runs to its end, so turning the flag off never strands one.

## Tests (named as sentences; time frozen)

All of design §15 Phase 3: a 2-of-2 vault whose other signer is the starter is refused; a 2-of-3
vault succeeds with starter and third signer; changing a threshold or removing the person while
open cancels; a vault changed 71 hours ago blocks the start; the starter's approval alone never
completes; renaming the person mid-request does not break completion; editing one vote's bytes
stops completion; a replacement decision exports and verifies offline. Plus: wrong claim codes
(5 ends it; tries counted side by side); expired link; flag off refuses; a kit use supersedes an
open quorum request; any password proof cancels and burns; a manager cancel keeps the kit; a
rejected decision ends it; a separation-of-duties vault needs a non-starter approval; a treasury
seat the person holds alone refuses the start; the phone twin matches the vectors; the claim code
and link token appear in no log, ledger payload or trace.

## Then

Full suite green, an independent adversarial security review (mandatory, as Phases 1 and 2), its
fixes with a regression test per attack, a re-review, merge `--no-ff` into `saas-rework`, full
suite, push. No deploy (Azure is paused; the flag would be off anyway).
