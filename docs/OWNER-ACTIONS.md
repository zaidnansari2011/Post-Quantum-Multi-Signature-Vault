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

*(Nothing outstanding. The project deliberately uses no third-party services — no cloud, no paid
APIs, no external key management. It runs entirely offline on one machine, which is itself worth
saying in the viva: the security argument depends on no vendor.)*

If I later propose anything that needs an account, it appears here **before** I build against it,
never after.

---

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

## 4. Submission and delivery

### 4.1 The dissertation — `TODO`

*Why it's yours:* it's your degree, and it must be in your voice.

*What I've prepared / will prepare:* the ADRs in `docs/adr/` are deliberately written as design
rationale you can lift into a Design chapter, and `docs/benchmarks/latest.md` is paste-ready tables
for an Evaluation chapter. I'll draft whatever sections you want in P9 — but the words you submit
should be words you can defend.

### 4.2 The viva — `TODO`

*Why it's yours:* you're in the room.

*What I've prepared / will prepare:* a scripted demo path in P9, plus the "state this in the viva"
notes already embedded in docstrings across the codebase (`interfaces.py`, `benchmark_service.py`,
`anchor.py`) — those are the defensible claims, written where they can't drift from the code.

---

## Log

| Date | Change |
| --- | --- |
| 2026-08-04 | Created. Seeded from the state after Phase 8. |
