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
