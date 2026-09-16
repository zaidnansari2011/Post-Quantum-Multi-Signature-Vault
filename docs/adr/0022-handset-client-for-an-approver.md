# ADR-0022 — The handset client is designed for an approver, not ported from a console

- **Status:** Accepted
- **Date:** 2026-09-17
- **Amends:** ADR-0014 (product, not demonstration) for the mobile surface. ADR-0016 and ADR-0017
  are untouched: no custody or signing behaviour changes here.

## Context

The Expo client built in Phase 2 was correct and unusable in the same breath.

Correct, because the security properties it exists to demonstrate were all present and all
enforced: the device recomputes `payload_hash` from the server's own stated inputs and refuses to
sign when they disagree, every signature is verified against this device's public key before it is
sent, and the signing seed never leaves `expo-secure-store`. None of that changes in this ADR, and
none of it was weakened to make room for what follows.

Unusable, because it was a console rendered at phone size. `src/theme.ts` opened by announcing
itself as "the Signal design system, ported from `qvault/static/qvault.css`", and the port was
faithful in exactly the wrong way — it carried across three habits that belong to an administrative
console and not to a phone:

- **Uppercase tracked micro-labels** on every field.
- **A monospace face for ordinary labels**, not just for values a reader compares.
- **Metadata joined with middle dots** — `ML-DSA-65 · 12 Mar, 14:02 · device key` — three facts
  wearing the costume of a sentence.

Those are, more or less exactly, the house style of a generated interface, and together they made
every screen read as an instrument readout.

The information architecture was worse than the typography. The decision screen gave the decision
itself — the sentence a person is being asked to put their name to — one paragraph inside a panel
titled "Action", and then gave a panel titled "Payload" equal billing, containing a verification
state, a payload hash, **a nonce**, a file digest, a creation timestamp and a signer count. An
executive has no nonce-shaped question. The list screen showed a title, a vault name and three
chips, none of which answered what someone triaging a queue actually asks: *how long have I got.*
`expires_at` had been on the wire since the API was written and the client never read it.

And the app was three screens on a flat stack, whose only route to the device screen was **a
sixteen-character key fingerprint printed in the footer of the approvals list**. A cryptographic
value was serving as a navigation affordance.

The prompt that forced this was the author's: *"the app should be made like its meant to be used by
a real executive who doesnt give a shit of the technical aspects he just needs to get shit done"*,
with the follow-up that it should support almost all of the product's functionality, *"but in a
proper way, no info dump"*.

## The tension, and how it resolves

Hiding the cryptography to serve the approver would delete the thing that makes this project worth
looking at. The on-device payload check *is* the thesis. If it is not visible, the guarantee is
indistinguishable from a claim.

But the old screen did not make the guarantee visible. It made it *loud*, which is a different
thing, and loudness applied uniformly is indistinguishable from noise. Six crypto rows at all times
do not tell a reader that the check passed; they tell a reader that this screen has a lot of
numbers on it.

**The decision: assurance is quiet when it holds and loud when it fails.**

- Holding: one line — a mark, four words, and a disclosure control. The detail is one tap away for
  the reader who wants it and absent for the reader who does not.
- Failing: the component opens, turns `broken`, **cannot be collapsed**, and the screen withdraws
  the signing controls entirely.

This is a better argument than the old screen made, not a concession. "The system verified this
before letting you sign, and it will stop you if it ever cannot" is a stronger sentence in a viva
than a printed nonce, and it is the sentence the interface now says.

`verifyProposalIntegrity` runs on every render of a loaded decision, exactly as before. Only its
presentation changed.

## Decision

**A quorum is drawn, not written.** An m-of-n vault is a document that is not valid until enough
people have sealed it; that is the literal mechanism and it is shown literally, as discrete marks
with the gathered ones filled. `2/3 approved` is a number a reader has to parse and convert. Three
marks with two filled is a state taken in without reading. Deliberately *not* a progress bar: a bar
implies a continuous quantity filling up, and a quorum is a small number of discrete,
individually-attributable consents. Above eight marks the row stops being countable at a glance and
falls back to a figure.

**One orchestrated moment, at the point of consequence.** When a signature completes the quorum the
final mark presses inward and a ring expands from it, with the heaviest haptic the product gives.
It fires only when *this person's* signature completed it — a decision already complete on arrival
did not happen in front of them, and animating it would claim it did. Everywhere else, motion only
answers something the person just did.

