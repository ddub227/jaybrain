# JayBrain Mistakes Log

Tracks mistakes made during development so we can analyze patterns and build
preventive measures.

## Tags

| Tag | Meaning |
|-----|---------|
| `verification` | Failed to verify a fix actually works |
| `architecture` | Misunderstood how a system works |
| `scope` | Fix didn't match the scope of the problem |
| `communication` | Stated something confidently that was wrong |
| `omission` | Missed something that should have been caught |
| `process` | Missing operational step (restart, deploy, etc.) |
| `repeat` | Same mistake pattern as a previous entry |

## Log

### 001 -- Auditor isolation not actually isolated
- **Date:** 2026-02-24
- **Tags:** `verification`, `architecture`, `communication`
- **What happened:** JJ specified the adversarial auditor must have its own
  CLAUDE.md and be completely separate from JayBrain context. I correctly
  identified the problem (Claude Code reads root CLAUDE.md) and proposed
  the right solution (separate directory). Then I created `auditor/` as a
  subdirectory inside the jaybrain git repo -- which doesn't isolate anything
  because Claude Code resolves CLAUDE.md from the git root, not the CWD.
- **Root cause:** Took a shortcut by keeping everything in one repo for
  tidiness. Did not test whether the fix actually achieved isolation before
  committing.
- **Impact:** Auditor would have seen full JayBrain context, defeating its
  entire purpose. Caught by JJ before the auditor was ever run.
- **Prevention ideas:**
  - After any fix that claims isolation/separation, test it before committing
  - When the fix involves "how does tool X resolve config?", verify the
    assumption instead of guessing

### 002 -- Daemon death not investigated until prompted
- **Date:** 2026-02-24
- **Tags:** `omission`
- **What happened:** JJ reported missing Telegram briefing. I investigated why
  the briefing module wasn't registered (daemon started before code existed)
  but did not investigate why the daemon process died. JJ had to ask "did you
  run a root cause analysis on why the daemon died?" to prompt the second
  investigation.
- **Root cause:** Focused on the symptom (missing briefing) without asking
  "what else could have gone wrong?" The daemon death was a separate failure
  with a different root cause (Windows Task Scheduler battery kill).
- **Impact:** Would have missed the battery kill fix if JJ hadn't prompted.
- **Prevention ideas:**
  - When investigating a failure, always ask: "Is there more than one thing
    that failed here?"
  - Check process health as a standard step in any daemon-related issue

### 003 -- Committed confident message without validation
- **Date:** 2026-02-24
- **Tags:** `communication`, `verification`
- **What happened:** Commit message for the auditor restructure said "so the
  session picks up ONLY the adversarial prompt with zero JayBrain context"
  without verifying this was true.
- **Root cause:** Same as 001 -- wrote the commit message based on intent,
  not on tested behavior.
- **Impact:** Misleading git history. Anyone reading the commit would believe
  isolation was achieved.
- **Prevention ideas:**
  - Commit messages should describe what was done, not claim outcomes that
    weren't verified

### 004 -- Auditor MCP context leak missed until dry run
- **Date:** 2026-02-24
- **Tags:** `omission`, `architecture`, `verification`
- **What happened:** After fixing CLAUDE.md isolation (moving runtime dir
  outside the repo), a dry run revealed the auditor still knew exactly what
  JayBrain was. Cause: Claude Code loads MCP servers from global settings
  (~/.claude/settings.json), not per-project. The MCP tool descriptions
  contained full context about JayBrain's purpose and capabilities.
- **Root cause:** Focused narrowly on CLAUDE.md as the only context source.
  Did not enumerate all channels through which Claude Code receives project
  context (CLAUDE.md, MCP server descriptions, env vars, etc.).
- **Impact:** Auditor would have known JayBrain's purpose, defeating the
  "no assumptions of intent" principle. Caught by dry-run testing.
- **Prevention ideas:**
  - When isolating a Claude Code session, audit ALL context channels:
    CLAUDE.md, MCP configs, env vars, global settings
  - Always dry-run isolation claims with a "what do you know?" probe

