# Actions that need you

A running list of the things I **cannot** do for you, kept so nothing falls through the cracks
while I work. Everything not on this list, I do myself.

Something lands here only if it needs one of:

- **your judgement** — a decision that is yours to make as the project's author,
- **your identity** — an account, credential, signature or submission that is legally or
  practically yours,
- **your eyes** — a subjective check (does this *look* right?) that I cannot make for you,
- **your hardware or presence** — something that must happen on a specific machine, or in a room.

For each item I record what I have already prepared, so your part is as small as possible.

**Status:** `TODO` · `DONE` · `N/A` (decided against)

---

## 1. Decisions that are yours

### 1.1 Choose a licence — `TODO`

The repository is **public** and currently has **no LICENSE file**. Without one, default copyright
applies: nobody may legally reuse the code, which is probably not what you intend for a portfolio
piece, and some examiners read a missing licence as an oversight.

*Why it's yours:* a licence is a legal declaration by the author. I should not make it on your behalf.

*What I've prepared:* my recommendation is **MIT** — permissive, one paragraph, universally
understood, and the norm for student portfolio work. If you would rather nobody built a product on
it, **AGPL-3.0** is the opposite pole. Tell me which and I'll add the file with correct attribution.

*Your effort:* one word.

### 1.2 Confirm the public-repo posture — `TODO`

The repo is public. That's good for a portfolio, but it means the tamper demo, the threat model and
every honest limitation in the ADRs are visible to anyone — including your examiners, which I
consider a feature, not a risk.

*Why it's yours:* it's your name on it.

*What I've prepared — secret audit, run 2026-08-04, result: **clean**.* Across all **10 commits**
in the repository's history:

- No `.env`, `*.db`, `*.sqlite`, `*.key`, `*.pem`, `instance/` or `storage/` file has **ever** been
  added, in any commit — not just absent from the current tree.
- The only secret-shaped string literals anywhere in history are the deliberate test and
  development placeholders in `config.py`: `SECRET_KEY = "test-secret-key"` (test config only) and
  `_DEV_SECRET = "dev-insecure-secret-key-change-me"`, which is named to be unmistakable. `TestConfig`
  uses `SERVER_MASTER_KEY = "0" * 64`, an obviously fake value.
- Real secrets are read from the environment, and `ProdConfig` refuses to start without them —
  so there is no path by which a deploy silently runs on a default.

Re-run it yourself any time with:

```bash
git log --all --pretty=format: --name-only --diff-filter=A | sort -u | grep -E "\.env$|\.db$|\.key$|\.pem$|instance/"
```

*Your effort:* decide public vs. private. My view: keep it public — the honesty of the ADRs is an
asset, and there is nothing in here to leak.

### 1.3 Repository presentation — `TODO`

The repo has **no description and no topics**, so on GitHub it reads as an unlabelled code dump.

*Why it's yours:* it's your public profile, and how you'd describe your own work is a judgement call.

*What I've prepared:* copy-paste ready —

> **Description:** Crypto-agile post-quantum multi-signature vault — M-of-N approvals signed with
> ML-DSA/SLH-DSA, a hash-chained audit ledger with a PQC-signed head anchor, and automated
> retire-but-retain key rotation. Flask + FIPS 203/204/205.
>
> **Topics:** `post-quantum-cryptography` `ml-dsa` `ml-kem` `slh-dsa` `fips-204` `crypto-agility`
> `multi-signature` `audit-log` `tamper-evident` `flask` `final-year-project`

*Your effort:* two paste operations, or say the word and I'll set them via `gh`.

---

## 2. Things needing your accounts or identity

### 2.1 Azure hosting — `TODO`

You have decided to host on Azure using ~$100 of student credit, so the demonstration runs against
a deployed instance rather than `localhost`, and your four team members can approve from their own
phones.

*Why it's yours:* it is your subscription, your billing, and your credential.

*What this changes about the project's story.* Until now this section read "no cloud, no vendor" and
treated that as part of the security argument. Be precise about what is and is not affected: the
**security argument is unchanged** — the cryptography, the hash chain, the SYSTEM anchor and the
offline verifier all still work on a stranger's laptop with no network and no Azure. What changes is
only *where the process runs*. Say it that way in the viva rather than dropping the point.

*What it buys you, in order of value:*

1. **A genuinely independent witness.** Today the witness is a second process on the same laptop,
   under the same operator — an examiner can fairly say that is not independence. On separate Azure
   infrastructure the claim in [ADR-0015](adr/0015-transparency-log-and-witness.md) becomes real.
   This is the highest-value use of the credit and the witness is tiny.
2. **Four people, four phones, one decision.** The thing the mobile client exists to demonstrate.
3. Not depending on venue Wi-Fi. University networks commonly isolate clients, which would silently
   break a laptop-as-server demo in the room.

*What I need from you before deploying:* the subscription, and a decision on region.

> **Critical, and easy to get wrong:** if the existing database is migrated to Azure, the **same
> `SERVER_MASTER_KEY` must go with it**. That key wraps the SYSTEM ledger-anchor key and every
> vault's ML-KEM key. With a different one, the instance can never anchor the ledger again and
> cannot decrypt a single attached file — and it will look like data corruption rather than a
> configuration mistake. `SECRET_KEY` may be regenerated freely (it only invalidates sessions).

### 2.2 Database backup before deployment — `DONE` (2026-08-20)

Taken before the device-key work began: `instance/qvault.db.bak-2026-08-20` (via `sqlite3.backup()`,
**not** `cp` — the WAL held 4.1 MB against a 602 KB main file, so a plain copy loses most of it),
plus `instance/storage.bak-2026-08-20/` for the 733 encrypted blobs no DB backup covers.

Verified readable: 7 users, 30 proposals, 135 ledger entries, 49 signatures, chain intact.

> **Do not run `scripts/seed_demo.py --reset` on this database.** It calls `db.drop_all()`
> unconditionally and mints a new SYSTEM key, which makes the existing witness reject the whole log
> as `key_changed`. To add your team members, register them as new users on the existing database.

If I later propose anything else that needs an account, it appears here **before** I build against
it, never after.

---

### 2.3 Build the mobile APK and switch on OTA updates — `TODO` (steps 1-3 `DONE` 2026-08-20)

The app is configured and frozen-ready; what remains needs an **Expo account**, which is yours.
Do these **in order** — step 3 must happen before step 5, or the APK ships with updates disabled.

1. **Create or confirm an account** at expo.dev. The free plan includes EAS Update. If it is an
   organisation rather than a personal account, tell me — `app.json` then also needs
   `"owner": "<org-slug>"`.

2. `cd q-vault/mobile && npx eas login`

3. ~~`npx eas init`~~ — **done.** Project `@zaid7864/qvault`, id
   `abfa50c5-38c5-4fd7-a01d-7c0d0dd9c028`. It wrote `extra.eas.projectId` and `owner`, and left
   `runtimeVersion: "1"` alone. I then set `updates.url`, which `eas init` does not do.

   Verified in a real prebuild: `expo.modules.updates.ENABLED` now reads **`true`** (it read
   `false` before the URL was set), `EXPO_UPDATE_URL` carries the project URL, and
   `expo_runtime_version` resolves to `1`. The APK will be updatable.

4. **Android keystore.** The first build offers to generate one — accept, then back it up with
   `npx eas credentials`. **This keystore is the app's identity for its lifetime.** A different one
   means a different signature, Android refuses to upgrade over the installed APK, and the enrolled
   signing seed inside becomes unreachable.

5. **Cut the build:** `npx eas build -p android --profile preview` → an installable `.apk`.

6. **Test on a real handset** (biometrics cannot be validated on an emulator): enrol → fingerprint
   prompt appears → approve a decision → decline the prompt and confirm nothing is signed → confirm
   the PIN fallback works.

