"""One-time script: Create updated Life Domains Google Doc with JJ's additions."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from jaybrain.gdocs import create_google_doc

CONTENT = r"""# JayBrain Life Domains -- Master Goal Framework

*Last updated: 2026-02-22*
*Status: ACTIVE*

---

## Domain 1: Career -- Break Into Tech (HIGHEST PRIORITY)

**Primary Goal:** Land a cybersecurity/IT job (remote preferred, on-prem acceptable as stepping stone)

**Current Status:**
- Industry: transitioning from a tech adjacent role (ATM field inspector)
- Certification: CompTIA Security+ SY0-701 in progress (see Domain 2)
- Portfolio: security homelab blog (ddub227.github.io), Sigma detection rules, JayBrain (open-source MCP server)
- Applications: actively tracking via JayBrain Job Hunter pipeline

**Sub-goals:**
1. Pass CompTIA Security+ (see Domain 2 -- prerequisite)
2. Apply to 5+ jobs per week (Fit Score 4-5 from job tracker)
3. Tailor resume per application (JayBrain resume_tailor)
4. Build interview prep materials for each application
5. Expand professional network (see Domain 5)
6. Continue building portfolio projects (homelab blog posts, GitHub contributions)

**Decision Tree:**
- IF remote job offer -> accept, begin Vietnam planning (Domain 3)
- IF on-prem job offer -> accept as stepping stone, target 6-12 months before converting to remote
- IF multiple offers -> prioritize remote > hybrid > on-prem; prioritize cybersecurity > general IT

**Time Allocation Target:** 20+ hrs/week (applications, networking, interview prep)

**Key Metrics:**
- Applications submitted per week
- Response/interview rate
- Networking events attended per month

---

## Domain 2: Learning -- CompTIA Security+ SY0-701 (HIGH PRIORITY)

**Primary Goal:** Pass Security+ certification exam

**Target Exam Date: March 1, 2026**

**Current Status:**
- Studying via SynapseForge spaced repetition system
- Practice exam 2/22/26: 73/90 (81.1%) -- on the threshold of passing, need more study
- Plan to take another practice exam next weekend, studying daily to prepare

**Sub-goals:**
1. Achieve 80%+ mastery across all 5 exam domains in SynapseForge
2. Complete practice exams with 85%+ score
3. Schedule and pass the exam

**Exam Domains (SY0-701):**
- 1.0 General Security Concepts (12%)
- 2.0 Threats, Vulnerabilities, and Mitigations (22%)
- 3.0 Security Architecture (18%)
- 4.0 Security Operations (28%)
- 5.0 Security Program Management and Oversight (20%)

**Time Allocation Target:** 15-20 hrs/week (study sessions, practice exams, lab exercises)

**Key Metrics:**
- SynapseForge readiness score
- Concepts at Blaze/Inferno/Forged level
- Practice exam scores
- Days until target exam date

---

## Domain 3: Relocation -- Digital Nomad in Vietnam (LONG-TERM)

**Primary Goal:** Relocate to Vietnam as a digital nomad

**Current Status:**
- Planning phase -- dependent on securing remote work (Domain 1)
- Never been to Vietnam, no specific cities planned, no detailed research yet

**Dependencies:**
- BLOCKED BY: Remote job (Domain 1)
- BLOCKED BY: Sufficient savings (Domain 6)

**Sub-goals:**
1. Research visa options (digital nomad visa, business visa, tourist visa + border runs)
2. Research cost of living (Ho Chi Minh City vs Da Nang vs Hanoi)
3. Research timezone overlap with US employers (Vietnam is GMT+7, 12 hours ahead of EST)
4. Plan logistics: banking (Wise/international account), health insurance, mail forwarding
5. Find indoor car storage locally (see Domain 7)
6. Downsize possessions for nomad lifestyle
7. Establish emergency return plan

**Vision:** No specific expectations. Comfortable living, enjoy exploring, beach access.

**Time Allocation Target:** 2-3 hrs/week (research, planning -- increases as dependencies clear)

**Key Metrics:**
- Remote job secured (yes/no)
- Savings target reached (yes/no)
- Logistics checklist completion %

---

## Domain 4: Professional Network

**Primary Goal:** Build cybersecurity professional network in NC and remote communities

**Current Status:**
- Networking spreadsheet tracked in Google Sheets

**Sub-goals:**
1. Attend 2+ networking events per month (virtual or in-person)
2. Engage in online cybersecurity communities (Reddit, Discord, LinkedIn)
3. Connect with hiring managers and recruiters in Charlotte cybersecurity market
4. Contribute to open-source security projects

**Time Allocation Target:** 3-5 hrs/week

**Key Metrics:**
- Events attended per month
- New meaningful connections per month
- Informational interviews conducted

