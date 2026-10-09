# Staging (rework R10)

Staging runs the rework image beside the live app on the team subscription, with its **own**
database and its **own** keys, so the team can try the rework before anyone decides to switch.
Nothing in it reads or writes the live app's database, file share, witness or treasury.

| | Staging | Live (unchanged) |
| --- | --- | --- |
| Container app | `qvault-staging` (0 to 1 replica, scales to zero) | `qvault` |
| Address | `https://qvault-staging.livelybeach-69506dc5.centralindia.azurecontainerapps.io` | `https://project4.zaidansari.tech` |
| Database | `qvault_staging` on `qvault-pg-260927` | `qvault` on the same server |
| Keys | its own `SECRET_KEY` and `SERVER_MASTER_KEY` | the live ones |
| Log origin | `<staging address>/ledger` | `project4.zaidansari.tech/team-ledger` |
| Witness, treasury, attack lab | off | as configured |
| Email | Resend, from `mail.zaidansari.tech` | none |
| Attachments | the container's own disk: **lost when it restarts or scales to zero** | the `vault-files` share |

All commands run against the team subscription only:
`--subscription 4e995e2f-5117-441f-97d2-149256d6215b`, with `MSYS_NO_PATHCONV=1` in Git Bash.

## How it was built (2026-10-09)

1. `az postgres flexible-server db create -g rg-qvault --server-name qvault-pg-260927 --name qvault_staging`.
2. Secrets, generated on the operator's machine and never printed: the live `database-url` with
   the database name swapped for `qvault_staging`, and a fresh `SECRET_KEY` and
   `SERVER_MASTER_KEY` (64 hex). They are kept outside the repository; losing the staging master
   key only loses staging's data.
3. A manual job `qvault-staging-migrate` (the rework image, command `alembic upgrade head`,
   `DATABASE_URL` from its secret) built the schema: `0001_baseline` to the head, on PostgreSQL.
   This is the same path the switch takes, on an empty database.
4. `az containerapp create -n qvault-staging` in `qvault-env` (Consumption profile, 0.5 CPU, 1 GiB,
   external ingress on 8000), with `FLASK_ENV=production`, `RATE_LIMIT_PROXY_HOPS=1` (ingress
   directly; Cloudflare is DNS-only), `PUBLIC_BASE_URL` set to the staging address,
   `SCHEDULER_ENABLED=true`, `ONCHAIN_EXECUTION_ENABLED=false`, `ATTACK_LAB_ENABLED=false`,
   `GLASSBOX_ENABLED=true`, and `RESEND_API_KEY` (secret) plus `MAIL_FROM`.
5. On first start the app wrote the genesis entry, its SYSTEM key and the first signed checkpoint.
   Checked: `/healthz`, `/`, `/status` and `/transparency/checkpoint.json` answer 200, and the
   live app still has one active revision.

## People

No accounts are seeded. The owner signs up at the staging address ("Create your workspace") and
invites the team from **Members → Invite**; the invitations arrive by email. That is the rework's
real path (R6 sign-up, R3 invitations, R8 email) rather than a script.

## Updating the image

```bash
az containerapp update -n qvault-staging -g rg-qvault --subscription 4e995e2f-5117-441f-97d2-149256d6215b \
  --image ghcr.io/zaidnansari2011/post-quantum-multi-signature-vault:<full sha>
az containerapp revision list -n qvault-staging -g rg-qvault --subscription 4e995e2f-5117-441f-97d2-149256d6215b -o table
```

Deactivate any older revision that is still active afterwards (this environment has re-activated
old revisions before). If the new image adds a migration, start the job with the same image first:

```bash
az containerapp job update -n qvault-staging-migrate -g rg-qvault --subscription 4e995e2f-5117-441f-97d2-149256d6215b --image <same image>
az containerapp job start  -n qvault-staging-migrate -g rg-qvault --subscription 4e995e2f-5117-441f-97d2-149256d6215b
```

## Known limits

- Scales to zero when idle: the first request after a quiet spell takes a few seconds, and the
  scheduler (reminders, the email and push outbox) runs only while a replica is up.
- Attachments do not survive a restart (no file share, on purpose: the live share is not shared).
- Push needs the rework APK (R7) and, once Enhanced Push Security is on, `EXPO_ACCESS_TOKEN`.

## Removing it

`az containerapp delete -n qvault-staging`, `az containerapp job delete -n qvault-staging-migrate`,
and `az postgres flexible-server db delete --server-name qvault-pg-260927 --name qvault_staging`
(all with `-g rg-qvault` and the subscription). The live app is unaffected.