7. **Prove OTA works before relying on it.** Change one visible string in `src/`, then
   `npx eas update --branch preview --message "smoke test"`. Force-close and reopen the app twice —
   the first launch downloads, the second runs it.

*Why it's yours:* an account, a signing credential, and a physical device.

*What I've prepared:* everything else — `eas.json` with a `preview` profile that emits an APK,
`app.json` with a static `runtimeVersion`, `expo-updates` installed and wired, and the permission
set trimmed to `INTERNET`, `USE_BIOMETRIC`, `USE_FINGERPRINT`, `VIBRATE`.

**The rule that keeps OTA working:** bump `runtimeVersion` in `app.json` whenever a native module
or any `plugins`/`android`/`ios`/`icon`/`scheme` value changes — and only then. JavaScript, assets
and `extra` never need it. ADR-0018 explains why this is a hand-maintained string rather than the
fingerprint policy.

**`runtimeVersion` is now `"2"` (2026-09-17).** The handset redesign (ADR-0022) added three native
modules — `react-native-reanimated`, `react-native-gesture-handler`, `expo-haptics` — and
`@expo/vector-icons` appended `expo-font` to `plugins`. That is exactly the case the rule is for.
The bump is what stops the new bundle being offered to the 20 Aug APK, which contains none of that
native code and would crash on launch, in a loop no further update could rescue. **Everything after
this build is JavaScript and ships over the air** — layout, copy, colour, motion, and any screen
built against an endpoint that already exists.

**Superseded on the rework (R8, 2026-10-09):** the rework adds `expo-notifications` at runtime
`rework-1`. It reaches phones only with the rework APK, and that build needs the Firebase file first
(§2.12, one command). The working branch's runtime-2 APK is unchanged. The original decision
follows.

**Decided against:** `expo-notifications`. Android push needs `google-services.json` compiled into
the binary, so adding push later forces a new APK *even if* the module is already bundled —
including it now buys nothing and puts `POST_NOTIFICATIONS` on a signing app's manifest for a
feature that does not exist. If you want "a decision is waiting", `refetchInterval` on the inbox
query does it with zero native surface and ships over the air.

### 2.7 Create the Azure deploy credential for CI — `TODO` (added 2026-09-17) — **one command**

Releasing has been manual since the first deployment, and the evidence that this does not work is
that on 2026-09-17 production was serving commit `5cb611c` while `main` was six commits ahead: the
decision-package export, the transparency-log work and the entire adversary lab were built, tested
and never shipped. `.github/workflows/deploy.yml` now closes that — it waits for a green CI run on
the same commit, then points the Container App at the freshly built image — but it needs one
credential that only you can mint.

*Why it's yours:* it creates a service principal under your subscription and stores a secret on
your GitHub account. Both are your identity, and neither should be held by anyone else.

**Step 1 — mint a scoped service principal.** Scoped to the resource group, not the subscription,
so a leaked credential cannot touch anything outside `qvault-rg`:

```bash
az ad sp create-for-rbac \
  --name "qvault-github-deploy" \
  --role contributor \
  --scopes /subscriptions/$(az account show --query id -o tsv)/resourceGroups/qvault-rg \
  --sdk-auth
```

It prints a JSON object exactly once. Copy the whole thing, braces included.

**Step 2 — store it as a repository secret** named `AZURE_CREDENTIALS`:

```bash
gh secret set AZURE_CREDENTIALS --repo zaidnansari2011/Post-Quantum-Multi-Signature-Vault
```

Paste the JSON when prompted, then press Ctrl+Z and Enter on Windows (Ctrl+D elsewhere). Or use
GitHub → Settings → Secrets and variables → Actions → New repository secret.

**Step 3 — prove it works** without waiting for a merge. Run the workflow by hand against a commit
already built and in GHCR:

```bash
gh workflow run deploy.yml -f sha=<the commit sha>
gh run watch
```

A green run means merged-to-main now means deployed, and §2.4's manual `az containerapp update`
stops being something anybody has to remember.

*What I've prepared:* the workflow, the CI gate that refuses to deploy a commit whose tests did not
pass, and the health check that waits for the new revision to actually reach `Running` rather than
reporting success the moment Azure accepts the request.

*One thing to know:* the credential expires. `create-for-rbac` issues a one-year secret by default,
so this will need redoing around September 2027 — the failure mode is a red deploy job with an
authentication error, not a silent one.

### 2.4 Post-demo: turn the demo-day Azure spend back down — `TODO` (added 2026-08-20)

*Why it's yours:* it costs money, and only you can decide when the demo is over.

Two changes were made on 2026-08-20 to de-risk the 2026-08-21 demo, and both cost
a little per day until reverted:

1. **`qvault` min-replicas 0 -> 1.** Removes the ~40 s cold start on the first
   click. Revert with:

   ```
   az containerapp update -n qvault -g qvault-rg --min-replicas 0
   ```

2. **A witness is now deployed** as a second Container App, `qvault-witness`,
   running the *same image* with a command override (`python -m witness`). Its
   state and keypair live on an Azure Files share so its identity survives a
   restart -- `qvaultwitness260820` / share `witness-data`, mounted with
   `nobrl` because SQLite cannot take byte-range locks over SMB.

   `WITNESS_URL`, `WITNESS_TIMEOUT_S=15` and `WITNESS_SYNC_SECONDS=60` are set
   on `qvault`. Keep this if you want exports to carry a co-signature; it is
   what turns the last verifier check from NOT-APPLICABLE into PASS.

   To tear it down entirely:

   ```
   az containerapp delete -n qvault-witness -g qvault-rg --yes
   az containerapp env storage remove -n qvault-env -g qvault-rg --storage-name witnessfiles --yes
   az storage account delete -n qvaultwitness260820 -g qvault-rg --yes
   az containerapp update -n qvault -g qvault-rg --remove-env-vars WITNESS_URL WITNESS_TIMEOUT_S WITNESS_SYNC_SECONDS
   ```

*Your effort:* one command if you keep the witness, four if you do not.

### 2.6 Attachment uploads are lost on every restart — `TODO` (added 2026-08-25) — **demo-blocking**

*Why it's yours:* it needs an Azure storage key and changes the running deployment.

**The symptom.** Downloading any vault attachment on the deployed app returns
*Internal Server Error*. Confirmed from the live container log:

```
FileNotFoundError: [Errno 2] No such file or directory:
  '/app/instance/storage/11/055a983e-8cf1-430f-bbc9-c5f0b8a292d0.bin'
```

**The cause.** `qvault` has **no volumes and no volume mounts** — verified with
`az containerapp show`. So `/app/instance/storage/` is the container's own
ephemeral filesystem, and every uploaded file is destroyed on restart, redeploy,
scale event or revision change. The database rows survive independently (a
`DATABASE_URL` is configured, pointing outside the container), which is why the
UI still lists an attachment whose bytes are gone. That mismatch is the whole
bug: the row promises a file that no longer exists.

This affects **every** upload, not just one. Uploading a file during the demo and
downloading it minutes later will work; anything uploaded before the last
restart will not.

**The fix — mount Azure Files at the storage path.** Reusing the storage account
the witness already uses, with a new share:

```
# 1. a share for vault attachments
az storage share-rm create --storage-account qvaultwitness260820     -g qvault-rg -n vault-files --quota 5

# 2. register it with the Container Apps environment
#    (get KEY from: az storage account keys list -n qvaultwitness260820 -g qvault-rg)
az containerapp env storage set -n qvault-env -g qvault-rg     --storage-name vaultfiles     --azure-file-account-name qvaultwitness260820     --azure-file-account-key "<KEY>"     --azure-file-share-name vault-files     --access-mode ReadWrite

# 3. attach it. Volumes need YAML - there are no CLI flags for this.
az containerapp show -n qvault -g qvault-rg -o yaml > qvault.yaml
```

