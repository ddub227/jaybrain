# SynapseForge Quiz Rules

Loaded when running a quiz session (SynapseForge or cram). These rules are mandatory.

## Question Format

- 1 question per turn, multiple choice A-D
- Always include "E. I don't know" and "F. Question previous question" as options
- Always prefix with all-time question number (e.g. `Q#167`). Derive from `SELECT COUNT(*) FROM forge_reviews WHERE subject_id = ?` + 1. Increment in-session.
- NEVER show term name, objective code, or category labels before the question. No preamble like "this revisits X." Present the scenario cold.
- CRITICAL: Randomize correct answer position across A-D. NEVER let the correct answer be the same letter more than 2 questions in a row. Track and force variation.

## Answer Format

JJ answers `[letter][confidence 1-5]` in one message (e.g. `B4` = answer B, confidence 4). Parse both silently. No separate confidence prompt.

## Mandatory Validation Step

Before generating ANY response, explicitly identify:
1. JJ's answer letter
2. Correct answer letter
3. Match Y/N

NEVER skip this. Momentum, streaks, and pattern-matching must not override the comparison. (See Mistake #008.)

## After Each Answer

- Explain WHY the correct answer is right using vivid analogies and memorable imagery. Vary analogies -- never reuse the same metaphor across concepts.
- ALWAYS explain why each incorrect option (A-D, not E) is wrong. Be specific about what each wrong option actually describes.
- When wrong: explain the misconception and why the wrong answer doesn't fit.
- Silent tracking -- NEVER mention DB updates, mastery deltas, scoring changes, or internal mechanics.
- Immediately present the next question.

## Depth Calibration (Security+ SY0-701)

Test conceptual understanding: what a technology is, why it matters, when to use it, how it compares to alternatives. Do NOT test CLI syntax, configuration steps, or hands-on admin details. The exam tests "which technology solves this problem?" not "how do you configure it?"

## Special Commands

- **F** -- Pin current question. Allow follow-up discussion. Resume with pinned question exactly when JJ is ready.
- **SIDEQUEST** -- Pause quiz, answer JJ's question, resume exactly where left off.
- **TIMEOUT** -- Pause for meta/process discussion, then resume.

## Session Resumption (Pinned Questions)

When resuming a session with a pinned question:
- Reference the pinned question by Q# only -- NEVER say the topic name or any hint before presenting it
- The no-hints rule applies to greetings, session summaries, and ALL pre-question output (see Mistake #016)
- MEMORY.md stores pinned question state as topic ID only, never human-readable name

## Question Selection

Pick from the interleaved study queue: highest priority = high exam weight + low mastery. Mix across objectives -- don't cluster same-topic questions back to back.
