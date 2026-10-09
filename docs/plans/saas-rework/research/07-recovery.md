# Research 07: how comparable products recover a key-holding account

Written 2026-10-09 for the R9 recovery design ([recovery-design.md](../recovery-design.md)). It
extends research 04 §8 with the facts the design leans on. **[D]** marks a documented fact read from
the vendor's own page on this date; **[I]** marks our inference. Nothing here is from memory alone.

| Product | Mechanism | What the design takes from it |
| --- | --- | --- |
| **1Password** | A 128-bit **Secret Key**, combined with the account password to make the key that encrypts everything; never sent to 1Password's servers; kept on signed-in devices and in the **Emergency Kit**. "We have no record of your Secret Key and can't recover it." [D] support.1password.com/secret-key-security/ . Team recovery is two halves: an admin begins it, the user completes it, the admin confirms; admins never see data. [D] support.1password.com/recovery/ (via 04 §8) | A printed kit with plain warnings; the vendor says what it cannot do. Recovery in a team is a two-party act. |
| **Bitwarden** | **Emergency access**: a trusted contact requests View or Takeover; access is granted when a wait time the account holder chose runs out, unless the holder rejects it first; email at each step. Takeover sets a new master password and removes two-step login methods. [D] bitwarden.com/help/emergency-access/ . Organisation **account recovery** encrypts the member's key to the organisation's public key. [D] bitwarden.com/help/account-recovery/ (via 04 §8) | The cancel window ("granted unless the holder rejects it in time"), and notification at every step. We reject the organisation-key escrow (design §11). |
| **Proton** | A 12-word **recovery phrase** resets the password and recovers data together. Resetting by email or SMS without it leaves "some of your account data … locked". [D] proton.me/support/recovery-phrase | Separate "get back in" from "get the keys back", and say which one a route does. |
| **Apple ADP** | Before Advanced Data Protection can be turned on, the user sets up at least one recovery contact or recovery key; "Apple will not have the encryption keys to help you recover it." [D] support.apple.com/en-us/102651 | Make the recovery method at set-up time, not after the loss. |
| **Safe** | Signers meeting the threshold replace a signer. RecoveryHub adds a recoverer with a delay (28 days by default) during which signers can cancel; Safe notes "there is no form of notification sent". [D] help.safe.global (via 04 §8) | Quorum replacement with a delay is the multisig-native answer; the missing notification is the cautionary example. |
| **Keybase** | Per-device keys plus paper keys; a new device is vouched for by an existing one; revoked devices stay visible as revoked. [D] book.keybase.io/account (via 04 §8) | Route (a2): an existing device vouches for the new web key. Retire-but-retain, which Q-Vault already does. |

**Synthesis [I].** Nobody serious offers an email reset that restores encrypted keys. Every product
that holds keys it cannot read offers some mix of: an offline artefact made at set-up (1Password,
Proton, Apple), an existing device vouching (Keybase, 1Password trusted devices), and other people
vouching after a delay (Bitwarden, Safe). Q-Vault's three routes are exactly that mix. The two
places we go further: the delay is cancellable by the account holder's existing credentials *and*
by the people who share the vault, and every step is in a witnessed log.
