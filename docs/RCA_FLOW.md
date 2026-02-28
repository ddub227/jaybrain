# JayBrain RCA Flow

A mandatory 10-phase root cause analysis process. Every RCA must follow
these phases in order. Each phase has a checkpoint that must pass before
proceeding.

## When to Use

- Any user-reported failure or regression
- Any daemon or automated system failure
- Any time a "fix" doesn't actually fix the problem
- Any time an investigation produces a wrong conclusion

## The 10 Phases

### Phase 1: Incident Detection & Scoping

- What is the observable symptom?
- When was it first noticed? By whom?
- What is the expected vs actual behavior?
- Is this a NEW failure or a REGRESSION of something that worked before?

**CHECKPOINT:** Can I reproduce the symptom or see direct evidence of it?
If relying on user report, confirm the details before proceeding.

### Phase 2: Timeline Construction

- When did it LAST work correctly? (Ask the user if unsure)
- What changed between "last worked" and "first failed"?
- Construct a timeline of all relevant events with timestamps
- Include: code changes, deployments, restarts, config changes, external
  events (power, network, etc.)

**CHECKPOINT:** Does my timeline have gaps? If yes, flag them explicitly
as unknowns. Never fill gaps with assumptions.

### Phase 3: Evidence Collection

- Query ALL available data sources (DB tables, logs, metrics, user reports)
- For each data source, record three things:
  1. What was found
  2. What was NOT found
  3. Whether absence means "didn't happen" or "not tracked"
- Check the user's direct experience — they are the most authoritative
  source for user-facing features

**CHECKPOINT:** For every "not found" result, explicitly state whether
the system WOULD have recorded it if it happened. "Not found in DB" ≠
"never happened."

### Phase 4: Hypothesis Formation

- Generate **at least 2** competing hypotheses
- For each hypothesis, list:
  - What evidence would CONFIRM it
  - What evidence would DISPROVE it
- Consider both "it never worked" AND "it worked then broke" as candidates

**CHECKPOINT:** Do NOT proceed with a single hypothesis. If you can only
think of one, you haven't thought hard enough. Consider asking the user
for their theory.

### Phase 5: Hypothesis Testing

- Test each hypothesis against ALL collected evidence
- Actively look for **disconfirming** evidence (not just confirming)
- Weight user-reported experience heavily — if the user says it worked,
  investigate HOW it worked rather than doubting them

**CHECKPOINT:** Has the user been asked to confirm/deny key assumptions?
If not, ask before proceeding.

### Phase 6: Root Cause Identification

- Apply **5 Whys**: Ask "why?" at least 5 times to reach the systemic cause
- Distinguish between:
  - **Triggering cause** — the immediate event (e.g., daemon died)
  - **Contributing factors** — conditions that enabled it (e.g., no auto-restart)
  - **Systemic root cause** — the architectural gap (e.g., no resilience design)

**CHECKPOINT:** Is this a NEW root cause or a recurrence of a known
pattern? Check `docs/MISTAKES_LOG.md` for previous entries with similar
tags or patterns. If it's a repeat, tag it explicitly.

### Phase 7: Impact Assessment

- What was the actual impact?
- What COULD have happened if not caught?
- Are there other systems affected by the same root cause?
- Is this a one-time event or a recurring pattern?

**CHECKPOINT:** Have related systems been checked for the same failure
mode? (e.g., if daemon module import failed, did ALL post-change modules
fail, or just one?)

### Phase 8: Fix Design

- Propose fix with:
  - What it changes
  - What it prevents
  - What it does NOT address (be explicit about limitations)
- Verify fix doesn't introduce new failure modes
- Consider both immediate fix and long-term prevention

**CHECKPOINT:** Is this fix testable? How will we VERIFY it worked?
Define the test BEFORE implementing.

### Phase 9: Implementation & Verification

- Implement the fix
- **VERIFY it actually works** with a concrete test
- For daemon changes: restart daemon, wait for next scheduled trigger,
  confirm it fires
- For code changes: run the affected code path and observe the result
- A fix without verification is not a fix (see Mistakes #001, #003,
  #005, #006, #008)

**CHECKPOINT:** Can I demonstrate the fix working? Show evidence, not
just "I changed the code."

### Phase 10: Documentation & Pattern Check

- Record in `docs/MISTAKES_LOG.md` if applicable
- Check for pattern matches with previous mistakes:
  - Tag with `repeat` if same pattern as a previous entry
  - Reference the previous entry number
- Update prevention measures if existing ones were insufficient
- Update `MEMORY.md` with new patterns learned

**CHECKPOINT:** Would this mistake be caught by existing prevention
measures? If not, what new measure is needed?

## Quick Reference: Common Anti-Patterns

| Anti-Pattern | Description | Mistakes |
|-------------|-------------|----------|
| Confidence without verification | Claiming an outcome without testing it | #001, #003, #006, #008, #011 |
| Absence = evidence | "Not in DB" treated as "didn't happen" | #011 |
| Single hypothesis | Not considering alternative explanations | #011, #013 |
| Stale memory trust | Treating old memories as current truth | #012 |
| Fix without restart | Changing daemon code without restarting | #005, #006 |
| Skipping the user | Not asking the user before concluding | #013 |
| Silent error handling | try/except that swallows failures | #002, build_daemon() |