In `qvault.yaml`, under `properties.template` add:

```yaml
    volumes:
      - name: vault-storage
        storageType: AzureFile
        storageName: vaultfiles
```

and under `properties.template.containers[0]` add:

```yaml
      volumeMounts:
        - volumeName: vault-storage
          mountPath: /app/instance/storage
```

then:

```
az containerapp update -n qvault -g qvault-rg --yaml qvault.yaml
```

**Mount only `/app/instance/storage`, not `/app/instance`.** The witness share
needs `nobrl` because SQLite cannot take byte-range locks over SMB (§2.4).
Mounting just the storage subdirectory keeps any SQLite file off the share
entirely, so `nobrl` is not needed here — the share holds only opaque AES-GCM
blobs, written once with `write_bytes()` and read with `read_bytes()`, never
locked.

**Two things this does not do:**

1. **Files already uploaded are gone for good.** Encrypted bytes that were never
   persisted cannot be recovered from the database row. Re-upload anything you
   need *after* the mount is live — including `csl_iat1.pdf`.
2. **The friendlier error needs a redeploy.** The code now raises
   `CiphertextMissing` and shows "this attachment's encrypted data is missing
   from server storage" instead of crashing, but the deployed image predates
   that fix and will keep returning 500 until a new image ships.

*Your effort:* three commands, one small YAML edit, then re-upload your files.

### 2.5 Publish the key fingerprints — `PARTLY DONE` (2026-08-21; values renewed 2026-10-04)

*Why it's yours:* a fingerprint is only worth anything if it reaches the reader through a channel
the log does not control. Me writing it into the repo the log ships from is exactly the circularity
it exists to break — so the last step has to be you, in public, in advance.

Both values, read from the running witness on 2026-10-04 (its own key, and the log key it has
pinned for origin `project4.zaidansari.tech/team-ledger`):

| | | |
| --- | --- | --- |
| **The log** | `78afee3014ee9c09` | ML-DSA-65, signs every checkpoint |
| **The witness** | `810fb51e5e2f75a8` | ML-DSA-87, `witness-1`, separate process and key |

Retired logs (§2.9): `project4.zaidansari.tech/ledger` with log `6e4025ccb44f44c4`
(2026-09-27 to 2026-10-04), and before it `qvault-azure-demo` with log `951dbf99653347de` and
witness `c79ad5683b2e9109`. The witness kept its key through the 2026-10-04 restart.

Each is `SHA-256(public key)` truncated to 16 hex characters — the same rule as
`Key.public_fingerprint()`, so a value shown on a phone, on the website and in an export can be
compared by eye.

