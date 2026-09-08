# Q-Vault — Publication Venues, Formats, and Requirements

**Research compiled 2026-09-08/09.** Every factual claim below carries the URL it came from. Anything I could
not confirm from a fetched page is marked **UNVERIFIED** in bold. Deadlines are quoted with the year the
source page states; where a date has already passed relative to 2026-09-08 I say so.

**Paper in question:** Q-Vault — a crypto-agile post-quantum multi-signature vault. ML-KEM (FIPS 203),
ML-DSA (FIPS 204), SLH-DSA (FIPS 205, via PQClean SPHINCS+); application-level M-of-N approval workflow;
hash-chained append-only audit ledger; RFC 6962 Merkle transparency log with signed checkpoints; an
independent witness co-signing checkpoints; a dependency-free offline verifier. Solo undergraduate author.

---

## 0. Recommended path (read this bit if you read nothing else)

Q-Vault is an *implementation-and-evaluation systems paper about cryptographic migration and agility*.
That is a real, currently fashionable topic with dedicated venues — but the paper is almost certainly not
a top-4 security conference paper (those run at 12–18% acceptance; see §2.6), and a solo undergraduate
with no publication record will additionally hit the **new arXiv endorsement wall** (§1), which is the
single biggest practical blocker and is worse than it was a year ago.

### Recommendation 1 — Preprint on the IACR Cryptology ePrint Archive, not arXiv. Do this first, this week.