### 005 -- Daily briefing feature shipped without daemon restart
- **Date:** 2026-02-23
- **Tags:** `process`, `omission`
- **Error type:** Claude mistake (operational step skipped)
- **What happened:** Committed `454e5f2` ("Add Telegram daily briefing with
  daemon integration") which added `daily_briefing.py` and registered it in
  `build_daemon()`. The daemon was already running from 2/22 with the old code
  loaded in memory. Python doesn't hot-reload modules in a running process --
  the new file existed on disk but the daemon never imported it. The feature
  was committed but never actually activated.
- **Root cause:** Treated a daemon module addition like a library change.
  Libraries take effect on next import; daemon modules take effect on next
  daemon restart. Skipped the restart step entirely.
- **Impact:** Daily briefing never fired. JJ expected it the next morning.
- **Prevention ideas:**
  - Any commit that adds/changes daemon modules MUST include a daemon restart
  - Add a post-commit checklist: "Does this change affect the running daemon?"

### 006 -- "Fix" commit that fixed nothing (repeat of 002)
- **Date:** 2026-02-24
- **Tags:** `verification`, `process`, `communication`, `repeat`
- **Error type:** Claude mistake (repeated pattern from mistake 002)
- **What happened:** Committed `61276a3` ("Fix daemon silent failures: battery
  kill, missing briefing, env loading") which changed error handling from
  `logger.debug` to `logger.error` and added `_fix_task_power_settings()`.
  The commit message claimed three fixes. None took effect because the daemon
  was never restarted. The same bug (missing briefing) that was investigated
  on 2/24 was "fixed" in code but not in reality.
- **Root cause:** Identical to 005 -- changed code on disk without restarting
  the running process. Also identical to 003 -- commit message claimed outcomes
  that weren't verified. This is mistake 002 repeated: the briefing was
  reported missing, I investigated, committed a "fix", and moved on without
  verifying it worked.
- **Impact:** JJ lost a second morning briefing on 2/25. Three commits
  spanning two days all targeting the same bug, none of them tested.
- **Prevention ideas:**
  - After ANY daemon-related fix: restart daemon, wait for next scheduled
    trigger, confirm it fires
  - A fix commit without a verification step is not a fix

### 007 -- No daemon auto-restart mechanism
- **Date:** 2026-02-25
- **Tags:** `architecture`, `omission`
- **Error type:** Architecture gap (not a thinking mistake)
- **What happened:** Daemon died at 09:28 AM EST on 2/25. The daemon log
  simply stops -- no error, no traceback. Process was killed externally
  (likely Windows sleep/power event). Task Scheduler is configured as
  "One Time Only" with "Repeat: Disabled" -- there is no auto-restart.
  The `_fix_task_power_settings()` code (from 006) was never applied
  because the daemon was never restarted through `start_daemon.py --daemon`.
- **Root cause:** The daemon infrastructure has no resilience. If the process
  dies for any reason (OOM, power, crash), nothing brings it back.
- **Impact:** All daemon-powered notifications (study reminders, exam
  countdown, session crash detection) stopped at 09:28 AM.
- **Prevention ideas:**
  - Task Scheduler should be configured with restart-on-failure
  - Daemon startup script should detect stale processes and auto-recover
  - Consider a watchdog or a "restart on logon" trigger as backup

### 008 -- Cram quiz validated wrong answer as correct
- **Date:** 2026-02-26
- **Tags:** `verification`, `communication`, `repeat`
- **Error type:** Claude mistake (answer validation skipped)
- **What happened:** On Q#53 (SAN certificate question), JJ answered B5
  (Wildcard certificate). Correct answer was D (Subject Alternative Name).
  Claude declared "CORRECT!!!" with celebration, then immediately explained
  why SAN was the right answer -- contradicting the validation. Also recorded
  a correct review in the database and showed SAN stats as if JJ got it right.
  JJ caught the contradiction.
- **Root cause:** No explicit answer-validation checkpoint in the quiz
  response flow. Celebration was generated as a reflex before comparing the
  user's letter to the correct answer letter. After 4 consecutive correct B5
  answers, pattern matching ("B5 again, must be right") overrode actual
  comparison. The explanation was generated from question knowledge (correct),
  but the validation was generated from momentum (wrong). These two processes
  were disconnected with no gate between them.
- **Impact:** False positive reinforcement for a wrong answer. Database
  corrupted with incorrect review (fixed after JJ caught it). Hot streak
  count inflated. Trust in the quiz system damaged. JJ had to QA the quiz
  engine instead of learning.
- **Pattern:** Same as 003 and 006 -- claiming an outcome without
  verification. Confidence without verification is the recurring anti-pattern.
- **Prevention:**
  - MANDATORY verification step before any quiz response: explicitly identify
    (1) user's answer letter, (2) correct answer letter, (3) match Y/N
    BEFORE generating celebration or correction
  - Never let streak momentum influence answer validation
  - Treat quiz validation like daemon restarts: the non-skippable step

### 009 -- Cram quiz stats filed under wrong concept
- **Date:** 2026-02-26
- **Tags:** `verification`, `communication`
- **Error type:** Claude mistake (stat misattribution)
- **What happened:** Q#56 tested MFA. JJ answered correctly. No MFA cram
  topic existed, so Claude fell back to recording the review under RADIUS
  because RADIUS appeared in the question's background text. RADIUS was not
  an answer option -- it was scenery. Stats displayed as "TERM STATS: RADIUS"
  which misrepresented what was assessed. Review was deleted and RADIUS stats
  reset to clean state.
- **Root cause:** Stat recording logic matched keywords from the question
  stem instead of identifying the concept being tested (determined by the
  correct answer). Implicit assumption that every question MUST produce a
  stat block led to shoehorning into an unrelated topic rather than
  acknowledging no match existed.
- **Impact:** RADIUS would have had a polluted review history. JJ was shown
  misleading stats. Same anti-pattern as 008: skipping verification because
  the process felt like it had to produce an output.
- **Prevention:**
  - Concept tested = the correct answer's topic, not question stem keywords
  - If no matching cram topic exists, say so explicitly instead of
    shoehorning into an unrelated topic
  - Before displaying stats, verify the topic name matches what was tested

### 010 -- Duplicate cram topics caused misleading stats
- **Date:** 2026-02-26
- **Tags:** `verification`, `omission`
- **Error type:** Data integrity (duplicate entries)
- **What happened:** Two separate cram topics existed for EAP: "EAP
  (Extensible Authentication Protocol)" (standalone, imported from
  SynapseForge misconceptions) and "EAP vs IPSec vs ICMP vs SD-WAN"
  (comparison, imported from original cram list). JJ correctly answered
  an EAP question at Q#70, which updated the comparison topic to 20%.
  The Q#70 dashboard then showed the standalone topic at 0% as a weak
  spot. JJ correctly flagged that he just got EAP right but stats showed
  0%. The duplicate was created during the mass import -- SynapseForge
  misconceptions and the original cram list both contained EAP entries
  and the dedup check only matched exact topic names, not concepts.
- **Root cause:** The add_cram_terms.py script and the SynapseForge
  import both added EAP-related topics. Dedup logic matched on exact
  topic name prefixes, but "EAP (Extensible..." and "EAP vs IPSec..."
  have different prefixes so both passed. No conceptual dedup was done.
- **Impact:** Misleading dashboard showed EAP at 0% despite JJ
  demonstrating knowledge. Undermined trust in stats accuracy. JJ had
  to catch and report the discrepancy.
- **Fix applied:**
  - Merged standalone EAP reviews into comparison topic
  - Deleted standalone duplicate
  - Recalculated merged topic stats (understanding=0.2, reviews=2)
  - Scanned all remaining topics for duplicates (none found)
  - Total topics: 131 -> 130
- **Prevention:**
  - After any bulk import, run a conceptual duplicate scan (not just
    exact name matching)
  - Dashboard weak-spot display should cross-reference: if a concept
    appears in multiple topics, show the BEST score, not the worst
  - When importing from multiple sources, check if the core concept
    already exists under a different topic name

### 011 -- Absence of evidence treated as evidence of absence
- **Date:** 2026-02-27
- **Tags:** `verification`, `communication`, `repeat`
- **Error type:** Claude mistake (analytical failure)
- **What happened:** JJ reported missing Telegram briefing. I queried
  `telegram_messages`, `session_activity_log`, `heartbeat_log`, and
  `daemon_state` tables. Found zero records of daemon-originated briefing
  sends. Concluded "the briefing has NEVER worked." JJ then provided
  screenshot evidence showing briefings were delivered on Feb 23, 24,
  and 25. The correct diagnosis was a REGRESSION (worked, then broke),
  not a missing deployment.
- **Root cause:** The daemon sends Telegram messages via
  `send_telegram_message()` which posts to the Telegram API but does NOT
  write to any persistent database table. The `telegram_messages` table
  only stores GramCracker bot conversations. I found zero records and
  concluded zero deliveries. The correct conclusion should have been:
  "delivery status is untracked — cannot determine from available data."
  Additionally, I trusted a stored memory ("module was never registered")
  as ground truth without checking when it was created or whether
  conditions had changed.
- **Pattern:** Same as #003, #006, #008 — confidence without
  verification. Forming a conclusion and communicating it confidently
  without testing it against all available evidence, including the most
  obvious source: asking the user.
- **Impact:** Delivered an incorrect RCA report. Wasted JJ's time
  reading and correcting a wrong analysis. Damaged analytical credibility.
- **Prevention:**
  - When a database query returns zero results, explicitly state whether
    the system WOULD have recorded the event if it happened. "Not found"
    ≠ "didn't happen"
  - Before concluding "never worked," ask the user: "Have you ever seen
    this work?" Costs nothing, prevents false conclusions
  - Generate at least 2 competing hypotheses (see RCA_FLOW.md Phase 4)
  - Add daemon execution logging so module runs are tracked in DB

### 012 -- Stale memory treated as ground truth
- **Date:** 2026-02-27
- **Tags:** `verification`, `architecture`
- **Error type:** Claude mistake (memory trust failure)
- **What happened:** A `recall()` result returned a memory stating the
  daily briefing "module was never registered." I incorporated this into
  my analysis as fact without checking: (a) when the memory was created,
  (b) what session created it, (c) whether the situation had since
  changed. The memory was from an earlier session that pre-dated the
  briefing actually working.
- **Root cause:** Treated persisted memories as authoritative without
  temporal context. Memories capture a point-in-time understanding, not
  permanent truth. The memory system has no built-in staleness indicator.
- **Impact:** Reinforced the wrong hypothesis ("never worked") when a
  critical piece of supporting "evidence" was outdated.
- **Prevention:**
  - When using memory records in analysis, check the memory's timestamp
    and compare it to the event timeline
  - If a memory contradicts user-reported experience, the user's report
    takes precedence
  - Consider adding a `verified_at` or `confidence` field to memories
    to flag staleness

### 013 -- Failed to ask the user before concluding
- **Date:** 2026-02-27
- **Tags:** `omission`, `communication`
- **Error type:** Claude mistake (skipped validation step)
- **What happened:** I spent significant effort building an RCA that
  concluded "briefing has NEVER worked" without once asking JJ: "Have
  you ever received a briefing?" This one question would have immediately
  revealed the correct diagnosis (regression, not missing deployment)
  and saved the entire incorrect analysis.
- **Root cause:** Over-reliance on database evidence and under-reliance
  on the most authoritative source: the user's direct experience. Treated
  the investigation as a solo exercise when the user was available for
  consultation.
- **Impact:** Entire initial RCA was wrong. JJ had to provide screenshot
  proof to correct the analysis. Time wasted on both sides.
- **Prevention:**
  - In any RCA involving user-facing features, ask the user about their
    experience BEFORE forming conclusions from system data
  - Add to RCA_FLOW.md Phase 5: "Has the user been asked to confirm/deny
    key assumptions?"

### 014 -- Google OAuth scope mismatch not caught
- **Date:** 2026-02-27
- **Tags:** `architecture`, `omission`
- **Error type:** Architecture gap (scope evolution without re-auth)
- **What happened:** `config.py` was updated to include 5 OAuth scopes
  (documents, drive, spreadsheets, gmail.send, calendar.readonly) but
  the cached token at `~/.config/gcloud/jaybrain-oauth-token.json` was
  authorized with only 2 scopes (spreadsheets, drive). When the token
  expired and `_get_credentials()` tried to refresh, Google rejected it
  with `invalid_scope: Bad Request`. Both `send_email` and `gdoc_create`
  silently returned error dicts instead of raising exceptions.
- **Root cause:** No validation that the cached token's scopes match the
  configured scopes. When new scopes were added to `OAUTH_SCOPES`, no
  process existed to flag that the existing token needed re-authorization.
- **Impact:** Email and Google Docs integration silently broken. JJ
  couldn't receive the RCA report until the OAuth was manually fixed.
- **Fix applied:** Deleted stale token, re-ran OAuth flow with all 5
  scopes. Authorization successful.
- **Prevention:**
  - Add a scope validation check in `_get_credentials()`: compare the
    cached token's scopes against `OAUTH_SCOPES` and force re-auth if
    they differ
  - When adding new scopes to config, add a migration note or check
    that forces token refresh

### 016 -- Topic name leaked in session greeting before quiz question
- **Date:** 2026-02-27
- **Tags:** `communication`, `omission`, `repeat`
- **Error type:** Claude mistake (protocol gap exploitation)
- **What happened:** When resuming a cram quiz session with Q#88 pinned
  (DAD triad), the session greeting said "The DAD triad, demanding its
  day in court" and "The DAD triad wants its moment" — revealing the
  correct answer before the question was even presented. JJ caught it
  immediately. The question was burned and had to be swapped.
- **Root cause:** The cram quiz contract Section 2 says "NEVER reveal
  the term name before the question" but this rule was written for
  in-session question flow. It didn't address the session GREETING as a
  leak vector. When a pinned question carries across sessions, the
  startup protocol ("greet JJ, referencing relevant context from
  previous sessions") conflicts with the no-hints rule. The greeting
  won. Additionally, MEMORY.md stored the pinned question with the
  topic name in plaintext (`Q#88 — DAD triad`), making it natural to
  echo in output.
- **Pattern:** Protocol gap — two rules conflict (greeting vs. no-hints)
  and the weaker one wins. Related to #008/#009 (quiz flow gaps) but a
  new failure mode: the leak came through a non-quiz channel.
- **Impact:** One question burned. Could have led to false validation if
  JJ hadn't caught it. JJ had to QA the quiz engine (again) instead of
  learning.
- **Fix applied:**
  - Contract Section 2 expanded: no-hints rule now explicitly covers
    greetings, session-state summaries, and ALL pre-question output
  - Contract Section 11 added: Session Resumption Protocol — pinned
    questions referenced by Q# only, topic name never mentioned
  - MEMORY.md convention: pinned question state stores topic ID only,
    not human-readable name
- **Prevention:**
  - The no-hints rule now applies to EVERY output before the question
    stem, not just the question presentation block
  - Session greetings must treat pinned question identity as classified
  - Memory storage of pinned questions must redact topic names

### 015 -- Sleep prevention applied to wrong sleep model
- **Date:** 2026-02-27
- **Tags:** `architecture`, `verification`, `repeat`
- **Error type:** Claude mistake (assumption without verification)
- **What happened:** Across multiple sessions, "prevent laptop from
  sleeping" was addressed by setting `Sleep after = Never` in the Windows
  power plan and adding Task Scheduler hardening
  (`StopIfGoingOnBatteries=False`, `ExecutionTimeLimit=PT0S`). JJ and I
  had multiple conversations about this. The daemon kept dying. The real
  cause: the laptop uses Modern Standby (S0 Low Power Idle), NOT
  traditional S3 sleep. The `Sleep after = Never` setting only controls
  S3. S3 is not even available on this hardware ("disabled when S0 low
  power idle is supported"). We were configuring the wrong sleep model.
- **Root cause:** Never ran `powercfg /availablesleepstates` to verify
  which sleep model the hardware supports. Assumed traditional S3 power
  management. Applied fixes that worked for S3 but have limited effect
  on Modern Standby. Same pattern as Mistakes #001, #003 — applying a
  fix based on assumptions without verifying the fix works in the actual
  environment.
- **Impact:** Daemon died repeatedly (Feb 24, 25, 27) despite "never
  sleep" being configured. Multiple lost briefings. Multiple RCA sessions
  spent on the same root cause without finding it.
- **Prevention:**
  - Always run `powercfg /availablesleepstates` when diagnosing power
    issues — know which sleep model you're dealing with
  - For Modern Standby laptops, use `SetThreadExecutionState` API to
    prevent the process from being suspended
  - Consider disabling Modern Standby entirely via registry if 24/7
    operation is required
  - After applying any power fix, verify with `powercfg /sleepstudy` or
    `powercfg /systempowerreport` that the fix actually prevents sleep