*What I've done:* published both on the **Q-Vault Crypto Inventory** page
(<https://claude.ai/artifact/Xo12wyizGRiDudEG2cqX2E>), which is hosted on claude.ai rather than
served by Q-Vault, so it is a channel independent of the thing it vouches for. Updated to the new
values on 2026-10-04, with a note naming the retired ones. **The page is private until you share
it** (its Share menu, "anyone with the link"); until then it publishes nothing to anyone else.

*What's still yours, and it is the part that carries the argument:* **put the witness fingerprint
on a slide, or write it on the board, before the demo starts.** Then when the verifier reports *the
witness key is the one you expected*, you can point at a value that was visible before the file was
opened. A fingerprint produced after the fact proves nothing; one committed to in advance is
evidence. Thirty seconds of work, and it is the difference between demonstrating the mechanism and
demonstrating the property.

To use either:

```
python -m qvault.verify decision-xxxxxxxx.qvault.html --expect-witness 810fb51e5e2f75a8
```

or paste it into the offline record's **Pin the keys you were told to expect** field. A correct
value adds a passing check; a wrong one turns the verdict red.

*Your effort:* one line on a slide.

### 2.8 On-chain execution on Sepolia — `LIVE` (added 2026-09-17; on in production 2026-10-04)

Approved Treasury decisions will pay out on Sepolia through a contract that checks the M-of-N
ML-DSA-65 signatures itself. Before building anything, a local Foundry test confirmed that
quantcrypt's signatures verify on ZKNox's Solidity verifier (10 of 10 checks passed). **The build
follows [docs/plans/onchain-execution.md](plans/onchain-execution.md); review it first,
especially the two decisions marked ⚑.**

*Why it's yours:* the faucet request is made under your login, the payout address is your wallet,
and the API keys belong to your accounts.

| Item | Status |
| --- | --- |
| Etherscan API key | `DONE`, stored in `.env` as `ETHERSCAN_API_KEY` |
| Alchemy RPC endpoint | `DONE`, stored in `.env` as `SEPOLIA_RPC_URL`; confirmed it answers as chain 11155111 |
| Address to receive demo payouts | `DONE`, `0xF590cEe84F86510555150F13Ca83AEc613f1676b`: valid, but no Sepolia history as of 2026-09-17, so confirm it matches the account MetaMask shows |
| Fund the relayer wallet | `PARTLY DONE`, 0.05 ETH arrived 2026-09-17, enough for setup; another 0.05 from the faucet on a later day pays for demo payouts |
| Using ZKNox's unaudited verifier on testnet | Assumed accepted with the go-ahead on 2026-09-17 |
| Fork ETHDILITHIUM to your GitHub account | `DONE`, 2026-09-17: [zaidnansari2011/ETHDILITHIUM](https://github.com/zaidnansari2011/ETHDILITHIUM), with tag `qvault-pin-4c370bb` on the pinned commit; the submodule now points at the fork |
| Phase 5: say which approver uses the phone ([plan Q2](plans/onchain-execution.md#open-questions)) | `TODO`, see *Link the demo Treasury vault* below |
| Phase 5: give the link access to the Azure database (plan Q3) | `TODO`, see below |
| Phase 5: approve the broadcast that links the Treasury vault (~0.028 ETH) | `TODO`, after reading the dry run |
| Approve the first broadcast to Sepolia (Phase 3: helper + verifier) | `DONE`, approved 2026-09-17; verifier deployed and source-verified at [`0x31a85de8CB44BC89c53487A69d20b3DC3dB7487C`](https://sepolia.etherscan.io/address/0x31a85de8CB44BC89c53487A69d20b3DC3dB7487C#code), cost 0.0109 ETH (relayer now holds ~0.039) |

**Approve the Phase 3 deployment.** On 2026-09-17 the session's permission system blocked the
first real broadcast. That is the right default for something that spends ETH and publishes to a
public chain, so it was not worked around. Everything around it is ready:

- the dry run with the relayer as sender succeeded: helper at `0x8fB7DC8733139924C7b8D12A296F2ff3c0f87ac4`, verifier at `0x31a85de8CB44BC89c53487A69d20b3DC3dB7487C`, 12.95M gas, ~0.014 ETH at the 1.07 gwei base fee then;
- `scripts/record_deployment.py` and `scripts/check_verifier_live.py` are written and tested. Both are read-only.

Either say *"go ahead with the Sepolia deployment"* in a session, or run it yourself from
`q-vault/chain` in PowerShell (this loads `.env` into the current shell only, and prints nothing
from it):

```powershell
Get-Content ..\.env | ForEach-Object { if ($_ -match '^\s*([A-Z_]+)\s*=\s*(.+?)\s*$') { Set-Item "env:$($Matches[1])" $Matches[2].Trim('"') } }
forge script script/DeployVerifier.s.sol --rpc-url $env:SEPOLIA_RPC_URL --private-key $env:EXECUTOR_PRIVATE_KEY --broadcast --slow --verify --etherscan-api-key $env:ETHERSCAN_API_KEY
```

If forge fails, its error text can include the RPC URL, which contains the Alchemy key, so don't
paste forge errors anywhere public.

After that, recording it and the live check need no approval. Recording waits for the blocks to
be finalized, about 13 minutes after the broadcast; before then it says so and writes nothing:
`..\.venv\Scripts\python ..\scripts\record_deployment.py`, then `..\.venv\Scripts\python ..\scripts\check_verifier_live.py`.

**Fund the relayer.** Send Sepolia ETH to **`0x3cbC1F33F6ad04B3305dbdf26F6a3b0eC98854c2`**. This
wallet was generated for Q-Vault, and its key is in `.env` as `EXECUTOR_PRIVATE_KEY`. It pays gas
and submits payouts that have already been approved. It cannot approve anything or change a
payment, because the recipient and amount are covered by the approvers' post-quantum signatures.

Costs below use measured gas, priced at the 1.12 gwei Sepolia fee on 2026-09-17:

| | Gas | ETH |
| --- | --- | --- |
| One-off setup (verifier, signer keys, treasury) | ~37M | ~0.042 |
| Each payout | ~3.3M | ~0.004, plus the amount paid |

**Send at least 0.1 ETH; 0.2 leaves room for fee spikes.** Faucets give a small amount per day, so
this may take more than one request.

**Fork ETHDILITHIUM.** The contracts pin ZKNox's verifier at commit `4c370bb`. That commit is
the tip of an unmerged branch (`mldsa-65`), so if ZKNox rebase or delete that branch, the commit
can disappear from GitHub, and CI plus every fresh clone would then fail to fetch it. A fork under
your account keeps the pinned commit reachable permanently. It's a public repository under your
name, which is why it's your call. If you say yes, I'll run the fork and point the submodule at it:

```bash
gh repo fork ZKNoxHQ/ETHDILITHIUM --clone=false
```

*One thing to know:* the relayer key exists only in the gitignored `.env` on this laptop. Losing
that file loses the testnet ETH in the wallet and nothing else. When the relayer moves to Azure,
the key becomes a Container App secret, which will be a separate step here.

*Also:* the Etherscan and Alchemy keys were pasted into a chat session. They're testnet-only, but
regenerate both before sharing the repository or any logs widely.

**Link the demo Treasury vault (Phase 5).** Built and tested; nothing has been spent. Linking
registers each approver's post-quantum key on chain and deploys the vault's own treasury contract.
Three things are yours:

1. **Which approver signs on the phone in the demo** (plan Q2). The contract counts keys, not
   people, so each approver gets exactly one key on the treasury: their password key, or their
   phone key. The phone approver's phone must already be enrolled on
   <https://project4.zaidansari.tech>: a phone key enrolled after linking (including after
   reinstalling the app) cannot approve payments until the treasury is linked again, which costs
   ~0.03 ETH.
2. **Access to the Azure database** (plan Q3). The link must read and write the database the demo
   runs on, not the local copy. It needs that database's `DATABASE_URL`, and the Postgres
   firewall must admit this laptop. Either run the commands below yourself, or say how you want to
   hand the session the URL. It is never written into the repository.
3. **Approve the broadcast.** A dry run against the local copy on 2026-09-17 said: three keys at
   ~8.78M gas each and a treasury at ~2.68M, about 0.028 ETH at 0.97 gwei, leaving ~0.011 ETH in
   the relayer. The 0.05 ETH top-up gives room if fees rise first.

From `q-vault` in PowerShell (the relayer settings come from `.env`; `DATABASE_URL` set here wins
over the local one, for this window only):

```powershell
$env:DATABASE_URL = "postgresql+psycopg://..."   # the Azure database
.venv\Scripts\python scripts\link_treasury.py --vault <id> --by <admin email> --device <phone approver's email>
# read the plan it prints: the Database line, the vault, each approver's key, the cost. If right:
.venv\Scripts\python scripts\link_treasury.py --vault <id> --by <admin email> --device <phone approver's email> --broadcast
Remove-Item Env:DATABASE_URL
```

The broadcast waits about 13 minutes for finality before it writes anything. If it is interrupted,
run the same command again: nothing already on chain is paid for twice. At the end it records the
treasury in `chain/deployments/sepolia.json` and prints the command that verifies its source on
Etherscan.

---

### 2.9 The deployment on the team Azure subscription — `LIVE` (added 2026-09-27)

Your own Azure credits ran low, so on 2026-09-27 everything was rebuilt from scratch on a
teammate's **Azure for Students** subscription (`4e995e2f…`, directory "Default Directory"),
signed in on this laptop with `az login --tenant 4ca17099-4223-438c-9f8a-91b2c0954037`. Your own
subscription (`88f39ece…`) was not touched. Everything lives in **one resource group, `rg-qvault`,
Central India** (the student plan allows only five regions), so deleting that group removes all of
it.

| Resource | Name | Notes |
| --- | --- | --- |
| Container Apps environment | `qvault-env` | workload-profiles mode (the CLI's new "express" default cannot mount file shares) |
| App | `qvault` | 0.5 vCPU / 1 GiB, **one always-on replica** (the scheduler lives in it), image from GHCR |
| Witness | `qvault-witness` | same image, `python -m witness`, scales to zero |
| Postgres | `qvault-pg-260927` | Burstable B1ms, 32 GB, v16, database `qvault`; firewall: Azure services only |
| Storage | `qvault260927st` | shares `witness-data` (mounted `nobrl`) and `vault-files` (attachments at `/app/instance/storage` — the §2.6 fix, so uploads now survive restarts) |
| Job | `qvault-seed` | re-runs `scripts/seed_demo.py` inside Azure; nothing opens the database to the internet |

**Domain:** `project4.zaidansari.tech` was kept, so every installed phone keeps working with no
app update. Cloudflare records (DNS only, grey cloud): `CNAME project4 →
qvault.livelybeach-69506dc5.centralindia.azurecontainerapps.io` and `TXT asuid.project4 →
97845A9A…910A`. HTTPS is Azure's free managed certificate.

**The team's own accounts since 2026-10-04.** At your request the database was wiped and restarted
with only the four of you, for testing: Zaid Ansari (`zaid@gmail.com`, administrator), Hassaan
Shaikh (`hassan@gmail.com`), Gracian Lopes (`gracian@gmail.com`) and Atharva Tike
(`atharv@gmail.com`), all signers on **Team vault** (2 of 4, owned by Zaid). The passwords are the
simple ones you chose; they are deliberately not written in this public repository. Anyone who
guesses one can sign as that person, so change them at `/account` before anything that matters.
Done with `scripts/reset_to_team.py`, run once as the `qvault-seed` job (its command was then put
back to the harmless default, which refuses a database with users). The log restarted under a new
origin, `project4.zaidansari.tech/team-ledger`, so the witness accepted it without losing its key;
new log fingerprint **`78afee3014ee9c09`** (§2.5). The demo personas, the 27 September history and
`ada@qvault.demo` are gone from the live site; the laptop's database still has them.

History of this database, for the record:

- **2026-09-27, a fresh start, not a migration:** demo data re-seeded (7 users, 6 vaults, 30
  decisions, ledger 133 entries), log `6e4025ccb44f44c4`. Your team's August accounts were in the
  old database on your own subscription and were not carried over; they still are there unless that
  database has been deleted.
- **Phones must enrol again:** devices and tokens belong to the database they were enrolled on.
- **On-chain treasuries are on** since 2026-10-04 (your call: switched on before the handset test,
  web and password keys only). The relayer key and the RPC endpoint are Container App secrets
  (`executor-private-key`, `sepolia-rpc-url`); `/admin/chain` reads *Funded*. The Treasury vault
  (#1) is linked to [`0x5788ccACAdCe9F3A0447B6fBFe009D8A6c821461`](https://sepolia.etherscan.io/address/0x5788ccACAdCe9F3A0447B6fBFe009D8A6c821461), 2 of 3,
  Ada, Brij and Chen on their password keys; deployment tx `0xb9a31b24…`, block 11,842,630. Linking
  cost 0.0307 ETH. Funded with 0.01 ETH from the relayer (your OK), then **a test payout ran end to
  end** the same day: Ada raised 0.001 ETH to `0xF590…676b`, Ada and Brij approved, and the app
  paid it in [`0x5afb834b…0548`](https://sepolia.etherscan.io/tx/0x5afb834ba468f717b4213af88dba951c8905c4d43c03ba31e5df82d753f70548)
  (block 11,842,867, 3,273,463 gas, 0.00344 ETH). Before the team restart its remaining 0.009 ETH
  was paid back to the relayer (net +0.0056 ETH after gas) and the treasury was **unlinked** (its
  approvers' keys went with the wipe); relayer now ~0.165 ETH. The older treasury `0xD491…f3D0`
  lives in the laptop's demo database.
- **Team vault has no treasury yet.** Creating one is the owner's button on its Treasury tab
  (~0.04 ETH for four keys). Decide first which of you sign from a phone: each approver's seat is
  the key they have chosen when it is created, and changing a seat later is a reconfiguration
  (~0.009 ETH per new key plus ~0.004).

**Yours to do:**

1. **Back up the new `SERVER_MASTER_KEY`** into a password manager. Without it the vault files and
   the log's SYSTEM key can never be unwrapped. It is a Container App secret on `qvault`; on
   2026-10-04 I checked that the scratchpad copy on this laptop is byte-identical to it, but that
   folder is temporary. Either line puts the key on your clipboard without showing it; paste it
   into the password manager, then copy something else:

   ```powershell
   # from the scratchpad copy (while it still exists)
   Get-Content "$env:LOCALAPPDATA\Temp\claude\c--Users-Zaid-Documents-4th-year-project\3b36b092-d14a-4e4c-813d-1b3b0df3710d\scratchpad\azure\master_key" | Set-Clipboard
   # or straight from Azure
   az containerapp secret show -n qvault -g rg-qvault --subscription 4e995e2f-5117-441f-97d2-149256d6215b --secret-name server-master-key --query value -o tsv | Set-Clipboard
   ```
2. **Your teammate:** they own the billing. The standing cost is roughly the Postgres server plus
   one always-on 0.5 vCPU replica (~$15–20/month). Ask them to glance at their credit monthly.
3. **Your old deployment** (`qvault-rg` on your own subscription `88f39ece…`): the container is
   stopped, but a Postgres server there still bills while it exists. Your subscription is no
   longer signed in on this laptop, and I do not touch it, so this one is yours. **It is the only
   copy of the team's August accounts, keys and decisions, and of the `qvault-azure-demo` log.**
   The live site no longer needs them, but export it first (`pg_dump`) if the dissertation might
   cite that history; to stop paying without losing it, `az postgres flexible-server stop` instead.
   To delete, either remove only the database server:

   ```powershell
   az login                      # your own account, then:
   az account set --subscription 88f39ece-...   # your full subscription id
   az postgres flexible-server list -g qvault-rg --query "[].name" -o tsv
   az postgres flexible-server delete -g qvault-rg -n <the name it printed> --yes
   ```

   or remove the whole old deployment (stopped app, old witness, storage, database) in one go with
   `az group delete -n qvault-rg --yes`. Nothing live uses it.
4. ~~Republish the two fingerprints above (§2.5).~~ `DONE` 2026-10-04 on the Crypto Inventory
   page; what is left is sharing that page and putting the witness value on a slide (§2.5).

**Found while deploying:** `scripts/seed_demo.py` deadlocked on Postgres (its own open transaction
held a lock `drop_all` waited on — SQLite never shows it), and the image workflow did not rebuild
when only `scripts/` changed, though the image ships `scripts/`. Both fixed (`68a4ab7`, `6923a39`).

### 2.10 Pin the live witness key when the rework goes live — `TODO` (added 2026-10-08)

*Why it's yours:* it is a setting on the live deployment, and the value has to be one you checked
against the witness yourself, not one I wrote into the repo the log ships from (§2.5).

From the SaaS rework on (owner decision 2026-10-08), Q-Vault can pin the witness key with
`WITNESS_KEY_FINGERPRINT`. Set, a co-signature from any other key is refused, not stored, and
**Audit → Transparency** says *Key mismatch*; unset, it accepts any key as today and shows admins
*Key not pinned*. It is the same 16-character value `python -m qvault.verify --expect-witness`
takes. Details: `witness/README.md`, "Pin its key".

*What to do at the switch to the rework branch:*

1. Read the live witness's ML-DSA-87 fingerprint off the witness itself. Its startup line in the
   `qvault-witness` container log reads `witness 'witness-1' — ML-DSA-87, fingerprint …`
   (Portal → `qvault-witness` → Log stream, or
   `az containerapp logs show -n qvault-witness -g rg-qvault --subscription 4e995e2f… --tail 200`),
   and its root page shows `key fingerprint …`. On 2026-10-04 it was `810fb51e5e2f75a8` (§2.5);
   if it is anything else now, stop and find out why before pinning.
2. Set it on the app and let it restart:

   ```powershell
   az containerapp update -n qvault -g rg-qvault --subscription 4e995e2f-... --set-env-vars WITNESS_KEY_FINGERPRINT=810fb51e5e2f75a8
   ```

3. Open **Audit → Transparency** as an admin: the witness card should say *Key pinned* with that
   value, and the next checkpoint should still be co-signed within a minute. *Key mismatch* means
   the value is wrong or something else answers at `WITNESS_URL`: remove the setting
   (`--remove-env-vars WITNESS_KEY_FINGERPRINT`) to go back to accepting any key while you look.

**Trap: the old revision comes back.** `az containerapp update` creates a new revision, and on
this app the previous one has re-activated beside it before, so half the requests still run without
the setting. Right after the update, list the revisions and deactivate every old one that is still
active:

```powershell
az containerapp revision list -n qvault -g rg-qvault --subscription 4e995e2f-... -o table
az containerapp revision deactivate -n qvault -g rg-qvault --subscription 4e995e2f-... --revision <old revision name>
```

If the witness is ever given a new key on purpose, change this setting to the new fingerprint at
the same time; nothing re-pins it automatically, by design.

*Your effort:* two or three commands and one look at a page.

### 2.11 Rework R8: an email account with Resend — `DONE` 2026-10-09 (domain `mail.zaidansari.tech` verified; key in `q-vault-rework/.env.rework`)

*Why it's yours:* a third-party account in your name, and DNS records on your domain.

Decided 2026-10-09: invitation and notification emails go through **Resend** (free tier, 3,000
emails a month). Until the key exists, R8 is built and tested against a local stand-in, so nothing
waits on this except the first real email.

1. Sign up at <https://resend.com> (GitHub sign-in is fine).
2. **Domains → Add domain** → `mail.zaidansari.tech` (a subdomain, so the main domain's mail is
   untouched), region closest to India.
3. Resend lists 3–4 records (an MX and a TXT for SPF on `send.mail…`, a TXT `resend._domainkey…`
   for DKIM, optionally DMARC). In **Cloudflare → zaidansari.tech → DNS**, add each exactly as shown
   (TXT and MX records are never proxied). Back in Resend press **Verify**; it usually turns green
   within minutes.
4. **API Keys → Create** → name `qvault-rework`, permission **Sending access**, domain
   `mail.zaidansari.tech`. Copy it once (it starts `re_`).
5. Save it in a new file `C:\Users\Zaid\Documents\4th year project\q-vault-rework\.env.rework`
   (git ignores `.env.*`) as two lines:
   `RESEND_API_KEY=re_...` and `MAIL_FROM=Q-Vault <notifications@mail.zaidansari.tech>`.
   Never paste the key into chat or a commit. At the switch it becomes a Container App secret.

*Your effort:* ~10 minutes, mostly waiting for DNS.

**Still to do at the switch (R10), added 2026-10-09 by R8.** On the rework's Container App, set:

- `RESEND_API_KEY` as a **secret** (a secretref, never a plain env var).
- `MAIL_FROM=Q-Vault <notifications@mail.zaidansari.tech>` as a plain env var.
- `PUBLIC_BASE_URL=https://project4.zaidansari.tech` as a plain env var. On staging, use the
  staging address. Every link in an email starts with it, and without it no email is sent.

Push needs no server secret, because `PUSH_TRANSPORT` defaults to `expo`. Set `EXPO_ACCESS_TOKEN`
as a secret only if you switch on "Enhanced push security" for the Expo project.

Proven 2026-10-09: Resend accepted two test emails sent through the real outbox to its test
address `delivered@resend.dev`. Run one replica, or expect each replica to work the outbox. That
is safe, as the plan's R8 known gaps explain.

### 2.12 Rework R8: push notifications with Firebase (Android) — `DONE` 2026-10-09 (project `qvault-90763`; FCM V1 key assigned to `com.qvault.approvals` in Expo)

*Why it's yours:* a Google account's Firebase project and the Expo account's credentials.

Decided 2026-10-09: Android push through Firebase Cloud Messaging, set up before the rework APK
(phone-ux §12 Q3). iOS is out of scope.

1. <https://console.firebase.google.com> → **Add project** → `qvault` (Google Analytics off).
2. **Add app → Android** → package name **`com.qvault.approvals`** (must match `mobile/app.json`)
   → Register → **download `google-services.json`**. Skip the SDK steps.
3. **Project settings → Service accounts → Generate new private key**: a JSON file. This one is a
   secret.
4. Put both files in `C:\Users\Zaid\Documents\4th year project\secrets\` (outside every
   repository; create the folder).
5. Give the service-account key to Expo: <https://expo.dev> → project **qvault** (owner `zaid7864`)
   → **Credentials → Android → com.qvault.approvals → FCM V1 service account key → Upload** the
   file from step 3. This is not a build and changes nothing on phones.

**Wired (R8, 2026-10-09).** `expo-notifications` is in the rework's config, and
`mobile/app.config.js` reads `google-services.json` from the EAS file variable
`GOOGLE_SERVICES_JSON`. The file is never committed (`mobile/.gitignore`). **One step remains, before
the rework APK (§2.3):** from `q-vault-rework/mobile`, once:

`npx eas env:create --name GOOGLE_SERVICES_JSON --type file --value "C:\Users\Zaid\Documents\4th year project\secrets\google-services (1).json" --visibility secret --environment preview`

Use the environment the `rework` build profile builds with. Without the variable, the APK builds and
runs, but no push ever reaches it. For a local `expo run:android`, copy the file to
`mobile/google-services.json` instead (git ignores it).

Then, on a handset (§3.5): enrol, press "Turn on notifications", have someone raise a decision on
the web, and check three things. The push arrives within about half a minute. It shows no amount
and no payee. Tapping it opens the decision and approves nothing.

*Your effort:* ~15 minutes.

## 3. Checks only you can make

### 3.1 Look at the UI — `TODO`

I built the entire visual showcase pass without being able to see it. I verified structure
(elements present, no template errors, correct data, 145 tests green) but **not aesthetics** — I
cannot tell you whether the spacing feels right or the indigo works.

*Why it's yours:* taste.

*What I've prepared:* run it and click through in this order, which is also a good rehearsal for
the demo:

```bash
.venv/Scripts/python.exe -m flask --app wsgi run --debug
```

| Look at | What to judge |
| --- | --- |
| `/` | Does the landing page read as a serious system in the first five seconds? |
| `/ledger/` | The chain visual is the flagship. Tamper entry #1 (edit, then rewrite) and restore. |
| `/dashboard` | Do the byte counts make the cryptography feel real? |
| a proposal page | Quorum meter + signature provenance |
| `/admin/crypto`, `/admin/benchmark` | The size-comparison bars |

Tell me what feels off in plain words ("too cramped", "the green is ugly") — the design tokens are
centralised in `qvault/static/qvault.css`, so restyling propagates everywhere from one place.

*Your effort:* ten minutes.

### 3.2 Benchmark figures on demo hardware — `TODO`

The committed reference run in `docs/benchmarks/` was measured on this laptop. If the viva happens
on a different machine, or you want the cleanest possible numbers for the dissertation, re-run it
there — close other applications and stay on mains power first, as thermal throttling is the
dominant error term.

*Why it's yours:* it must run on the physical machine in question.

*What I've prepared:*

```bash
.venv/Scripts/python.exe scripts/run_benchmark.py --iterations 50 --warmup 5
```

It rewrites `docs/benchmarks/latest.json` and `latest.md`, and the admin page picks the new figures
up automatically. Commit the result.

*Your effort:* one command, about four seconds of runtime.

---

### 3.3 Run the mobile app on a real handset — `TODO`

The Expo client in `mobile/` is written, typechecks, bundles, and its signing flows pass an
end-to-end test against a real HTTP server. Three things remain that **only a phone can settle**:

1. that the `crypto.getRandomValues` polyfill installs before `@noble/post-quantum` loads under
   Hermes — it works in Node because Node has a `crypto` global and Hermes does not;
2. how long ML-DSA key derivation and signing actually take on ARM under Hermes (6-27 ms on
   desktop V8; the biometric prompt should absorb whatever multiple Hermes adds);
3. that `expo-secure-store` and `expo-local-authentication` behave on your specific device.

*Why it's yours:* it needs your hardware, your fingerprint, and your eyes on the result.

*What I've prepared:* everything else. To run it:

```bash
cd mobile
pnpm install
pnpm start
```

Then scan the QR code with **Expo Go**. It points at the deployed Azure instance already, so the
phone does not need to be on this machine's network. Sign in with your Q-Vault email and password
once, at enrolment; after that the app never asks for it again.

Expo Go supports both `expo-secure-store` and `expo-local-authentication`, so **Atharva's iPhone
works without an Apple Developer account**. For an installable Android APK later:
`eas build -p android`.

Worth doing on the demo itself: have one person approve in the app and another approve in the web
UI on the same decision. The decision screen names the custody of every vote — "key held on their
device" against "key held on the server" — so both models appear side by side on one record.

**Added 2026-09-17, after the redesign (ADR-0022).** The app was rebuilt for an approver rather
than ported from the console, so there is now a second kind of check to make, and it is the kind
only you can make: **does it feel like a product a senior person would actually use.** Specific
things to look at, because each was a deliberate call I could have got wrong:

1. **The queue.** Sorted by deadline, not recency. Headline is a sentence ("Three decisions need
   you"), not a counter. Is the urgency colouring right — only the under-six-hours band is red?
2. **The quorum marks.** A decision's progress is drawn as filled/empty marks rather than written
   as `2/3`. Does that read instantly, or does it need a number after all?
3. **The seal.** Approve something that completes a threshold and watch the last mark close. It is
   the one animation in the product and it fires only when *your* signature completed it. It should
   feel like a thing being set, not like a notification.
4. **The confirm sheet.** Approving now restates the decision verbatim before the biometric prompt.
   Is that one tap too many, or does it feel proportionate to something irreversible?
5. **The assurance line.** All the cryptography collapsed to "Verified on this device" with the
   detail one tap away. Tap it. Then decide whether the collapsed form is still enough for a viva
   audience, or whether the demo wants it expanded by default.

If any of those is wrong it is a JavaScript change and ships over the air — no new APK.

### 3.4 Rework: accessibility checks — `TODO` (added 2026-10-08)

The rework's accessibility pass (plan S24) is checked by machine as far as a machine can:
`tests/test_accessibility.py` reads every page for names, headings, ids, landmarks and tables, and
a browser run checked focus visibility in both themes, text contrast and 44px touch targets. What no
test can tell is whether the product **makes sense through a screen reader**: whether the order is
sensible, whether a control's name says what it does, whether an announcement arrives once and at
the right moment.

*Why it's yours:* it needs a person listening, on a real screen reader and a real phone.

*What I've prepared:* the pages are built for this; run the web locally over the demo data (or use
the live site after the rework is deployed) and sign in as `ada@qvault.demo` /
`demo-password-2026`.

**A. NVDA on Windows (about 30 minutes).** Install NVDA (free, nvaccess.org), open the site in
Chrome or Edge, start NVDA (Ctrl+Alt+N). Insert is the NVDA key; H moves by heading, D by landmark,
F by form field, T by table, Tab by control; Insert+F7 lists links and headings.

1. Any page: press Tab once. You should hear "Skip to content"; press Enter, then Tab again: focus
   is in the page body, past the sidebar.
2. Home: press D through the landmarks. Expect: Main (the sidebar), Breadcrumb, the main area.
   Press 1: one heading level 1 per page, then H moves through level 2s in a sensible order.
3. Sign out, then sign in with a wrong password. The error must be read without you hunting for
   it (it is an alert). Then submit the sign-in form with the email empty: focus should land on
   the email field and NVDA read its label and then the error.
4. New vault: leave the name empty and submit. Same as above: focus on the refused field, its
   error read.
5. Approvals: Tab to the filters. Each select reads its name ("Vault", "Type", "Order"); changing
   one reloads the list. Then T to the table: NVDA reads the caption, and Ctrl+Alt+arrows read
   each cell with its column header.
6. The bell (top bar): Tab to it. It reads "Notifications", the unread count and "collapsed".
   Enter opens the popover and moves into it; Escape closes it and returns to the bell.
7. Account > Notifications: Tab through the checkboxes. Each should read its group ("Outcomes"),
   its event and "In-app", and checked or not checked. The two security rows read as disabled,
   with the reason.
8. A decision page: the decision code, the status, and Approve with its password field. Approve
   once: the result is announced (a toast read through the live region) exactly once.
9. Verify (signed out): upload an exported decision. The verdict is read as soon as the page
   loads, once; the page title starts "Passed" or "Failed".
10. The avatar menu: Enter opens it, arrows move between items, Escape closes it and returns to
    the avatar. Change the theme from inside it.

**B. TalkBack on the Android phone (about 15 minutes).** Settings > Accessibility > TalkBack, on.
Swipe right/left moves, double-tap activates; the TalkBack menu (three-finger tap, or swipe down
then right) offers headings and landmarks. Open the site in Chrome on the phone.

1. Open the menu button (top left): the drawer opens, focus moves into it, and Close menu shuts
   it.
2. Account > Notifications: tap each checkbox directly (not its label). A tap a little off the
   box should still toggle it, and never the box in the row above or below.
3. Approvals: tap the filters and the tabs; each should be easy to hit first time.
4. A decision: approve one with the password field and the keyboard open; the result is read.

**C. Anything that is wrong:** tell me the page, what you did, and what was said (or not said),
in plain words. Each fix is a template or stylesheet change.

*Your effort:* about 45 minutes, once, after the rework is merged.

### 3.5 Rework: phone handset checks — `TODO` (added 2026-10-08)

Things in the rework phone app that only a handset can settle. Each was left at the safe,
already-proven setting rather than guessed.

1. **Class 3 biometrics only, and a confirm after a face match.** The spec (phone-ux §5.13, I-9)
   wants the signing prompt at `biometricsSecurityLevel: 'strong'` without
   `requireConfirmation: false`. It is not on, because expo-local-authentication 57.0.2 turns
   `'strong'` plus the PIN fallback into androidx.biometric's `BIOMETRIC_STRONG | DEVICE_CREDENTIAL`,
   which androidx documents as unsupported on Android 9 and 10 (API 28 and 29):
   `PromptInfo.Builder.build()` throws there, and the module only catches a
   `NullPointerException`, so such a phone could not sign. `mobile/src/keystore.ts` keeps the
   options every handset so far has proven (`requireConfirmation: false`, platform-default level).
   *To check:* on an Android 11+ phone and, if you have one, an Android 9 or 10 phone, set
   `biometricsSecurityLevel: 'strong'` (or gate it on `Platform.Version >= 30`), approve and reject
   once with a fingerprint and once with the PIN, and confirm the prompt opens on both. Then decide
   whether to keep the confirm after a face match.
   *The change to make once that passes* (a JavaScript change, over the air), in
   `confirmPresence` in `mobile/src/keystore.ts`: pass
   `biometricsSecurityLevel: Platform.OS === 'android' && Number(Platform.Version) < 30 ? undefined : 'strong'`
   and remove `requireConfirmation: false`; then phone-ux §5.13 and I-9 say "strong" again, and the
   button label of a phone with only Class 2 face unlock can go back from "Sign with your screen
   lock" to "Sign with your phone's PIN" (its prompt would then show only the PIN). Until then that
   phone's prompt may offer the face first, which is why the label is neutral.
2. **The decision's 20-second refresh and the biometric prompt.** The app ignores the app going to
   the background while its own prompt is up (the PIN screen on Android is a separate activity).
   *To check:* open a decision, approve with the PIN fallback, take 30 seconds over the PIN, and
   confirm the sheet stays put and the signature goes through.
3. **Offline.** Turn on aeroplane mode with the app open: the bar "Offline. Showing what was here
   at …" should appear on the next refresh, the queue stays, and Approve on a decision says it needs
   a connection. Kill the app, reopen it offline, and confirm the queue paints from the encrypted
   cache. (Before the rework APK there is no NetInfo, so the bar appears after a failed request,
   not the instant the radio drops.) If the queue does not paint offline after a restart, the APK
   is missing expo-file-system's native module (it should come with `expo`); the app then simply
   keeps no cache, and nothing else breaks.
4. **Push (R8), on the rework APK built with the Firebase file (§2.12).** After enrolling, the
   "Get told when something needs you" sheet should appear once. "Turn on notifications" should
   bring up Android's permission prompt; nothing should ask before that.
   *To check:*
   - Raise a decision on the web as someone else. Within about half a minute the phone shows
     "Needs your signature" with the vault's name and the due time, and with no title, amount or
     payee. This holds on the lock screen too.
   - Tapping the push opens that decision. Nothing approves from the notification or its shade.
   - With Q-Vault open, a push shows no banner, and the queue updates instead.
   - Account → Notifications shows "On". Switching "Updates" off stops the "Approved" push to the
     person who raised the decision.
   - Removing the phone stops its pushes.

## 4. Submission and delivery

### 4.1 The dissertation — `TODO`

*Why it's yours:* it's your degree, and it must be in your voice.

*What I've prepared / will prepare:* the ADRs in `docs/adr/` are deliberately written as design
rationale you can lift into a Design chapter, and `docs/benchmarks/latest.md` is paste-ready tables
for an Evaluation chapter. I'll draft whatever sections you want in P9 — but the words you submit
should be words you can defend.

### 4.2 Synopsis title page details — `DONE` (2026-08-06)

Supplied by you and built into `../documents/synopsis/synopsis.pdf` (8 pages):

| Field | Value now on the title page |
| --- | --- |
| Team | Hassan Shaikh (70), Zaid Ansari (63), Gracian Lopes (68), Atharva Tike (53) |
| Guide | Ms Varunakshi Bhojane |
| Department | Computer Science and Engineering (IoT, Blockchain and Cybersecurity) |
| Academic year | 2026-2027 |

Two things I did not decide for you, both one-line edits to the
`DETAILS TO CONFIRM` block at the top of `documents/synopsis/synopsis.tex`:

- **Name order** is exactly the order you listed, which is not roll-number
  order (70, 63, 68, 53). If your department expects ascending roll numbers,
  reorder the four `\studentlist` lines.
- **Roll numbers vs. full student IDs** — you gave two-digit roll numbers; the
  departmental example synopsis uses full nine-digit IDs (e.g. `202204021`).
  Check which your submission wants.

### 4.3 Confirm "Tamper-Evident" in the project title — `TODO`

The submitted title currently reads "…with a **Tamper-Evident** Ledger-Based
Audit Trail…". The original project brief proposed "**Immutable** Ledger-Based
Audit Trail".

*Why it's yours:* it is the title on your submission, and the wording is a claim
you will have to defend in the viva.

*What I've prepared:* my recommendation is to keep **tamper-evident**. The
system cannot honestly claim immutability — ADR-0005 records that truncating the
tail of the chain is undetectable without an external witness. Tamper-evidence
is precisely what the demo proves, and a title that overstates the guarantee is
the kind of thing an examiner will probe. Say the word and I'll switch it back.

*Your effort:* one word, in `\projecttitle`.

### 1.4 Decide whether the live trace is on for the demo — `TODO` (added 2026-09-09)

The glass box (`/trace`, ADR-0020) shows real cryptographic values from live operations —
canonical signing payloads, public keys, signatures, Merkle nodes — with the source that produced
them. It is **off by default**, administrator-only, and 404s entirely when disabled.

*Why it's yours:* it is an exposure decision, not a technical one. Everything it prints is public
by construction and the redaction layer withholds every secret (there is a test that takes the
whole serialised payload after a real vote and searches it for the private key and the password),
but a page that exists to reveal internals is a judgement call on a deployment that other people
can reach.

*What I've prepared:* set `GLASSBOX_ENABLED=true` in the Container App's environment to turn it on
(it is already on in local development). My recommendation: **on for the demo instance**, because
it is the most persuasive answer to "how do you know it really does that?" — and off again
afterwards, alongside §2.4.

*Check it works:* sign in as the admin, open `/trace` in a second window, cast a vote in the
first. You should see one operation and nine steps.

### 1.5 Decide whether the adversary lab is on for the demo — `TODO` (added 2026-09-12)

The adversary lab (`/admin/attack`, ADR-0021) runs ten attacks against the system and against
controls, and it is the answer to *"you showed me it works, show me it is hard to break."* Like the
trace it is **off by default**, administrator-only, and 404s when disabled.

*Why it's yours:* the same exposure judgement as §1.4, plus one more consideration. The page
publishes, in public, the exact mechanism that defeats each attack and the exact control under which
each attack succeeds. I consider that a feature — it is what makes the claims checkable — but on a
deployment other people can reach it is your call, not mine.

*What I've prepared:* set `ATTACK_LAB_ENABLED=true` in the Container App's environment (already on
in local development). My recommendation: **on for the demo instance**, then off with §2.4. One
thing to know: the in-request run executes only the algorithm-level attacks, which need no
database. The database-backed ones forge signature rows and edit ledger entries, so they run only
in `scripts/run_attack_lab.py` against a throwaway in-memory application — the page reports those
from the committed `docs/attack-lab/latest.json` and says so on screen. There is a test that fails
if that ever changes, and it checks the data rather than the configuration.

*Check it works:* sign in as the admin, open `/admin/attack`, press "Run the algorithm attacks
now". You should get six live attacks, all "as expected", in roughly fifteen seconds, and the
recorded run below it showing all ten.

*One thing to say out loud in the demo,* because it is the honest framing and it is better coming
from you than from a question: the Shor demonstration factors a **9-bit** modulus, not 2048. The
algorithm is the real one and runs to completion; the parameter is scaled because simulating the
quantum register costs O(2^t). The claim is "the algorithm that breaks RSA runs here and its cost is
polynomial", never "we broke RSA-2048".

### 4.4 The research paper — venue and submission — `TODO` (added 2026-09-09)

Groundwork is in `docs/paper/research/`. Three things need you:

1. **Choose a target.** My reading of the survey is IACR **ePrint** as a preprint this week (no
   endorsement needed, free, where PQC people read), then a real venue. Note **arXiv is now a
   genuine blocker**: since 21 January 2026 a first-time submitter needs prior arXiv authorship or
   a personal endorsement, so it is not the quick option it used to be.
2. **Submit under your own name and affiliation.** Author identity, ORCID and institutional
   details are yours; I cannot create the accounts or agree to the licence terms.
3. **Check the money before committing to an ACM venue.** ACM went fully open-access on
   2026-01-01. If your university is not an ACM Open participant, SAC carries a **$500–750** fee.
   Worth confirming with the department before a deadline forces the question.

*Deadlines found (re-verify before relying on them):* SPACE 2026 cycle 2 — abstract 18 Sep,
paper 25 Sep 2026. SEC@SAC 2027 — 2 Oct 2026. ACSAC 2026 posters — 19 Sep 2026.

*One thing to be clear about before you write a word:* the SPHINCS+/FIPS-205 incompatibility is
**already publicly documented** — FIPS 205 Appendix A states it outright, and it is recorded in
liboqs #1894, PQClean #562 and a Red Hat RHEL 10 advisory. Presenting it as our discovery would be
a credibility error in the paper and in the viva. What *is* ours is the narrower point: an
algorithm identifier that names a NIST standard while binding to a pre-standard construction,
undetectable from key and signature sizes, caught only by cross-implementation verification.
Sources are in `docs/paper/research/related-work.md`.

### 4.3 The viva — `TODO`

*Why it's yours:* you're in the room.

*What I've prepared / will prepare:* a scripted demo path in P9, plus the "state this in the viva"
notes already embedded in docstrings across the codebase (`interfaces.py`, `benchmark_service.py`,
`anchor.py`) — those are the defensible claims, written where they can't drift from the code.

---

## Log

| Date | Change |
| --- | --- |
| 2026-08-04 | Created. Seeded from the state after Phase 8. |
| 2026-08-06 | Added §4.2 — title-page details for the drafted synopsis. |
| 2026-08-06 | §4.2 closed (details supplied and built in); split the title wording out as §4.3. |
| 2026-08-20 | Pre-demo verification. Added §2.4 (demo-day Azure spend to revert) and §2.5 (publish the witness fingerprint). |
| 2026-08-21 | §2.5 partly closed: both fingerprints published off-platform; the slide is still yours. |
| 2026-09-09 | Added §1.4 (turn the live trace on for the demo?) and §4.4 (paper venue + submission). |
| 2026-09-17 | Added §2.8: on-chain execution on Sepolia. Keys received, relayer wallet generated, funding outstanding. |
| 2026-09-17 | §2.8: Phases 1–2 committed; the Phase 3 broadcast was blocked by the session's permission system and needs your approval (command recorded). |
| 2026-09-27 | Added §2.9: the system rebuilt on a teammate's Azure subscription (`rg-qvault`, Central India), `project4.zaidansari.tech` kept; new fingerprints to republish; master key to back up; old deployment to delete. |
| 2026-10-08 | Added §2.10: pin the live witness key (`WITNESS_KEY_FINGERPRINT`) at the switch to the rework. |
| 2026-10-08 | Added §3.4: the rework's accessibility checks only a person can make (NVDA on Windows, TalkBack on the phone). |
| 2026-10-08 | Added §3.5: rework phone handset checks (Class 3 biometrics on Android 9 and 10, the prompt with the refresh, offline). |
| 2026-10-09 | Added §2.11 (Resend email) and §2.12 (Firebase push) for rework R8, after the owner chose both. |
| 2026-10-09 | R8 built: §2.11 gains the switch-time settings (`RESEND_API_KEY` as a secret, `MAIL_FROM`, `PUBLIC_BASE_URL`); §2.12 gains the one EAS command for the Firebase file before the rework APK, and the handset check; §2.3's "decided against expo-notifications" is marked superseded on the rework. |