The ePrint Archive has **no endorsement requirement**: "Any author can submit a paper with a technical
contribution in the field of cryptology"
([eprint.iacr.org/operations.html](https://eprint.iacr.org/operations.html)). It is free, it is the
default preprint venue that PQC researchers actually read, and it gives you a stable citable URL
immediately. arXiv, by contrast, now requires either prior arXiv authorship *plus* an institutional email,
or a personal endorsement from an established arXiv author
([blog.arxiv.org, 2026-01-21](https://blog.arxiv.org/2026/01/21/attention-authors-updated-endorsement-policy/)).
Do ePrint first; do arXiv later only if a supervisor endorses you.

Caveat: ePrint is scoped to *cryptology*. Q-Vault is a systems paper that uses cryptography. Frame the
abstract around the cryptographic content (PQC scheme composition, transparency-log construction,
threshold/multi-signature protocol, checkpoint co-signing) rather than around the vault UI, or the editors
may bounce it as out of scope.

### Recommendation 2 — SPACE 2026, Cycle 2. **Submission window is open right now and closes later this month.**

*International Conference on Security, Privacy and Applied Cryptographic Engineering*, 16th edition,
Bengaluru, 16–19 December 2026. Cycle-2 abstract registration **18 September 2026**, paper **25 September
2026**, notification 2 November 2026. LNCS template, max 20 pages *including* bibliography and appendices,
double-blind, Springer LNCS proceedings. Post-quantum cryptography is explicitly named in the topic list
under "Applied Cryptography, Blockchain and Distributed Systems"
([space2026.isec.tugraz.at](https://space2026.isec.tugraz.at/);
registration deadline "Friday Sep 18, 2026, 11:59:59 PM AoE" confirmed on the Cycle-2 HotCRP at
[space2026-cycle-2.hotcrp.com](https://space2026-cycle-2.hotcrp.com/)).

This is the best fit I found that is *actually open*: "applied cryptographic engineering" is precisely what
Q-Vault is, it is Springer-indexed (so it counts as a real publication), and it is a second-tier venue where
a careful implementation-and-evaluation paper from a strong undergraduate is plausible. **Re-verify both
dates before relying on them** — the CFP page notes Cycle-2 deadlines "have been updated" at least once.

### Recommendation 3 — SEC@SAC 2027 (Computer Security track, ACM SAC). Deadline 2 October 2026.

8 pages (10 with a page charge), blind review, at least three referees, ACM Digital Library proceedings,
conference 5–9 April 2027 in Gwangju, South Korea
([dmi.unict.it/giamp/sac/cfp2027.php](https://www.dmi.unict.it/giamp/sac/cfp2027.php)). SAC is a well-known
ACM conference with a deliberately applied remit and an early-October deadline, and it has a **2-page poster
paper** option (up to 3 pages with a surcharge) if the full paper isn't ready. The catch is money: ACM went
100% open access on 2026-01-01, and if your institution is not an ACM Open participant you pay an APC of
**$500 (ACM/SIG member) or $750 (non-member)** for a 2027 paper
([acmse.net/2027/papers-call](https://acmse.net/2027/papers-call/)). Check your university's ACM Open status
*before* submitting.

### Runner-up worth flagging: MAgiCS

*Workshop on Migration and Agility in Cryptographic Systems* — literally the name of what Q-Vault does. The
first edition ran 10 May 2026 in Rome, co-located with EUROCRYPT 2026; Springer CCIS proceedings, 18 pages
excluding references, double-blind ([magics-workshop.cs.hs-rm.de](https://magics-workshop.cs.hs-rm.de/),
[easychair.org/cfp/MAgiCS26](https://easychair.org/cfp/MAgiCS26)). Accepted papers included
"Cryptographic Agility for Applications: An Assessment Framework and Principled API Design" and
"Post-quantum Blockchains with Agility in Mind" — the same genre as Q-Vault. **No 2027 edition is announced**
(workshop page last updated 2026-06-20). If MAgiCS 2027 is announced with a ~February 2027 deadline, it is
the single best topical home for this paper. Set a reminder to check in November 2026.

### One near-term, low-risk extra: ACSAC 2026 Posters / Works-in-Progress — deadline 19 September 2026

2 pages max including references, IEEE 2-column template, **not anonymous**, no publication surcharge for
posters, conference 7–11 December 2026 in Los Angeles. The call says they are "particularly interested in
work that shares real-life experiences including actual system or product implementation"
([acsac.org/2026/submissions/posters](https://www.acsac.org/2026/submissions/posters/)). As of 2026-09-08
this is **still open** — note that a poster requires you to travel and register, so only do
this if attendance is feasible.

**Suggested sequence:** ePrint preprint now → SPACE 2026 Cycle 2 (25 Sep) → if rejected, SEC@SAC 2027 poster
paper or ACMSE 2027 (14 Nov) → watch for MAgiCS 2027 → keep ACSAC 2027 and ICISS 2027 as the next full-paper
targets. Do **not** aim first at IEEE S&P / CCS / USENIX Security / NDSS.

---

## 1. arXiv: the endorsement blocker (verified, and it is real)

**The policy changed on 21 January 2026 and it got harder, not easier.**

From [blog.arxiv.org/2026/01/21/attention-authors-updated-endorsement-policy/](https://blog.arxiv.org/2026/01/21/attention-authors-updated-endorsement-policy/):

- Effective **21 January 2026**, across **all arXiv categories**.
- arXiv's stated reason: "institutional email addresses are no longer a sufficient credential for
  determining minimum research competence or endorsement." They cite an unsustainable rise in
  non-scientific submissions.
- **Path 1:** an institutional email from an academic/research organisation **AND** "previous authorship on
  an existing paper which has been accepted to the arXiv 'endorsement domain'" you want to submit to.
- **Path 2:** seek a personal endorsement from an established arXiv author in the field.
- Previously endorsed authors keep their endorsement. arXiv staff will not endorse you themselves.

From [info.arxiv.org/help/endorsement.html](https://info.arxiv.org/help/endorsement.html) (note: the URL
without `.html` 404s):

- All first-time submitters need endorsement before their first paper, and again when entering a new category.
- Endorsers "must have authored a certain number of papers within the endorsement domain of a subject area",
  and arXiv only counts "papers that have been submitted between three months and five years ago."
- Mechanics: start a submission, which triggers an endorsement-request email; find endorsers among authors
  of related papers; contact them with the provided link; you need at least one positive endorsement.

**Category:** `cs.CR` — "Covers all areas of cryptography and security including authentication, public key
cryptosytems, proof-carrying code, etc." ([arxiv.org/category_taxonomy](https://arxiv.org/category_taxonomy)).
That is the right primary category. `cs.DC` (distributed/cluster) is a defensible cross-list for the witness
and transparency-log components; `cs.SE` is not.

### What this means for a solo undergraduate

A first-time submitter with no prior arXiv paper **cannot self-serve**, even with a university email address.
You need a named human to endorse you. Practical routes, in order of likelihood:

1. **Add your project supervisor as a co-author** if they contributed — most supervisors in a CS department
   have arXiv papers and become an automatic route via Path 1/2.
2. **Ask your supervisor or a departmental researcher to endorse** you (they don't have to be a co-author;
   they do have to have enough recent arXiv papers in the cs endorsement domain).
3. **Post to IACR ePrint instead** (§2.3) — no endorsement, no fee, better-targeted readership for a PQC paper.

Treat arXiv as a nice-to-have, not the plan.

---

## 2. Venue catalogue

### 2.1 Open now or imminent (as of 2026-09-08)

| Venue | Type | Deadline | Length | Blind? | Proceedings | Fee | Realistic? |
|---|---|---|---|---|---|---|---|
| **SPACE 2026 Cycle 2** | Conference | Abstract **18 Sep 2026**, paper **25 Sep 2026** | 20 pp incl. bib + appendices, 10 pt | Double-blind | Springer LNCS | Registration only (**UNVERIFIED** amount) | **Yes — best open fit** |
| **SEC@SAC 2027** | Conference track | **2 Oct 2026** | 8 pp (10 w/ charge); posters 2 pp (3 w/ surcharge) | Blind, ≥3 referees | ACM DL | ACM APC $500/$750 if not ACM Open | **Yes** |
| **ACSAC 2026 Posters/WiP** | Poster | **19 Sep 2026** 23:59 AoE | 2 pp incl. refs | Not anonymous | Not in proceedings | No publication surcharge; must register/attend | **Yes, if you can attend LA in Dec** |
| **ACMSE 2027** | Conference | **14 Nov 2026** | Full 7–10 pp; short 5–6 pp | Double-anonymous | ACM DL | APC $500/$750; posters exempt | **Yes** |
| **IACR ePrint** | Preprint | Rolling | No limit | Must NOT be anonymous | n/a (archive) | Free | **Yes — do it now** |

Sources: [SPACE 2026](https://space2026.isec.tugraz.at/) and
[SPACE Cycle-2 HotCRP](https://space2026-cycle-2.hotcrp.com/);
[SEC@SAC 2027 CFP](https://www.dmi.unict.it/giamp/sac/cfp2027.php);
[ACSAC 2026 posters](https://www.acsac.org/2026/submissions/posters/);
[ACMSE 2027 CFP](https://acmse.net/2027/papers-call/);
[ePrint operations](https://eprint.iacr.org/operations.html).

**Detail — SPACE 2026.** Cycle 1 (abstract 7 Jul 2026, paper 10 Jul 2026, notification 14 Aug 2026) has
closed. Cycle 2: abstract 18 Sep 2026, paper 25 Sep 2026, notification 2 Nov 2026. Submissions must be PDF,
English, "Official LNCS template" with unmodified margins, max 20 pages at 10 pt including bibliography and
appendices, "double-blind review: all submissions must be appropriately anonymized". All accepted papers go
to Springer LNCS. Conference 16–19 December 2026, Bengaluru, India. A "Fellowship" programme is referenced
but its terms are **UNVERIFIED**.

**Detail — SEC@SAC 2027.** 26th edition of the Security Track. Topics span "software security (protocols,
operating systems, etc.)" through adversarial ML, hardware, mobile, network, cloud and IoT security. Papers
2 Oct 2026 → notification 13 Nov 2026 → camera-ready 4 Dec 2026 → author registration 11 Dec 2026 →
conference 5–9 April 2027, Gwangju. "Each paper will be fully refereed and undergo a blind review process by
at least three referees." ACM conference-specific LaTeX style. Presenter attendance mandatory for inclusion.

**Detail — ACMSE 2027 (ACM Southeast Conference).** Two categories: full papers 7–10 pages with roughly 35%
acceptance, short papers 5–6 pages with roughly 45% acceptance. Double-anonymous, three-phase review
(desk-reject screen, evaluation, optional rebuttal). Manuscripts due 14 Nov 2026, notification 20 Feb 2027,
camera-ready 1 Mar 2027, conference 15–17 April 2027. LaTeX template mandatory, PDF only, Word not accepted.
Published in ACM DL (ISBN 979-8-4007-2749-8). Explicit APC statement: no fee if you are at an ACM Open
institution, otherwise $500 for ACM members / $750 for non-members, "with rare waivers available"; posters
exempt from APCs. This is a genuinely undergraduate-friendly ACM venue and the short-paper option matches a
capstone-scale contribution.

### 2.2 Recurring, realistic — plan for the next cycle

**MAgiCS — Workshop on Migration and Agility in Cryptographic Systems.** First edition 10 May 2026, Aula 13,
Città Universitaria, Sapienza University of Rome, affiliated with EUROCRYPT 2026. Chairs: Daniel Loebenberger
and Marc Stöttinger. Submission 1 Feb 2026 (the workshop site and the EasyChair CFP disagree slightly: 1 Feb
vs 15 Feb 2026), notification 22 Mar 2026, camera-ready 29 Mar 2026. "Papers must be original, unpublished,
anonymous, and not submitted to journals or other conferences/workshops." Springer CCIS format, max 18 pages
excluding references, double-blind. Topics: crypto-agility methodologies, maturity models, software tooling,
hardware accelerators, protocol design, key management, formal verification, hybrid solutions (classical+PQC,
multiple PQC schemes, QKD+PQC), CBOMs, legacy support strategies, attacks on agile schemes, identification of
legacy cryptography in systems. Proceedings: Springer CCIS volume
([link.springer.com/book/9783032289452](https://link.springer.com/book/9783032289452)).
**No 2027 edition announced as of the page's 2026-06-20 update** — recurrence is **UNVERIFIED**.
Sources: [magics-workshop.cs.hs-rm.de](https://magics-workshop.cs.hs-rm.de/),
[easychair.org/cfp/MAgiCS26](https://easychair.org/cfp/MAgiCS26),
[NIST PQC-forum announcement](https://groups.google.com/a/list.nist.gov/g/pqc-forum/c/29-wFow5Ses).

**ACSAC — Annual Computer Security Applications Conference.** ACSAC 2026 is 7–11 December 2026 in Los Angeles.
The 2026 paper deadline (26 May 2026, "firm") has passed; the next full-paper opportunity is ACSAC 2027, on
what is historically a ~May deadline (2027 dates **UNVERIFIED**). Why it matters for Q-Vault: ACSAC
"encourages papers with results that are demonstrably useful for improving cybersecurity and that address
lessons learned from practical applications" and is "especially interested in submissions that address the
application of security technology, the implementation of systems, and lessons learned" — the most
implementation-friendly stance of any established security conference.
Format: max 11 double-column pages excluding well-marked references and appendices (appendices ≤5 pages,
total PDF ≤16 pages), **IEEE double-column format with IEEEtran.cls version 1.8b**, US letter, formatting
strictly enforced with desk-rejection risk. Double-blind, two review rounds with early rejection and an
author-response period. Also runs a non-archival **Case Studies in Applied Security Track** (talks, not in
proceedings, with a Best Case Study Award) and an **Artifacts Competition** for previously published
artifacts. Sources: [acsac.org/2026/submissions/papers](https://www.acsac.org/2026/submissions/papers/),
[acsac.org/2026/submissions](https://www.acsac.org/2026/submissions/).

**ICISS — International Conference on Information Systems Security.** 22nd edition, 16–20 December 2026,
Chennai Mathematical Institute, in partnership with IIT Bombay. Paper deadline 31 July 2026 (passed),
notification 30 Sep 2026, camera-ready 7 Oct 2026. LNCS format, 20 pages excluding well-marked appendices and
references, double-blind, ≥3 reviews, Springer proceedings, best-paper award, partial travel grants for
students with accepted papers. Notably it runs an **Industry/Demo track** for "implementations and
proof-of-concepts" and a **PhD Forum track** with a registration fee waiver. Target ICISS 2027 (deadline
**UNVERIFIED**). Source: [iciss.in/cfp](https://iciss.in/cfp/).

**ARES — International Conference on Availability, Reliability and Security.** ARES 2026 was the 21st edition,
24–27 August 2026, Linköping University, Sweden; abstract 2 March 2026 and full paper 9 March 2026, both
passed. **ARES 2027 is not announced on the conference site**, so its dates are **UNVERIFIED**. ARES hosts a
large satellite-workshop programme, which historically is where short applied-security papers land; the
individual workshop CFPs are **UNVERIFIED**. Source:
[ares-conference.eu](https://www.ares-conference.eu/).

**SVCC Post-Quantum Security Workshop (Silicon Valley Cybersecurity Conference).** Explicitly invites
"high-quality, previously unpublished research papers, position papers, experience reports, and system demos"
on PQC including "performance evaluations, implementation security, and migration strategies for PQC in
large-scale systems". 5 pages, IEEE conference format, EasyChair. The 2026 deadline was 15 March 2026
(passed) with notification 20 March 2026 — an unusually short turnaround. Publication venue and fees are not
stated on the page (**UNVERIFIED**), and **SVCC 2027 is not announced**. Worth watching: a 5-page experience
report is exactly the right size for a first paper. Source:
[svcc-svcsi.org/post-quantumsecurityworkshop](https://www.svcc-svcsi.org/post-quantumsecurityworkshop).

**PQCrypto.** 17th International Conference on Post-Quantum Cryptography, 14–16 April 2026, Saint-Malo,
France; deadlines 31 Oct 2025 (initial) and 7 Nov 2025 (final), both long passed; Springer proceedings; topics
include "integration of and migration to post-quantum cryptography". **PQCrypto 2027 is not announced** —
dates **UNVERIFIED**. Note also that PQCrypto is a *cryptography* conference: it will judge Q-Vault on
cryptographic novelty, which a systems-integration paper mostly does not have. Lower priority than
MAgiCS/SPACE. Sources:
[PQCrypto 2026 announcement on the NIST PQC forum](https://groups.google.com/a/list.nist.gov/g/pqc-forum/c/omD5J9dmqbk),
[Springer PQCrypto series](https://link.springer.com/conference/pqcrypto).

### 2.3 Preprint / archival (non-refereed)

**IACR Cryptology ePrint Archive — the recommended preprint route.**
- Established 1999 by the IACR; "over 15,000 papers"
  ([eprint.iacr.org/about.html](https://eprint.iacr.org/about.html)).
- "Any author can submit a paper with a technical contribution in the field of cryptology."
  **No endorsement, no affiliation requirement, no fee mentioned.**
- Submissions **must not be anonymous**: "title, author name(s), and a contact address or affiliation(s) on
  the first page."
- Editors check only that a submission: "address[es] research in cryptology and related fields"; is "clear,
  readable, and self-contained"; "look[s] somewhat new and interesting"; and "contain[s] proofs or convincing
  arguments for any claims". "If a paper is accepted, this does not mean that the editors have verified any
  claims or arguments."
- "Papers have been placed here by the authors and did not undergo any refereeing process other than
  verifying that the work seems to be within the scope of cryptology and meets some minimal acceptance
  criteria."
- Licensing: you "grant IACR a non-exclusive and irrevocable license to distribute the paper", you certify
  you have the right to do so, and "publications cannot be completely removed once accepted". Withdrawal
  keeps the title, abstract and all past versions, and "once withdrawn, a paper cannot be restored."
- Source: [eprint.iacr.org/operations.html](https://eprint.iacr.org/operations.html).

**Practical consequence:** post the *final* version you're happy with, not a draft you'll be embarrassed by —
you cannot fully delete it. Also check the target venue's concurrent-submission rule before posting; most
crypto and security venues explicitly allow ePrint/arXiv preprints, but MAgiCS's "original, unpublished,
anonymous, and not submitted to journals or other conferences/workshops" wording is worth clarifying with the
chairs (**UNVERIFIED** whether MAgiCS treats a preprint as prior publication).

**arXiv (cs.CR).** See §1. Free, but gated by endorsement.

### 2.4 Journals

| Journal | Model | APC | Length | Notes |
|---|---|---|---|---|
| **IACR Communications in Cryptology (CiC)** | Diamond OA, fully refereed, rolling issues | **None** — no charge to author or reader | Regular papers ≤20 pp excl. bibliography; long papers uncapped, >40 pp may be deferred across rounds | `iacrcc` LaTeX class, `\documentclass[version=submission]{iacrcc}`, from publish.iacr.org/iacrcc. Rebuttal phase. Vol 3 Issue 3: submit 27 Jul 2026, rebuttal 31 Aug–4 Sep 2026, notify 22 Sep 2026, final 16 Oct 2026. Later 2026/2027 cycles **UNVERIFIED**. Scope is "any topic in cryptology" — a pure systems paper risks a scope rejection. |
| **IEEE Access** | Gold OA, multidisciplinary, fast review | **$2,160** + local taxes | No page limit, <20 pp preferred | 5% discount for IEEE members, 20% for society members — but the page states discounts "do not apply to Student or Graduate Student Members". Only waiver is for World-Bank low-income countries where *all* co-authors qualify. |
| **Cryptography (MDPI)** | Gold OA | **CHF 1,800** | **UNVERIFIED** | Fully open access, ISSN 2410-387X. |
| **ACM TOPS (Transactions on Privacy and Security)** | ACM OA (post-2026 transition) | ACM APC applies if not ACM Open (**exact journal APC UNVERIFIED**) | **≤35 pp total** in ACM style; over-length rejected without review | "Submitted papers should have practical relevance to the construction, evaluation, application, or operation of security or privacy-critical systems" — good scope fit, but a top-tier journal bar. |
| **Journal of Cryptographic Engineering (Springer)** | Hybrid / transformative | **$0 if you choose the subscription route**; APC only if you opt into OA | **UNVERIFIED** | The one genuinely free-to-publish traditional journal in the list. Scope (implementation and engineering of cryptography) is a strong match for Q-Vault. |
| **Journal of Open Source Software (JOSS)** | Diamond OA | **None** | Short paper + code review | Almost certainly **out of scope**: JOSS requires software with "demonstrated clear research impact" in a scientific context, "rather than being a one-off tool for a single analysis". A capstone vault is unlikely to qualify. In 2026 JOSS tightened criteria toward "human creativity, design thinking, and demonstrable research impact" in response to generative AI. |

Sources: [cic.iacr.org/page/callforpapers](https://cic.iacr.org/page/callforpapers);
[ieeeaccess.ieee.org/about/article-processing-charges](https://ieeeaccess.ieee.org/about/article-processing-charges/);
[mdpi.com/journal/cryptography/apc](https://www.mdpi.com/journal/cryptography/apc);
[dl.acm.org/journal/tops/author-guidelines](https://dl.acm.org/journal/tops/author-guidelines);
[link.springer.com/journal/13389/how-to-publish-with-us](https://link.springer.com/journal/13389/how-to-publish-with-us);
[joss.theoj.org/about](https://joss.theoj.org/about) and
[JOSS 2026 blog post](https://blog.joss.theoj.org/2026/01/preparing-joss-for-a-generative-ai-future).

**The APC point, bluntly:** IEEE Access at $2,160 and MDPI Cryptography at CHF 1,800 are not realistic for a
self-funding student. IACR CiC ($0), Journal of Cryptographic Engineering (subscription route, $0) and the
ACM venues with an ACM Open institution ($0) are the affordable options. Check whether your university is an
ACM Open participant before choosing an ACM venue — that single fact swings the cost between $0 and $750.

### 2.5 Practitioner / magazine venues

**IEEE Security & Privacy magazine.** Accepts "research articles, case studies, tutorials, and departments".
Wants writing that is "down to earth, practical, and original", understandable to "a broad audience of people
interested in security and privacy". Explicitly **discourages** "narrow technical research papers", "research
lacking experimental validation", and work "better suited for IEEE Transactions journals"; instead it seeks
"general added value" including surveys and tutorials on new technologies. Review is **single-anonymous**
(reviewers know authors). Submission via ScholarOne Manuscripts (IEEE Computer Society is migrating to the
IEEE Author Portal). Hybrid open access — subscription publication is free, OA costs an APC (5% IEEE member /
20% society member discounts). Figures need ≥300 dpi at display size; line art is often redrawn.
**Word limits: UNVERIFIED.** Search snippets gave conflicting numbers (one said 5,500 words; another said
5,000–7,000 for peer-reviewed full papers and 2,000–4,000 for shorter internally-reviewed pieces). Do not
rely on either — the authoritative page is
[computer.org/csdl/magazine/sp/write-for-us](https://www.computer.org/csdl/magazine/sp/write-for-us/14680),
which returned no readable content to me. Sources:
[CFP](https://www.computer.org/digital-library/magazines/sp/cfp-ieee-security-and-privacy),
[IEEE CS author resources](https://www.computer.org/publications/author-resources).

*Assessment:* a genuinely plausible venue for a "here is what migrating a real system to FIPS 203/204/205
actually took" article — but you would rewrite the paper as a practitioner narrative, not submit the technical
paper. Consider it a second product, not the primary one.

**USENIX `;login:` — DEAD. Do not plan around it.** `;login:` moved from print to digital-only open access in
2021 and **`;login:` Online concluded publication in 2025**. Note: I could not fetch
[usenix.org/publications/login](https://www.usenix.org/publications/login) directly (HTTP 403); this is
sourced from search results quoting that page, so treat the exact wording as **partially verified** — but
multiple independent snippets agree it has ceased.

**ACM XRDS: Crossroads, The ACM Magazine for Students.** Quarterly, print and online, for ACM student members,
founded 1994. Publishes "students who submit unsolicited works" alongside invited pieces. Submission is via a
contributions form (`bit.ly/xrdscontribute`) followed by contacting `xrdsmagazine@gmail.com`.
**Word limits, deadlines, review process and any fees: UNVERIFIED** — xrds.acm.org returned HTTP 403 to every
fetch I attempted. Sources: [xrds.acm.org](https://xrds.acm.org/),
[dl.acm.org/magazine/xrds](https://dl.acm.org/magazine/xrds).
*Assessment:* genuinely aimed at students and therefore a realistic place for a well-written 2,000–3,000-word
account of Q-Vault. It is a magazine, not a refereed venue — good for visibility and a CV line, weak as an
academic citation.

### 2.6 Student research competitions (a real option, but check eligibility)

The **ACM Student Research Competition (SRC)** runs at many ACM conferences. Standard rules:
students must be enrolled at the initial submission deadline; **graduate submissions must be the student's
individual work with no supervisor or student co-authors**; **undergraduate submissions may be individual or
team**; work done as an undergraduate can still be entered in the undergraduate category by a first-year
graduate student. Prizes are $500 / $300 / $200 for first/second/third in each category.
Source: [SIGCSE TS 2026 SRC](https://sigcse2026.sigcse.org/track/sigcse-ts-2026-acm-student-research-competition).

**Important caveat for Q-Vault:** the SRC at **SAC 2027** is **graduate-students-only** — "open for graduate
students currently enrolled in University or College" with active ACM *and* SIGAPP student membership
required; abstracts due **2 October 2026**, max 3 pages in ACM camera-ready format, single student author, no
group projects; two rounds (poster judging → top five present orally); winners can apply to the Student Travel
Award Program ([sigapp.org/sac/sac2027/src_program.php](https://www.sigapp.org/sac/sac2027/src_program.php)).
So the SAC route for an undergraduate is the **regular SEC@SAC track or a poster paper**, not the SRC.

I found **no ACM SRC at a dedicated security conference** (CCS, NDSS, USENIX Security). SRCs I confirmed exist
at SIGCSE TS, ICSE, SOSP, CHI, CGO, SC, ASSETS, PACT — none of which is a natural home for Q-Vault. Treat SRC
as a low-priority path unless you are willing to reframe the work for a general-CS venue.

**Conference grants:** ACM CCS provides a Conference Grant covering registration and travel for students
including undergraduates, requiring a CV, a student statement, and an advisor letter justifying financial need
([CCS 2025 student grants](https://www.sigsac.org/ccs/CCS2025/student-conference-grants/); the CCS 2026
equivalent is **UNVERIFIED**). ICISS offers partial travel grants to students with accepted papers.

### 2.7 Not realistic — the top tier, with numbers

These are excellent papers to *read* and terrible papers to *aim at* first. Acceptance rates for 2026 from
[csconfstats.xoveexu.com/conferences](https://csconfstats.xoveexu.com/conferences/):
**IEEE S&P 12.7%**, **USENIX Security 13.2%**, **NDSS 17.9%**; ACM CCS 2026 partial data only.

For completeness, and because their submission requirements set the norms every lower-tier venue imitates
(see §4):

- **IEEE S&P 2027** — the 2026 cycles are closed (Cycle 1 submission 5 Jun 2025; Cycle 2 submission
  13 Nov 2025). Format: up to 13 pages of text plus up to 5 pages for references and appendices, ≤18 total,
  IEEE "compsoc" conference template, US letter. Fully anonymous, self-citations in the third person,
  **artifact repositories must also be anonymised**. A separate **"Ethics considerations" section is
  mandatory**. Vulnerabilities must be disclosed no later than the rebuttal deadline. Accept/Reject only, no
  conditional accepts; accepted papers get published meta-reviews.
  ([sp2026.ieee-security.org/cfpapers.html](https://sp2026.ieee-security.org/cfpapers.html))
- **ACM CCS 2026** — Cycle A abstract 7 Jan / paper 14 Jan 2026; Cycle B abstract 22 Apr / paper 29 Apr 2026,
  artifact deadline 2 May 2026, notification 17 Jul 2026, camera-ready 13 Sep 2026. All passed. acmart
  `sigconf`, ≤12 pages excluding bibliography and appendices, no font or margin changes. "Papers not properly
  anonymized may be rejected without review"; anonymous artifact hosting e.g. `anonymous.4open.science`.
  **Open Science appendix required, and "Artifacts are required for submissions whose contributions
  fundamentally rely on an implementation, experimental evaluation, system, tool, or dataset"** — which is
  exactly Q-Vault's category.
  ([sigsac.org/ccs/CCS2026/call-for/call-for-papers.html](https://www.sigsac.org/ccs/CCS2026/call-for/call-for-papers.html))
- **USENIX Security '26** — Cycle 1 registration 19 Aug / submission 26 Aug 2025; Cycle 2 registration
  29 Jan / submission 5 Feb 2026; final papers 11 Jun 2026. All passed. "All papers MUST comply with the
  unaltered USENIX Security LaTeX template. Any attempts to remove whitespace (e.g., negative vspaces,
  savetrees, titlesec, removing author blocks, etc.) are strictly forbidden." Anonymous submission.
  **Artifact sharing is mandatory**: "Artifacts must be made available during the reviewing process. If they
  cannot be made available during review or after publication, the Open Science appendix must explain the
  reasoning." Three ethics attestations plus a clearly-marked ethics appendix of up to one page. Max seven
  papers per author per cycle.
  ([ieee-security.org/Calendar/cfps/cfp-USENIXSec2026.html](https://www.ieee-security.org/Calendar/cfps/cfp-USENIXSec2026.html))
- **USENIX Security '27** — Cycle 2 mandatory registration **19 Jan 2027**, submission **26 Jan 2027**. Papers
  must be registered a week early with fixed title, fixed full author list including ORCIDs, tentative
  abstract and fixed topics. Open Science Appendix mandatory, listing all artifacts needed to evaluate the
  paper's contribution and how reviewers access each one.
  ([usenix.org/conference/usenixsecurity27/call-for-papers](https://www.usenix.org/conference/usenixsecurity27/call-for-papers))
- **NDSS 2027** — Summer cycle submission 6 May 2026 (passed); **Fall cycle submission 19 Aug 2026 (passed as
  of 2026-09-08)**, camera-ready 6 Jan 2027. ≤13 pages excluding the "Ethics Considerations" section,
  references and appendices; camera-ready ≤18 pages total, which authors may allocate freely. Double-blind.
  Max 6 submissions per author per cycle. A summer-cycle rejection cannot be resubmitted with major overlap in
  the fall cycle. NDSS 2028 dates are **UNVERIFIED**.
  ([ndss-symposium.org/ndss2027/submissions/call-for-papers](https://www.ndss-symposium.org/ndss2027/submissions/call-for-papers/))

**Poster tracks at top venues** are, however, realistic. USENIX Security '26 posters: submit a draft poster PDF
(max 36"×48") or a one-page abstract by **10 July 2026** (passed), decisions 17 July 2026; presenters must
register and attend; the session is pitched at "provocative opinions, interesting preliminary work, or cool
ideas, as well as new or ongoing work"
([usenix.org/conference/usenixsecurity26/call-for-posters](https://www.usenix.org/conference/usenixsecurity26/call-for-posters)
— page returned 403 to direct fetch, details from search results, so **partially verified**).
NDSS also runs a poster track ([ndss26-posters.hotcrp.com](https://ndss26-posters.hotcrp.com/)).

---

## 3. Formats and templates

### 3.1 ACM — `acmart`

- **Current version: 2.20, released 16 August 2026.** ([ctan.org/pkg/acmart](https://ctan.org/pkg/acmart))
- Download: **https://mirrors.ctan.org/macros/latex/contrib/acmart.zip** (14.4 MB)
- Source repository: **https://github.com/borisveytsman/acmart/** (maintainer Boris Veytsman; LPPL 1.3)
- Official ACM landing page: **https://www.acm.org/publications/proceedings-template**
- Overleaf: **https://www.overleaf.com/latex/templates/acm-conference-proceedings-primary-article-template/wbvnghjbzwpc**
  (ACM has partnered with Overleaf to provide the authoring template free)
- Which class option: conference proceedings use **`sigconf`** (most proceedings authors) or `sigplan`.
- **Double-anonymous submission:** `\documentclass[sigconf,anonymous,review]{acmart}` — `anonymous,review`
  anonymises the work and adds line numbers; use `\acmSubmissionID` to print the submission ID on each page.
- Single-column review format: `\documentclass[manuscript]{acmart}`.
- Sources: CTAN page above, plus
  [ACM Primary Article Template](https://www.acm.org/publications/proceedings-template) (the ACM page itself
  returned 403 to my fetch; the sigconf/anonymous/review details come from search results quoting ACM and
  conference guidance and are therefore **partially verified** — confirm in `acmart.pdf` shipped in the zip).

### 3.2 IEEE — `IEEEtran`

- **Current version: 1.8b.** The most recent CTAN announcement is dated **28 August 2015** — this class has
  been stable for a decade, so "1.8b" is not stale, it is simply the current release.
  ([ctan.org/pkg/ieeetran](https://ctan.org/pkg/ieeetran))
- Download: **https://mirrors.ctan.org/macros/latex/contrib/IEEEtran.zip** (1.6 MB)
- Maintainer's homepage: **https://www.michaelshell.org/tex/ieeetran/**
- IEEE conference template page: **https://ieee.org/conferences/publishing/templates.html** — offers LaTeX
  Template Instructions (PDF), a Template ZIP (~700 KB, updated 2024) and LaTeX bibliography files ZIP.
  *(Page not fetchable by me directly; contents per search results — **partially verified**.)*
- Overleaf IEEE official gallery: **https://www.overleaf.com/gallery/tagged/ieee-official**
- IEEE Template Selector: **https://template-selector.ieee.org/** — the IEEE Author Center directs authors
  here to pick a template by publication type ("Use the interactive IEEE Template Selector to find the
  template you need"). The site returned HTTP 418 to my fetch, so its contents are **UNVERIFIED**.
  ([IEEE Author Center article templates](http://journals.ieeeauthorcenter.ieee.org/create-your-ieee-journal-article/authoring-tools-and-templates/tools-for-ieee-authors/ieee-article-templates/))
- **ACSAC pins the version explicitly:** "IEEE double-column format with IEEEtran.cls version 1.8b", US letter,
  strictly enforced with desk-rejection risk.
- IEEE S&P uses the IEEE **"compsoc"** conference template variant.

### 3.3 NDSS

- LaTeX source: **https://www.ndss-symposium.org/wp-content/uploads/bare_conf_NDSS2027.tex**
- Rendered PDF: **https://www.ndss-symposium.org/wp-content/uploads/bare_conf_NDSS2027.pdf**
- US letter, two columns 9.25 in high × 3.5 in wide, Times ≥10 pt with ≥11 pt line spacing, PDF only.
  DOI form `https://dx.doi.org/10.14722/yyy.2027.[23|24]xxx`; NDSS block at the bottom of the first column of
  page 1; page numbers on every page except the title page. Explicit warning: "do not use macros that have
  similar/same names found on other sites since they could differ and result in incorrect formatting."
  ([ndss-symposium.org/ndss2027/submissions/templates](https://www.ndss-symposium.org/ndss2027/submissions/templates/))

### 3.4 Springer LNCS / CCIS

Used by SPACE, ICISS, PQCrypto (LNCS) and MAgiCS (CCIS). SPACE requires the "Official LNCS template" with
unmodified margins; MAgiCS requires "Springer CCIS format". **The exact Springer template download URLs are
UNVERIFIED** — I did not fetch a Springer template page. Get them from the conference's own submission page,
which normally links the current `llncs` bundle.

### 3.5 IACR

- Journal (CiC): the **`iacrcc`** LaTeX class, `\documentclass[version=submission]{iacrcc}`, from
  **publish.iacr.org/iacrcc** ([cic.iacr.org/page/callforpapers](https://cic.iacr.org/page/callforpapers)).
- ePrint: no mandated template; the only formatting rule I confirmed is that the first page must carry title,
  author name(s), and a contact address or affiliation — i.e. **not anonymous**.

### 3.6 Anonymisation — a checklist derived from the CFPs I read

Double-blind is the norm at every refereed venue in §2.1–2.2 (SPACE, SEC@SAC, ACMSE, MAgiCS, ICISS, ACSAC) as
well as the top tier. Concretely, the requirements that recur:

- No author names, affiliations or email addresses anywhere in the PDF (CCS, NDSS, IEEE S&P).
- Cite your own prior work in the **third person** (IEEE S&P, NDSS).
- No acknowledgements that reveal identity or funding source (IEEE S&P).
- **Anonymise the artifact repository too** — IEEE S&P requires it; CCS names
  `anonymous.4open.science` as the mechanism. *For Q-Vault this matters: a GitHub repo with your name and
  commit history will break anonymity.*
- No adding authors after the deadline (NDSS).
- Exceptions: **ACSAC posters are explicitly not anonymous** ("Author names, affiliations, and country
  information are required"), and **ePrint submissions must not be anonymous**.

---

## 4. What this class of paper is expected to contain

There is no single official "systems security paper structure" document I could fetch and quote. What follows
separates (a) the section skeleton, which is convention rather than a rule, from (b) the specific evidentiary
demands that I *did* verify from CFPs, which are enforceable and where papers actually get rejected.

### 4.1 Conventional skeleton (convention — **UNVERIFIED as a written rule anywhere**)

1. **Abstract** — problem, what you built, what you measured, headline numbers.
2. **Introduction** — the migration problem, why existing vaults/HSM workflows don't address it, contributions
   as an explicit bulleted list.
3. **Background** — ML-KEM/FIPS 203, ML-DSA/FIPS 204, SLH-DSA/FIPS 205, RFC 6962 Merkle logs, M-of-N
   approval. Keep it short; reviewers resent tutorials.
4. **Threat model and security goals** — see §4.2, this is the section reviewers attack first.
5. **Design** — architecture: agility layer, multi-signature workflow, hash-chained ledger, transparency log,
   witness, offline verifier. State invariants explicitly.
6. **Implementation** — languages, LOC, which PQClean/reference implementations, key sizes, wire formats,
   engineering pitfalls. This is where an implementation paper earns its keep.
7. **Security analysis** — argue each threat-model goal against the design; state what you do *not* defend
   against.
8. **Evaluation** — see §4.3.
9. **Related work** — position against classical multi-sig vaults, certificate transparency, existing
   crypto-agility frameworks (MAgiCS 2026 proceedings are the obvious recent citations).
10. **Discussion / limitations / lessons learned** — ACSAC explicitly rewards this.
11. **Conclusion**, **References**, then required appendices (see §4.2).

### 4.2 Mandatory appendices and sections — verified, and increasingly enforced

These are now hard requirements at the venues that set norms, and mid-tier venues are adopting them:

- **Ethics considerations.** IEEE S&P 2026 mandates "a separate 'Ethics considerations' section" covering
  vulnerability disclosure, human-subjects approvals and IRB compliance, with disclosure no later than the
  rebuttal deadline. USENIX Security '26 requires three ethics attestations plus "a clearly-marked appendix of
  up to one page on ethical considerations". NDSS 2027 makes it encouraged rather than mandatory but excludes
  it from the page count. CCS 2026 requires a dedicated appendix for papers touching human subjects, user data
  or vulnerability analysis.
  *For Q-Vault:* this section is short and easy — no human subjects, no live-system attacks — but omitting it
  reads as carelessness.
- **Open Science appendix.** USENIX Security '26 and '27 require it: it "must list all artifacts necessary to
  evaluate the contribution of the paper and make clear how the review committees can access each artifact",
  or explain why artifacts cannot be provided. CCS 2026 requires an Open Science appendix and states
  "**Artifacts are required for submissions whose contributions fundamentally rely on an implementation,
  experimental evaluation, system, tool, or dataset**".
  *For Q-Vault:* your contribution is fundamentally an implementation. At CCS-class venues, no artifact means
  no paper. Plan the artifact from the start (§5).

### 4.3 What reviewers demand as evidence

Distilled from the CFPs above plus the artifact-evaluation criteria in §5:

**Threat model.** Reviewers want scope stated before design: which parties are trusted, which are adversarial,
what the adversary can observe and modify, and what is explicitly out of scope. For Q-Vault the interesting
axes are: a malicious/compromised vault operator; fewer than M compromised approvers; a compromised
transparency-log server; a colluding log-and-witness pair; a network adversary; and the standard PQC framing
(a store-now-decrypt-later adversary with a future CRQC). Be explicit that you inherit the security of the
NIST primitives rather than claiming novel cryptographic security.

**Evaluation methodology.** State the hardware, OS, compiler/runtime versions, how many repetitions, what
statistic (mean/median, variance or confidence intervals), and how you controlled for warm-up and noise. This
is the single most common weakness in student implementation papers. USENIX artifact evaluators explicitly
check that documentation gives "exact environment specifications", "complete commands to reproduce each paper
claim", and "time and resource requirements clearly stated" — write the paper so that appendix is easy.

**Comparison against baselines.** An implementation paper with no baseline is a demo. Credible baselines for
Q-Vault: (i) the same workflow with classical ECDSA/Ed25519 signatures and X25519 KEM, giving the true cost of
migration — this is the headline result a crypto-agility venue wants; (ii) ML-DSA vs SLH-DSA on the same
operations, showing the signature-size/speed trade-off that motivates agility; (iii) ledger/log verification
cost vs log size, showing the RFC 6962 inclusion/consistency proofs behave logarithmically. Report artifact
sizes (signature, key, checkpoint bytes) as first-class results, not footnotes — for PQC migration, bytes on
the wire are often the finding.

**Reproducibility artifacts.** See §5. Q-Vault has an unusual advantage here: a **dependency-free offline
verifier** is close to an ideal artifact — it is small, it has no environment dependencies, and it lets a
reviewer independently confirm the transparency-log claims. Lead the artifact appendix with it.

**Note on IEEE S&P's stated bar for the magazine** (a different animal from the symposium): it rejects
"research lacking experimental validation" outright — a useful reminder that measured numbers, not
architecture diagrams, are what makes this paper publishable anywhere.

---

## 5. Artifact evaluation

### 5.1 Which venues run it

From [secartifacts.github.io](https://secartifacts.github.io/), the community hub for security artifact
evaluation, formal AE runs at: **ACSAC** (2017–2025), **CHES** (2021–2025), **NDSS** (2024–2027), **PETS**
(2020–2026), **IEEE S&P** (2026), **SysTEX** (2024–2026), **USENIX Security** (2020–2026), **USENIX
VehicleSec** (2026), **WOOT** (2019–2025). The site also indexes artifacts released without formal evaluation
at ACM CCS and IEEE S&P via a tool called ArtiFinder. ACM CCS runs its own artifact evaluation
([CCS 2026 call for artifacts](https://www.sigsac.org/ccs/CCS2026/call-for/call-for-artifacts.html)).

The stated purpose: "to recognize the authors who have put in the effort to release usable hardware and
software systems as well as to validate the results of the accepted papers."

### 5.2 Badges

**ACM badge set** (policy **version 1.1, dated 24 August 2020**, reproduced by
[SIGIR](https://sigir.org/general-information/acm-sigir-artifact-badging/); the canonical ACM page
[acm.org/publications/policies/artifact-review-and-badging-current](https://www.acm.org/publications/policies/artifact-review-and-badging-current)
returned 403 to me, so version currency is **partially verified** — a search result also surfaced an
"Artifact Review and Badging – Version 1.0 (not current)" page, confirming 1.1 supersedes it):

| Badge | Definition |
|---|---|
| **Artifacts Available** | "applied to papers in which associated artifacts have been made permanently available for retrieval" — permanent online availability with a DOI |
| **Artifacts Evaluated – Functional** | "documented, consistent, complete, exercisable, and include appropriate evidence of verification and validation". Reviewers check completeness/consistency; compilation not necessarily required. A few hours of review |
| **Artifacts Evaluated – Reusable** | "of a quality that significantly exceeds minimal functionality… very carefully documented and well-structured to the extent that reuse and repurposing are facilitated". Code must compile and execute; README with step-by-step deployment; datasets need schema descriptions and example parsers |
| **Results Reproduced** | "main results of the paper have been obtained in a subsequent study by a person or team other than the authors, **using, in part, artifacts provided by the author**" |
| **Results Replicated** | "…independently obtained… **without the use of author-supplied artifacts**". Noted as *not currently implemented* |

**Per ACM policy, a paper receives at most one of Functional and Reusable**
([POPL 2026 AE](https://popl26.sigplan.org/track/POPL-2026-artifact-evaluation), which also phrases Reusable as
requiring "good documentation, good installation instructions, platform compatibility, ease of running the
tool on other examples not in the paper, and making the code available via open source licensing").

**USENIX Security '26 badges:** *Artifacts Available*, *Artifacts Functional*, *Results Reproduced*
([secartifacts.github.io/usenixsec2026/instructions](https://secartifacts.github.io/usenixsec2026/instructions)).

**ACSAC 2026 badges:** *Available*, *Reviewed*, *Reproducible* — awarded as IEEE Xplore badges, with "special
mention during the conference and on the ACSAC webpage"
([acsac.org/2026/submissions/papers/artifacts](https://www.acsac.org/2026/submissions/papers/artifacts/)).

### 5.3 What a submission needs

**Hosting.** For an *Available* badge, artifacts must be on a permanent archival repository — CCS 2026 names
**Zenodo, FigShare, Dryad, Software Heritage**, and explicitly **not GitHub**. USENIX Security '26 repeats
this: "GitHub, GitLab, and personal websites prohibited for permanent storage", with versioning done through
the archival platform's own features. Practically: develop on GitHub, then mint a Zenodo DOI for the
evaluated snapshot.

**Artifact Appendix.** USENIX Security '26 wants a PDF, **max 3 pages recommended**, covering hardware and
software requirements, configuration, the paper's key claims, how to reproduce each one, and how to compare
reproduced output against the published results, plus a README with tutorials and usage guidance. The
conventional section structure — *Abstract; Description & Requirements (including security/privacy/ethical
concerns for evaluators, and access via DOI or stable reference); Set-up; Evaluation workflow (Major Claims,
then Experiments); Notes* — is widely used but I verified it only from secondary/summary sources, so the exact
section names are **partially verified**. The authoritative USENIX guidelines page
([usenixsecurity22/artifact-appendix-guidelines](https://www.usenix.org/conference/usenixsecurity22/artifact-appendix-guidelines))
returned 403 to me.

**Evaluation criteria in practice.** ACSAC's four tests: **Documented** ("An inventory of artifacts is
included, and sufficient description provided to enable the artifacts to be exercised"), **Consistent**
(artifacts relate to the paper and contribute to its main results), **Complete** (all relevant components
except proprietary ones), **Exercisable** (scripts and software execute successfully; data accessible).
USENIX evaluators additionally check for a README with description, compilation and running instructions,
supported environments and configuration; module- and class-level code documentation; that all major
components described in the paper are present; and, for *Results Reproduced*, exact environment
specifications, complete per-claim commands, stated time and resource requirements, and outputs matching the
paper "within reasonable variation"
([secartifacts.github.io/usenixsec2026/guide](https://secartifacts.github.io/usenixsec2026/guide)).

Useful principles from the same evaluator guide: reviewers "should spend time auditing rather than debugging",
authors bear responsibility for working artifacts, and "unreasonable effort requirements justify withholding
badges". Destructive artifacts must be explicitly flagged. AE is **single-blind** — anonymisation is
unnecessary at that stage (it *is* necessary during paper review).

**Process shape.** USENIX Security '26 splits it: **Phase 1 (mandatory)** availability verification after
paper acceptance but before camera-ready; **Phase 2 (optional)** functionality and reproducibility, with a
four-week author/evaluator discussion window. ACSAC 2026 AE: registration 9 Sep, submission 12 Sep, evaluation
15 Sep – 21 Oct, decision 23 Oct 2026, single-blind with interactive reviewer feedback. CCS 2026 AE ran two
cycles: registration 12 Jun / submission 19 Jun / decisions 29 Jul 2026, and registration 11 Sep / submission
18 Sep / decisions 28 Oct 2026. CCS requires a two-step submission (register with abstract, PDF, topics and
conflicts; then submit a stable URL or archive, credentials if needed, badge selections, and a "ready for
review" checkbox), and the package must contain the accepted paper, the artifact, and a README with
"instructions and documentation" for installation, execution and usage. At least one contact author must
respond to evaluator questions throughout.

### 5.4 What Q-Vault should ship

Concretely, and this is worth doing regardless of venue because it doubles as the capstone deliverable:

- A Zenodo-archived snapshot with a DOI (GitHub for development, Zenodo for the badge).
- A README that maps **each numerical claim in the paper** to the exact command that regenerates it.
- The **offline verifier** as the centrepiece — dependency-free means an evaluator can validate the
  transparency-log claims with no environment setup, which is the fastest route to *Functional*.
- Pinned dependency versions and a container image for the benchmark harness, so timing numbers are
  reproducible.
- A small pre-generated log/ledger fixture plus signed checkpoints, so reviewers can verify inclusion and
  consistency proofs without running the full vault.
- Documented hardware and runtime for every benchmark, plus expected run time — evaluators are told to check
  exactly this.

---

## 6. Cost summary (matters for a self-funding student)

| Route | Cost to publish |
|---|---|
| IACR ePrint preprint | **$0** |
| arXiv preprint | **$0** — but blocked by endorsement (§1) |
| IACR Communications in Cryptology | **$0** (diamond OA) |
| Journal of Cryptographic Engineering, subscription route | **$0** |
| ACM venue (SAC, ACMSE, CCS…) at an **ACM Open** institution | **$0** |
| ACM venue, institution *not* in ACM Open, 2027 | **$500** ACM/SIG member, **$750** non-member (subsidised transition rate; 2026 rate was $250/$350) |
| Springer LNCS/CCIS conference (SPACE, ICISS, MAgiCS) | No APC found; you pay **registration** (amounts **UNVERIFIED**) |
| MDPI *Cryptography* | **CHF 1,800** |
| IEEE Access | **$2,160** + tax; **student memberships get no discount** |

ACM's geographic waiver policy gives a 100% waiver for authors in countries covered by ACM's EIFL and
Research4Life agreements and 50% off for lower-middle-income countries; discretionary hardship waivers exist
but "are rare" and "simply sending a message to ACM indicating an inability to pay an APC is typically
insufficient justification"
([ACM geographic waiver policy](https://www.acm.org/publications/policies/policy-on-geographic-apc-waivers-and-discounts),
[ACM Open transition](https://conferences.acm.org)).
**Check your institution's ACM Open status first — it is the difference between $0 and $750.**

---

## 7. What I could not verify

Listed so nothing here is mistaken for confirmed fact:

- **IEEE Security & Privacy magazine word limits.** Conflicting unverified figures (5,500 words vs
  5,000–7,000 peer-reviewed / 2,000–4,000 internally reviewed). The authoritative page
  (`computer.org/csdl/magazine/sp/write-for-us/14680`) returned no readable content.
- **ACM XRDS** submission specifics — word limits, deadlines, review process, fees. `xrds.acm.org` returned
  HTTP 403 on every attempt.
- **`;login:` cessation** — sourced from search snippets quoting `usenix.org/publications/login`, which
  returned 403. The "concluded publication in 2025" claim is consistent across snippets but not directly
  fetched.
- **Springer LNCS / CCIS template download URLs** — get them from the target conference's submission page.
- **MAgiCS 2027, PQCrypto 2027, SVCC 2027, ARES 2027, ACSAC 2027, ICISS 2027, NDSS 2028** — none announced on
  the pages I could reach. All future dates for these are unknown, not guessed.
- **Registration fees** for SPACE, ICISS, MAgiCS, ACSAC and student rates thereof.
- **SPACE 2026 Fellowship** programme terms.
- **ACM APC for TOPS specifically** (journal APCs differ from the conference APC).
- **Whether MAgiCS-style "unpublished" clauses treat an ePrint/arXiv preprint as prior publication** — ask the
  chairs before posting a preprint if MAgiCS becomes the target.
- **CCS 2026 student conference grant** (verified only for CCS 2025).
- **IEEE Template Selector contents** (`template-selector.ieee.org` returned HTTP 418).
- **acmart `anonymous,review` option details** — consistent across secondary sources but confirm against
  `acmart.pdf` in the CTAN zip.
- **ACM badging policy currency** — v1.1 (24 Aug 2020) is the version conferences cite; the canonical ACM page
  was unreachable.

---

## Appendix — every source URL used

arXiv: [blog.arxiv.org 2026-01-21 endorsement policy](https://blog.arxiv.org/2026/01/21/attention-authors-updated-endorsement-policy/) ·
[info.arxiv.org/help/endorsement.html](https://info.arxiv.org/help/endorsement.html) ·
[arxiv.org/category_taxonomy](https://arxiv.org/category_taxonomy) ·
[arxiv.org/list/cs.CR/recent](https://arxiv.org/list/cs.CR/recent)

IACR: [eprint.iacr.org/about.html](https://eprint.iacr.org/about.html) ·
[eprint.iacr.org/operations.html](https://eprint.iacr.org/operations.html) ·
[cic.iacr.org/page/callforpapers](https://cic.iacr.org/page/callforpapers) ·
[cic.iacr.org/page/faq](https://cic.iacr.org/page/faq)

Conferences: [space2026.isec.tugraz.at](https://space2026.isec.tugraz.at/) ·
[space2026-cycle-2.hotcrp.com](https://space2026-cycle-2.hotcrp.com/) ·
[dmi.unict.it/giamp/sac/cfp2027.php](https://www.dmi.unict.it/giamp/sac/cfp2027.php) ·
[sigapp.org/sac/sac2027](https://www.sigapp.org/sac/sac2027/) ·
[sigapp.org/sac/sac2027/src_program.php](https://www.sigapp.org/sac/sac2027/src_program.php) ·
[acmse.net/2027/papers-call](https://acmse.net/2027/papers-call/) ·
[magics-workshop.cs.hs-rm.de](https://magics-workshop.cs.hs-rm.de/) ·
[easychair.org/cfp/MAgiCS26](https://easychair.org/cfp/MAgiCS26) ·
[MAgiCS on NIST PQC forum](https://groups.google.com/a/list.nist.gov/g/pqc-forum/c/29-wFow5Ses) ·
[MAgiCS 2026 CCIS volume](https://link.springer.com/book/9783032289452) ·
[acsac.org/2026/submissions](https://www.acsac.org/2026/submissions/) ·
[acsac.org/2026/submissions/papers](https://www.acsac.org/2026/submissions/papers/) ·
[acsac.org/2026/submissions/posters](https://www.acsac.org/2026/submissions/posters/) ·
[acsac.org/2026/submissions/papers/artifacts](https://www.acsac.org/2026/submissions/papers/artifacts/) ·
[iciss.in/cfp](https://iciss.in/cfp/) ·
[ares-conference.eu](https://www.ares-conference.eu/) ·
[svcc-svcsi.org/post-quantumsecurityworkshop](https://www.svcc-svcsi.org/post-quantumsecurityworkshop) ·
[PQCrypto 2026 on NIST PQC forum](https://groups.google.com/a/list.nist.gov/g/pqc-forum/c/omD5J9dmqbk) ·
[link.springer.com/conference/pqcrypto](https://link.springer.com/conference/pqcrypto)

Top-tier CFPs: [sp2026.ieee-security.org/cfpapers.html](https://sp2026.ieee-security.org/cfpapers.html) ·
[CCS 2026 CFP](https://www.sigsac.org/ccs/CCS2026/call-for/call-for-papers.html) ·
[CCS 2026 call for artifacts](https://www.sigsac.org/ccs/CCS2026/call-for/call-for-artifacts.html) ·
[USENIX Sec '26 CFP mirror](https://www.ieee-security.org/Calendar/cfps/cfp-USENIXSec2026.html) ·
[USENIX Sec '27 CFP](https://www.usenix.org/conference/usenixsecurity27/call-for-papers) ·
[USENIX Sec '26 call for posters](https://www.usenix.org/conference/usenixsecurity26/call-for-posters) ·
[NDSS 2027 CFP](https://www.ndss-symposium.org/ndss2027/submissions/call-for-papers/) ·
[NDSS 2027 templates](https://www.ndss-symposium.org/ndss2027/submissions/templates/) ·
[csconfstats acceptance rates](https://csconfstats.xoveexu.com/conferences/)

Templates: [ctan.org/pkg/acmart](https://ctan.org/pkg/acmart) ·
[mirrors.ctan.org acmart.zip](https://mirrors.ctan.org/macros/latex/contrib/acmart.zip) ·
[github.com/borisveytsman/acmart](https://github.com/borisveytsman/acmart/) ·
[acm.org/publications/proceedings-template](https://www.acm.org/publications/proceedings-template) ·
[Overleaf ACM primary article template](https://www.overleaf.com/latex/templates/acm-conference-proceedings-primary-article-template/wbvnghjbzwpc) ·
[ctan.org/pkg/ieeetran](https://ctan.org/pkg/ieeetran) ·
[mirrors.ctan.org IEEEtran.zip](https://mirrors.ctan.org/macros/latex/contrib/IEEEtran.zip) ·
[michaelshell.org/tex/ieeetran](https://www.michaelshell.org/tex/ieeetran/) ·
[ieee.org/conferences/publishing/templates.html](https://ieee.org/conferences/publishing/templates.html) ·
[IEEE Author Center templates](http://journals.ieeeauthorcenter.ieee.org/create-your-ieee-journal-article/authoring-tools-and-templates/tools-for-ieee-authors/ieee-article-templates/) ·
[Overleaf IEEE official gallery](https://www.overleaf.com/gallery/tagged/ieee-official)

Artifacts: [secartifacts.github.io](https://secartifacts.github.io/) ·
[secartifacts USENIX Sec 2026 instructions](https://secartifacts.github.io/usenixsec2026/instructions) ·
[secartifacts USENIX Sec 2026 index](https://secartifacts.github.io/usenixsec2026/index) ·
[secartifacts USENIX Sec 2026 evaluator guide](https://secartifacts.github.io/usenixsec2026/guide) ·
[POPL 2026 artifact evaluation](https://popl26.sigplan.org/track/POPL-2026-artifact-evaluation) ·
[SIGIR reproduction of ACM badging policy](https://sigir.org/general-information/acm-sigir-artifact-badging/)

Journals & magazines: [ieeeaccess.ieee.org APC](https://ieeeaccess.ieee.org/about/article-processing-charges/) ·
[mdpi.com/journal/cryptography/apc](https://www.mdpi.com/journal/cryptography/apc) ·
[dl.acm.org/journal/tops/author-guidelines](https://dl.acm.org/journal/tops/author-guidelines) ·
[Journal of Cryptographic Engineering](https://link.springer.com/journal/13389/how-to-publish-with-us) ·
[joss.theoj.org/about](https://joss.theoj.org/about) ·
[JOSS 2026 blog](https://blog.joss.theoj.org/2026/01/preparing-joss-for-a-generative-ai-future) ·
[IEEE S&P magazine CFP](https://www.computer.org/digital-library/magazines/sp/cfp-ieee-security-and-privacy) ·
[IEEE CS author resources](https://www.computer.org/publications/author-resources) ·
[usenix.org/publications/login](https://www.usenix.org/publications/login) ·
[xrds.acm.org](https://xrds.acm.org/)

Fees/policies: [ACM geographic APC waivers](https://www.acm.org/publications/policies/policy-on-geographic-apc-waivers-and-discounts) ·
[ACM going fully OA in 2026](https://conferences.acm.org) ·
[ACM Open APC list pricing](https://libraries.acm.org/acmopen/apc-list-pricing) ·
[SIGCSE TS 2026 SRC rules](https://sigcse2026.sigcse.org/track/sigcse-ts-2026-acm-student-research-competition) ·
[CCS 2025 student conference grants](https://www.sigsac.org/ccs/CCS2025/student-conference-grants/)