**Approving takes a restatement.** The old flow went from tap straight to the OS biometric prompt,
which says "Q-Vault wants to authenticate you" — a sentence about identity, not about the decision.
A sheet now restates the action **verbatim** before the prompt. Verbatim rather than summarised: a
summary is a second, unsigned description of the decision sitting beside the signed one, and the
moment the two disagree the confirmation is confirming the wrong sentence.

**Two typefaces with a job each.** Source Serif 4 sets the decision, because the decision is a
document. Public Sans sets the interface around it. The split is functional — it is how a reader
tells the thing being signed from the apparatus describing it. Monospace is restricted to hashes
and fingerprints, values a reader compares character by character, which is what makes it mean
something when it appears.

**The neutrals are cool and the ink is a navy** (`#16233A`), not a tinted near-black. The status
triad — `sealed` / `waiting` / `broken` — is carried over **unchanged**, because it is semantic
across the ledger, the record export and the console, and because "colour never decorates data"
survives the move intact. No brand accent exists, and no button is coloured to attract a tap.

**Elevation is spent twice** — the pinned action bar and the confirm sheet — and radius varies by
what a surface is. Uniform corners and one soft grey shadow on everything is what makes an
interface read as a card kit rather than a designed thing.

**Tabs replace the flat stack.** Approvals, Activity, Account. The decision screen is pushed *above*
the tabs rather than living inside one: it is reachable from two places and it is modal in intent,
and a tab bar under someone mid-signature is an invitation to wander off.

**Time is relative and urgency is banded.** `expires_at` is finally read. The queue sorts by
deadline rather than recency, because a queue sorted by when things were raised makes the person
find the urgent item themselves — work the screen should be doing. Bands are coarse on purpose: a
countdown to the minute implies a precision the expiry sweep does not have, since it runs on a
scheduler rather than on the clock tick.

**Activity exists at all.** `GET /proposals?state=all` has been supported since the API was written
and no screen ever called it, so the app had no answer to "what did I approve last quarter" — a
question that arrives from an auditor, from a colleague, or from one's own memory failing in a
meeting. An approval client that cannot answer it is a notification tray.

## Consequences

**A new binary is required, once.** `react-native-reanimated`, `react-native-gesture-handler` and
`expo-haptics` are native modules, and `@expo/vector-icons` added `expo-font` to `plugins`.
Per the rule in OWNER-ACTIONS §2.3 and ADR-0018, `runtimeVersion` goes to **`"2"`**. That bump is
not bookkeeping — it is what stops the new bundle being offered to the 20 Aug APK, which has none
of that native code and would crash on launch, in a loop no further update could rescue. After this
build, every subsequent change here is JavaScript and ships over the air.

**Bundle discipline had to be enforced by hand.** Importing the font families from their package
roots pulled **34 `.ttf` files** into the build — every weight in roman and italic — because Metro
bundles any asset it can see a `require` for and the barrel re-exports all of them. Importing each
weight from its own subpath brings it to six. That is roughly 2MB, and it is 2MB in every
over-the-air update as well as in the APK. The same applies to `@expo/vector-icons`: the package
root drags in all nine icon families, and `@expo/vector-icons/Feather` does not.

**Three screens were deleted**, not migrated: `InboxScreen`, `ProposalScreen` and `DeviceScreen`
became `HomeScreen`, `DecisionScreen` and `AccountScreen`. The old component vocabulary
(`Header`, `Body`, `Panel`, `Meta`) went with them.

**What this ADR does not do.** Vaults, raising a decision, the audit ledger, the record export and
account management are all still web-only, because the device API exposes eight endpoints and none
of them cover those surfaces. Bringing them across is API work first and screen work second, and it
is deliberately not bundled into a change whose subject is the interface. The tab bar has room for
a fourth entry when it lands.

**A limitation worth stating plainly:** a proposal is a `title` and a free-text `action_text`, with
no structured amount or counterparty. So the queue cannot lead with what a decision is *worth*,
which is the first thing a real approver would want. Fixing that is a schema change that reaches
the canonical signing payload — the one surface in this project that cannot be altered casually —
and it is recorded here as the next honest step rather than faked with parsing.
