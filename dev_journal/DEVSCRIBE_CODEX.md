# DevScribe Codex - JayBrain Development Journal Format

Adapted from JJ's LabScribe Codex for software development documentation.

## Purpose

Track every build session with enough detail to understand decisions, learn from troubleshooting, and pick up where we left off - even months later.

## File Structure

```
dev_journal/
├── DEVSCRIBE_CODEX.md                        # This file - format reference
├── DEV_JOURNAL_INDEX.md                       # Master index of all sessions
└── YYYY-MM/
    └── JayBrain_DevJournal_YYYY-MM-DD.md      # Daily entries
```

## Entry Template

```markdown
# [Descriptive Title Summarizing Session]

| Field | Value |
|-------|-------|
| **Focus** | [Technical description] |
| **Files Modified** | [List of files created/modified] |
| **Goal** | [Primary objective] |

---

## Summary
[Overview + key accomplishments as bullet points]

## Architecture Decisions
### [Decision Title]
- **Context:** Why this decision was needed
- **Options Considered:** What alternatives existed
- **Decision:** What was chosen and why
- **Trade-offs:** What we gave up

## Code Written
### [Component/File]
- **Purpose:** What it does
- **Key Design Choices:** Why it was built this way
- **How It Works:** Walkthrough of the logic

## Concepts Learned
### [Concept Name]
- **What it is:** Clear explanation
- **Why it matters:** Relevance to JayBrain
- **Example:** Practical example

## Troubleshooting
### Problem: [Description]
- **Symptoms / Diagnosis / Root Cause / Solution / Lesson**

## Dependencies & Tools
| Tool/Package | Purpose | Why Chosen |
|---|---|---|

## Questions to Research
- [ ] Open questions for future sessions

## Next Steps
- [ ] Follow-up tasks

## Wildcard
[Unexpected discoveries, aha moments, tangential learnings]

## Key Takeaway
> **Insight:** [One sentence - most important lesson]
```

## Rules

1. Only include sections that have content (no empty sections)
2. Beginner-friendly explanations
3. Code blocks always specify language
4. Connect choices to the "why"
5. Include actual code snippets and commands
6. Updated after each implementation session
