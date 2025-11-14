---
applyTo: 'book/chapters/ch6.md,book/chapters/ch7.md,book/chapters/ch8.md,book/chapters/ch9.md'
---

AI Agent Instructions: Chapters 6–9 (Act II — The Breakdown: Discovery & Damage)

Summary
- This section deepens the conflict and exposes consequences: environmental fallout, goodwill impairments, the protagonist's investigation into the export and the acquisition’s accounting, and the early connections to actors in the protagonist’s homeland.

Group goals
- Intensify the stakes: show environmental damage from the exported equipment and the public relations fallout.
- Start the technical investigation: Kareem has access to system backups, logs, or a contact who helps him access snippets of data.
- Create social friction: contemporary and legacy voices clash (old-timers vs. new executives; local press vs. corporate PR).

Per-chapter guidance
- ch6: Dirt in the Water
  - Purpose: Show early environmental consequences where Kareem’s homeland is impacted by the exported equipment. Add personal stakes (letters from home, childhood contacts).
  - Scenes: a letter, a news article, a friend’s observation; the protagonist is confronted with moral and emotional consequences.
  - Hook: an inconsistency in specs vs. observed damage. The gear used is not the equipment as described; someone is mislabeling or obfuscating.

- ch7: Goodwill
  - Purpose: Introduce corporate financial language publicly (the company’s stock reaction or investor memos) and internal confusion at the plant.
  - Scenes: analyst calls, investor notes, a CFO memo about goodwill, and a manager’s private worry.
  - Hook: a suspicious memo or a consultant’s name appears that links to the CFO’s previous deals.

- ch8: The Backup
  - Purpose: Kareem uses his system knowledge to examine backups, logs, or old contracts and finds anomalies or hidden copies of the spec, a redacted clause, or an export manifest labelled military.
  - Scenes: the act of finding the evidence; use tech detail to be plausible: file names, backup timestamp, log strings.
  - Hook: a clear breadcrumb — an invoice sent to a hidden entity or encryption/obfuscation pointing to malfeasance.

- ch9: A Country on Fire
  - Purpose: Link consequences to the protagonist’s homeland. News and personal accounts show the equipment's effect: environmental damage and societal harm.
  - Scenes: personal letters, a friend’s plea, or an NGO report that corroborates the damage.
  - Hook/Transition: Kareem realizes the export and acquisition may be linked; his personal stakes deepen and he moves into active investigation.

Tone & detail
- Maintain a diary-like, reflective first-person voice but escalate urgency and moral weight.
- For evidence, prefer verifiable, non-technical-but-concrete details more than unrealistic “hack the planet” scenarios: timestamps, mundane file names, small code-ish snippets are enough.

Continuity & fact verification
- References to the CFO, outside consultants, and the acquisition should remain consistent across files. If you introduce a consultant's firm, keep the name the same.
- Date continuity: If you reference a particular quarter or shipment date, ensure it matches earlier references (e.g., the order date listed in ch2).

PR guidelines
- Branch name example: `chapter/ch8-backup-evidence`.
- Commit message: `ch6: add local environmental report & personal letter`.
- PR body: Include the new evidence and list any other chapters that should mention these facts (e.g., ch5 now references a backup file; ch10 later will reference the consultant name).

Editor note
- Do not escalate technical implausibilities—technical data should be small and verifiable, not full intrusion scenes. The plot leverages bureaucracy and mislabeling rather than advanced cybercrime.