---

## Domain 5: Finances

**Primary Goal:** Financial runway for career transition and eventual Vietnam relocation

**Current Status:**
- No real savings or savings plan -- need to develop
- Need to research appropriate savings target for remote relocation
- Old "greenbot" expense tracking project exists (C:\Users\Joshua\projects\activeprojects\greenbot) -- needs revival

**Sub-goals:**
1. Track monthly expenses and subscriptions (see Subscription Tracker below)
2. Build emergency fund (3-6 months expenses)
3. Save for Vietnam relocation costs
4. Minimize unnecessary subscriptions
5. Revive greenbot for automated expense tracking

**Subscription Tracker:**

| Service | Cost/mo | Category | Essential? |
|---------|---------|----------|------------|
| Claude Code Max 20x | $200.00 | AI/Productivity | Yes |
| Google One 2TB | $19.99 | Cloud Storage | Yes |
| Anthropic API | ~$10-30 | AI/Productivity | Yes (GramCracker) |
| Verizon cell service | $146.00 | Communications | Yes |
| Bitwarden Premium | $1.67 | Security | Yes |
| **Monthly Total** | **~$378-398** | | |
| **Annual Total** | **~$4,532-4,772** | | |

**Time Allocation Target:** 1-2 hrs/week (budget review, optimization)

---

## Domain 6: Logistics -- Car Storage

**Primary Goal:** Find secure, indoor car storage near Statesville, NC

**Current Status:**
- Actively searching
- Vehicle: 2019 Hyundai Sonata
- Budget: ~$85/month
- Timeline: soon, no hard deadline
- Will also store a few totes/boxes

**Sub-goals:**
1. Research indoor storage facilities within 30 min of Statesville
2. Compare pricing (climate controlled vs basic indoor)
3. Arrange storage for vehicle + small amount of belongings

**Time Allocation Target:** 1-2 hrs total (one-time research task)

---

## Domain 7: Personal Relationships

**Primary Goal:** Maintain and strengthen relationships with loved ones

**Current Status:**
- Lives with mother -- spends ~1 hour/night watching TV together
- Old dog Gyda -- needs love and affection, limited mobility
- Planning for maintaining relationships while abroad (Vietnam)

**Sub-goals:**
1. Track important birthdays and anniversaries (JayBrain event tracker)
2. Research ways to stay connected from Vietnam (timezone-friendly calls, care packages)

**Key Dates:**
| Person | Date | Notes |
|--------|------|-------|
| Mom | November 29 | Born 1955 |
| Corey (older brother) | July 26 | |
| Little brother | February 9 | |

**Time Allocation Target:** Daily (1 hr evening routine with mom is non-negotiable)

---

## Domain 8: JayBrain Development (HOBBY / ONGOING)

**Primary Goal:** Build JayBrain v2 -- proactive life OS agent

**Current Status:**
- JayBrain v1 live on GitHub (ddub227/jaybrain)
- Memory, tasks, SynapseForge, job hunter, GramCracker, browser automation, homelab all functional
- Planning v2: heartbeat daemon, life domains, proactive outreach, conversation archival

**Sub-goals:**
1. Heartbeat daemon (proactive Telegram notifications)
2. Life domains goal tracking engine
3. Conversation archival to Google Docs (2am daily dump)
4. Event discovery integration (web scraper)
5. Time allocation engine
6. PreCompact hook for context preservation
7. Onboarding intake system
8. Personality/companion layer
9. Voice calls (future phase)

**Time Allocation Target:** 5-10 hrs/week (hobby, flexible)

---

## Goal Priority Stack (Ordered)

1. **Security+** -- gate to everything else (TARGET: March 1, 2026)
2. **Get a tech job** -- gate to financial stability and Vietnam
3. **JayBrain v2** -- force multiplier for all other goals (hobby hours)
4. **Professional network** -- supports job search
5. **Finances** -- track and optimize
6. **Car storage** -- one-time task, do when needed
7. **Vietnam planning** -- blocked until remote job secured
8. **Relationships** -- ongoing, parallel

## Goal Conflicts to Monitor

- **Study time vs JayBrain dev time** -- both compete for evening hours. Security+ comes first.
- **On-prem job vs Vietnam timeline** -- on-prem delays Vietnam by 12-18+ months.
- **Current job flexibility vs new job demands** -- current job allows project time; new job may not.
- **Minimizing hardware vs building infrastructure** -- nomad goal conflicts with homelab expansion.

---

*This document is the agent's objective function. JayBrain uses it to prioritize notifications, allocate time recommendations, detect goal conflicts, and measure progress. Update it whenever priorities shift.*
"""

result = create_google_doc("JayBrain Life Domains v2 -- Master Goal Framework", CONTENT)
print(result)
