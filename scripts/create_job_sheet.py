"""Create a Google Sheet with Security+ job listings near Statesville, NC.

One-time script -- run and discard. v2: validated URLs only.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from jaybrain.gdocs import _get_credentials, _get_sheets_service, _get_drive_service, register_sheet_in_index
from jaybrain.config import GDOC_SHARE_EMAIL, GDOC_FOLDER_ID

SPREADSHEET_ID = os.environ.get("JOB_SHEET_SPREADSHEET_ID", "")

HEADERS = [
    "Company", "Job Title", "Location", "Distance",
    "Salary", "Work Mode", "Experience", "Sec+ Status",
    "Fit", "Link Status", "URL", "Notes"
]

# CLEANED DATA: Only verified-active or high-confidence listings
# Link Status: VERIFIED = confirmed active | LIKELY = site blocked verification but search confirms | GENERIC = careers page
JOBS = [
    # === FIT SCORE 5: APPLY NOW ===
    ["Corvid Technologies", "HPC Systems Administrator", "Mooresville, NC", "~20 min",
     "Not listed", "On-site", "Entry (2+ yrs IT)",
     "REQUIRED", "5", "LIKELY",
     "https://www.linkedin.com/jobs/view/hpc-systems-administrator-at-corvid-technologies-4366198372",
     "Security+ EXPLICITLY required. Security clearance required. Closest to Statesville."],

    ["Apex Systems (bank client)", "Tier 1 SOC Analyst", "Charlotte, NC", "~40 min",
     "$41-$43/hr (~$85K)", "Hybrid (12-mo contract)", "Entry",
     "Typically expected", "5", "VERIFIED",
     "https://www.apexsystems.com/job/3021139_usa/soc-analyst",
     "Posted 2/12/2026. Contract-to-hire at major bank. Verify Charlotte vs AZ location with recruiter."],

    ["Honeywell", "IT/Cyber Engineer & Data Science - Recent Grad", "Charlotte, NC", "~40 min",
     "$75,000-$105,500", "On-site", "Entry (recent grad)",
     "Not confirmed", "5", "VERIFIED",
     "https://www.thefreshdev.com/job/information-systems-it-cyber-engineer-data-science-recent-grad-full-time-honeywell-2943",
     "Bachelor's in CS/Cyber/IT/MIS. Graduation Aug 2025-May 2026. Apply via Honeywell Workday."],

    ["FBI", "Special Agent - Cybersecurity/Technology", "Charlotte, NC", "~40 min",
     "$99,461-$128,329", "On-site", "Mid (degree + 2 yrs)",
     "Certs valued", "5", "VERIFIED",
     "https://www.usajobs.gov/job/847989800",
     "Open 12/31/2025 - 12/30/2026. Bachelor's + 2 yrs exp. Background/polygraph/urinalysis."],

    ["KPMG", "Associate, OT Cybersecurity", "Charlotte, NC", "~40 min",
     "$73,000-$112,000", "Not specified", "Entry-Mid",
     "Not confirmed", "5", "VERIFIED",
     "https://www.kpmguscareers.com/jobdetail/?jobId=130480",
     "DEADLINE: February 28, 2026. IEC 62443, NIST CSF 2.0. Apply ASAP."],

    ["SMBC", "Cyber Security Analyst - Vuln Mgmt (Associate)", "Charlotte, NC", "~40 min",
     "$97,000-$154,000", "Hybrid", "Mid (2+ yrs)",
     "Not confirmed", "5", "VERIFIED",
     "https://careers.smbcgroup.com/smbc/job/Charlotte-Cyber-Security-Analyst-Vulnerability-Management-Associate-NC-28202/1325354300/",
     "SOC team. Defender, Wiz, Qualys, CrowdStrike. Requisition ID 6317."],

    # === FIT SCORE 4: STRONG FIT ===
    ["Deloitte", "Cyber Data & Infrastructure Security Eng Developer", "Charlotte, NC", "~40 min",
     "$80,000-$148,000", "Hybrid/Remote", "Entry-Mid",
     "YES - Sec+ qualifying cert", "4", "VERIFIED",
     "https://apply.deloitte.com/en_US/careers/JobDetail/Cyber-Data-and-Infrastructure-Security-Engineering-Developer/322551",
     "Deadline May 1, 2026. Risk & Financial Advisory. Security+ listed alongside CISSP/CISM."],

    ["TD Bank", "Information Security Analyst I - Cyber Incident & Forensics", "Charlotte, NC", "~40 min",
     "$57,000-$99,000", "Not specified", "Entry (1 yr exp)",
     "Industry certs valued", "4", "LIKELY",
     "https://td.wd3.myworkdayjobs.com/en-US/TD_Bank_Careers/job/Information-Security-Analyst-I--US--Cybersecurity-Incident---Forensics_R_1389597",
     "Level I = entry. Bachelor's in IT/Cyber/CS. 1 year exp or equivalent training."],

    ["Ally Financial", "SOC L1 Analyst", "Charlotte, NC", "~40 min",
     "Not listed", "Contract-to-hire", "Entry",
     "Not confirmed", "4", "LIKELY",
     "https://www.career.com/job/ally-financial/soc-l1-analyst/j202202102118329828443",
     "DLP/DAR focus. 12+ month contract. May include 3rd shift. Also on Glassdoor."],

    ["Hearst Media Services", "Cybersecurity Audit Analyst", "Charlotte, NC", "~40 min",
     "$66,000-$108,000", "Not specified", "Entry-Mid",
     "Not confirmed", "4", "LIKELY",
     "https://www.glassdoor.com/job-listing/cybersecurity-audit-analyst-hearst-media-services-JV_IC1138644_KO0,27_KE28,49.htm?jl=1010030096161",
     "Internal audit cybersecurity team. Search confirms active as of Feb 2026."],

    ["AIG", "2026 Early Career Technology Analyst", "Charlotte, NC", "~40 min",
     "$86,200-$99,100", "On-site", "Entry (new grad)",
     "Not confirmed", "4", "LIKELY",
     "https://aig.wd1.myworkdayjobs.com/en-US/aig/job/XMLNAME-2026---Early-Career---Technology---Analyst---United-States--Jersey-City--NJ--or-Charlotte--NC-_JR2504979-1",
     "24-month rotation. Cybersecurity track. Starts July 2026."],

    ["Coca-Cola Consolidated", "IT Cyber Security Analyst", "Charlotte, NC", "~40 min",
     "$76,000-$111,000", "Hybrid (3 days on-site)", "Mid (3-5 yrs)",
     "Not confirmed", "4", "LIKELY",
     "https://www.linkedin.com/jobs/view/it-cyber-security-analyst-at-coca-cola-consolidated-4236461313",
     "PCI compliance, incident response, threat monitoring. Active on LinkedIn."],

    ["MorganFranklin Consulting", "SOC Analyst", "Charlotte, NC", "~40 min",
     "~$119,000", "Not specified", "Mid (1+ yrs)",
     "Not confirmed", "4", "LIKELY",
     "https://www.simplyhired.com/job/PlL5-zCqVVivnwa3af2HyGDPm-TB4eWVkNihlEfGNsd8948fao6xPg",
     "Cyber Fusion Center. 24/7 Advanced Threat Detection. Also on Indeed."],

    ["Corvid Cyberdefense", "Junior Security Specialist", "Mooresville, NC", "~20 min",
     "~$66,600-$78,500 (est.)", "Not specified", "Entry-Mid",
     "Not confirmed", "4", "GENERIC",
     "https://www.indeed.com/q-corvid-cyberdefense-l-mooresville,-nc-jobs.html",
     "Search Indeed for current postings. SIEM logs, alert rules. Close to Statesville."],

    ["RSM", "Cloud DevOps Engineer, CyberSecurity Associate", "Charlotte, NC", "~40 min",
     "$85,000-$162,000", "Not specified", "Mid",
     "Not confirmed", "4", "LIKELY",
     "https://rsm.wd1.myworkdayjobs.com/RSMCareers/job/Charlotte/Cloud-DevOps-Engineer--CyberSecurity-Associate_JR115589",
     "Cloud DevOps + Security. Good combo with AWS cert path."],

    ["Wells Fargo", "Information Security Analyst", "Charlotte, NC", "~40 min",
     "Not listed", "Not specified", "Mid",
     "General certs mentioned", "4", "LIKELY",
     "https://www.wellsfargojobs.com/en/jobs/r-286198/information-security-analyst/",
     "Testing security controls, developing security standards. R-286198."],

    # === FIT SCORE 3: GOOD WITH 6-12 MO EXPERIENCE ===
    ["BofA", "Cyber Rotation Program - 2026", "Charlotte, NC", "~40 min",
     "$108,000-$132,000", "On-site", "Entry-Mid (2+ yrs + Master's)",
     "Not confirmed", "3", "LIKELY",
     "https://builtin.com/job/cyber-rotation-program-2026/7417430",
     "Requires Master's + 2 yrs cyber exp. May have recently closed -- check BuiltIn."],

    ["TIAA", "Cybersecurity Analyst - IAM", "Charlotte, NC", "~40 min",
     "~$120,000 median", "On-site", "Mid",
     "Not confirmed", "3", "LIKELY",
     "https://www.ziprecruiter.com/c/TIAA/Job/Cybersecurity-Analyst,-Identity-Access-Management/-in-Charlotte,NC",
     "SailPoint IdentityIQ, SQL, Excel. On ZipRecruiter."],

    ["DHS", "Cybersecurity Service Positions", "Various (incl. NC)", "Varies",
     "Competitive", "Various", "Various",
     "Likely valued", "3", "GENERIC",
     "https://dhscs.usajobs.gov/",
     "Browse and filter on USAJOBS. Multiple roles and levels."],

    ["Trane Technologies", "Cybersecurity roles", "Davidson, NC", "~30 min",
     "Not listed", "On-site", "Various",
     "Not confirmed", "3", "GENERIC",
     "https://ttcareers.referrals.selectminds.com/",
     "OT Cyber and Third Party Risk roles closed; check for new postings. 981 total jobs."],

    ["Booz Allen Hamilton", "Cybersecurity roles", "Charlotte, NC", "~40 min",
     "$43,000-$79,190", "On-site", "Various",
     "YES - required (IAT Level II)", "3", "GENERIC",
     "https://careers.boozallen.com/teams/cyber",
     "Federal contractor. Security+ required for IAT Level II. Browse for Charlotte openings."],

    ["LPL Financial", "Cyber Defense roles", "Charlotte, NC", "~40 min",
     "$93,000-$155,000", "In-Office", "Mid-Senior",
     "Not confirmed", "3", "GENERIC",
     "https://career.lpl.com/",
     "Filter by Technology category (57 jobs). Azure, AWS, Splunk, IR skills."],

    ["Duke Energy", "Cybersecurity Operations roles", "Charlotte, NC", "~40 min",
     "$37K-$124K (level dependent)", "Hybrid", "Entry-Senior",
     "Certs valued", "3", "GENERIC",
     "https://dukeenergy.wd1.myworkdayjobs.com/Search",
     "CSOC Associate/Analyst deadlines passed; check for new postings. Great SOC target."],

    # === FIT SCORE 2: STRETCH / 1-2 YEARS OUT ===
    ["Lowe's", "Sr Analyst, Information Security (Offensive Security)", "Mooresville, NC", "~20 min",
     "$70,700-$180,700", "Hybrid (3 days)", "Senior (4+ yrs)",
     "Not confirmed", "2", "VERIFIED",
     "https://talent.lowes.com/us/en/job/JR-02345522/Sr-Analyst-Information-Security-Offensive-Security",
     "Posted 1/8/2026. Lowe's HQ. Offensive security. Senior but worth bookmarking."],

    ["Lowe's", "Sr Analyst, Information Security (Third-Party Risk)", "Charlotte, NC", "~40 min",
     "$70,700-$170,000", "Hybrid", "Senior (4+ yrs)",
     "Not confirmed", "2", "VERIFIED",
     "https://talent.lowes.com/us/en/job/JR-02071475/Sr-Analyst-Information-Security-Third-Party-Risk-Management",
     "Active listing. GRC/third-party risk focus."],

    ["AT&T", "Lead Cybersecurity - SOC Team Lead", "Charlotte, NC", "~40 min",
     "$141,300-$211,900", "Not specified", "Senior",
     "Not confirmed", "2", "VERIFIED",
     "https://www.att.jobs/job/charlotte/lead-cybersecurity-soc-team-lead/117/91690211872",
     "Posted 2/13/2026. 24x7 SOC leadership. Long-term target."],

    ["Capital One", "Senior Auditor - Cyber Risk & Analysis", "Charlotte, NC", "~40 min",
     "$101,100-$115,400", "Hybrid", "Senior",
     "Not confirmed", "2", "VERIFIED",
     "https://www.capitalonecareers.com/job/mclean/senior-auditor-cyber-risk-and-analysis-technology-audit-hybrid/1732/91458119776",
     "Posted 2/6/2026. Cyber risk and analysis technology audit."],

    ["Spectrum", "Cyber & IT Audit Manager", "Charlotte, NC", "~40 min",
     "Not listed", "Not specified", "Senior",
     "Not confirmed", "2", "VERIFIED",
     "https://jobs.spectrum.com/job/charlotte/cyber-and-it-audit-manager/4673/91807839744",
     "Posted 2/16/2026. Cybersecurity assessments."],

    ["USAA", "Sr Info Security & Privacy Advisor", "Charlotte, NC", "~40 min",
     "$103,450-$197,730", "Hybrid (4 days in-office)", "Senior",
     "Not confirmed", "2", "VERIFIED",
     "https://usaa.wd1.myworkdayjobs.com/USAAJOBSWD/job/Senior-Information-Security---Privacy-Advisor--Risk---Controls_R0115018",
     "Posted 2/17/2026. Risk & controls. DEADLINE ~2/24/2026."],

    ["Wells Fargo", "Sr Info Security Engineer - Threat Monitoring", "Charlotte, NC", "~40 min",
     "$98,000-$141,000", "Hybrid", "Senior",
     "Not confirmed", "2", "LIKELY",
     "https://www.wellsfargojobs.com/en/jobs/r-415576/senior-information-security-engineer-cybersecurity-threat-monitoring/",
     "Cyber Threat Fusion Center. R-415576."],

    ["BofA", "Cyber Crime Specialist", "Charlotte, NC", "~40 min",
     "Not listed", "On-site", "Senior (5+ yrs)",
     "No (CISSP/CISM)", "2", "VERIFIED",
     "https://careers.bankofamerica.com/en-us/job-detail/26002204/cyber-crime-specialist-charlotte-north-carolina-united-states",
     "5+ yrs fraud/risk. MITRE ATT&CK. Financial crimes."],

    ["Truist", "Cybersecurity roles", "Charlotte, NC", "~40 min",
     "$104K-$147K (est.)", "On-site (5 days)", "Mid-Senior",
     "Not confirmed", "2", "GENERIC",
     "https://careers.truist.com",
     "Search for cybersecurity. Risk Officer, Compliance, Sr Auditor positions available."],

    ["Sia Partners", "Cybersecurity Consultant", "Charlotte, NC", "~40 min",
     "$117,000-$121,000", "In-Office", "Mid-Senior",
     "Not confirmed", "2", "VERIFIED",
     "https://www.sia-partners.com/en/career/cybersecurity-consultant",
     "Consulting. Charlotte location confirmed on this URL (not the Sr Consultant one)."],

    ["Pacific Life", "Sr. Network Security Engineer", "Charlotte, NC", "~40 min",
     "$125,000-$153,000", "Hybrid", "Senior",
     "Not confirmed", "1", "GENERIC",
     "https://www.pacificlife.com/home/Careers/locations/charlotte.html",
     "New Charlotte office 2026. Click 'Find Your Opportunity' to search."],
]


def update_sheet():
    creds = _get_credentials()
    if creds is None:
        print("ERROR: Could not get Google credentials.", file=sys.stderr)
        sys.exit(1)

    sheets = _get_sheets_service(creds)

    # Get sheet IDs
    meta = sheets.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
    sheet_id = meta["sheets"][0]["properties"]["sheetId"]
    summary_sheet_id = meta["sheets"][1]["properties"]["sheetId"]

    # Clear existing data
    sheets.spreadsheets().values().clear(
        spreadsheetId=SPREADSHEET_ID,
        range="'Job Listings'!A:Z",
    ).execute()
    sheets.spreadsheets().values().clear(
        spreadsheetId=SPREADSHEET_ID,
        range="'Summary'!A:Z",
    ).execute()

    # Write updated job data
    all_rows = [HEADERS] + JOBS
    sheets.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range="'Job Listings'!A1",
        valueInputOption="USER_ENTERED",
        body={"values": all_rows},
    ).execute()
    print(f"Wrote {len(JOBS)} validated job listings.")

    # Count stats
    verified = sum(1 for j in JOBS if j[9] == "VERIFIED")
    likely = sum(1 for j in JOBS if j[9] == "LIKELY")
    generic = sum(1 for j in JOBS if j[9] == "GENERIC")

    summary_data = [
        ["Security+ Job Search - Statesville, NC Area (VALIDATED)"],
        ["Updated: February 19, 2026 -- URLs verified"],
        [""],
        ["QUICK STATS"],
        ["Total Active Listings", str(len(JOBS))],
        ["VERIFIED (confirmed working link)", str(verified)],
        ["LIKELY (search confirms active, site blocked direct check)", str(likely)],
        ["GENERIC (careers page -- search manually)", str(generic)],
        [""],
        ["BY FIT SCORE"],
        ["Fit 5 - Apply NOW", str(sum(1 for j in JOBS if j[8] == "5"))],
        ["Fit 4 - Strong fit", str(sum(1 for j in JOBS if j[8] == "4"))],
        ["Fit 3 - Good w/ some exp", str(sum(1 for j in JOBS if j[8] == "3"))],
        ["Fit 2 - Stretch/future", str(sum(1 for j in JOBS if j[8] == "2"))],
        ["Fit 1 - Long-term goal", str(sum(1 for j in JOBS if j[8] == "1"))],
        [""],
        ["Sec+ Explicitly Required/Listed", str(sum(1 for j in JOBS if "YES" in j[7].upper() or "REQUIRED" in j[7].upper()))],
        ["Remote/Hybrid Available", str(sum(1 for j in JOBS if "remote" in j[5].lower() or "hybrid" in j[5].lower()))],
        ["Within 20 min of Statesville", str(sum(1 for j in JOBS if "20 min" in j[3]))],
        [""],
        ["URGENT DEADLINES"],
        ["KPMG OT Cybersecurity", "Deadline: Feb 28, 2026"],
        ["USAA Sr InfoSec Privacy", "Deadline: ~Feb 24, 2026"],
        [""],
        ["FIT SCORE LEGEND"],
        ["5", "Apply immediately -- entry-level, Security+ valued"],
        ["4", "Strong fit -- may need minor additional experience"],
        ["3", "Good target with 6-12 months experience"],
        ["2", "Stretch goal / 1-2 years out"],
        ["1", "Long-term aspirational target"],
        [""],
        ["LINK STATUS LEGEND"],
        ["VERIFIED", "Directly confirmed active, working link"],
        ["LIKELY", "Site blocked automated check (403) but web search confirms active"],
        ["GENERIC", "Links to careers page -- search manually for specific role"],
        [""],
        ["REMOVED FROM v1 (expired/broken)"],
        ["Duke Energy CSOC Associate", "Deadline passed 2/1/2026"],
        ["Corvid Technologies Security Specialist", "Position closed"],
        ["Dept of Navy IT Cyber", "Announcement closed"],
        ["TIAA Cybersecurity Analyst II", "Contract ended"],
        ["Trane OT Cyber Security Analyst", "Position closed"],
        ["Strategic Staffing Cyber III", "Listing removed (410)"],
        ["Lowe's Sr Analyst SOC", "Removed 12/2/2024"],
        ["Lowe's Sr Analyst InfoSec (JR-01975529)", "Listing removed (410)"],
        ["SMBC Threat Researcher", "Position filled"],
        ["Ally Financial Principal Cyber", "Deadline passed 1/14/2026"],
        ["Trane Sr Analyst Third Party Risk", "Position closed"],
        ["Deloitte Cyber Analyst (#307110)", "Page not found (404)"],
        ["Iredell County CyberSecurity Analyst", "0 jobs currently posted"],
        ["City of Charlotte Cyber Security Analyst", "No current posting found"],
    ]

    sheets.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range="'Summary'!A1",
        valueInputOption="USER_ENTERED",
        body={"values": summary_data},
    ).execute()

    # Formatting
    requests = [
        # Bold header row
        {
            "repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1},
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": {"red": 0.2, "green": 0.3, "blue": 0.5},
                        "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }
        },
        # Auto-resize columns
        {"autoResizeDimensions": {
            "dimensions": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 12}
        }},
        # Fit Score 5 = green
        {
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [{"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": len(JOBS) + 1}],
                    "booleanRule": {
                        "condition": {"type": "CUSTOM_FORMULA", "values": [{"userEnteredValue": '=$I2=5'}]},
                        "format": {"backgroundColor": {"red": 0.85, "green": 0.95, "blue": 0.85}},
                    },
                },
                "index": 0,
            }
        },
        # Fit Score 4 = light green
        {
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [{"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": len(JOBS) + 1}],
                    "booleanRule": {
                        "condition": {"type": "CUSTOM_FORMULA", "values": [{"userEnteredValue": '=$I2=4'}]},
                        "format": {"backgroundColor": {"red": 0.90, "green": 0.97, "blue": 0.90}},
                    },
                },
                "index": 1,
            }
        },
        # Fit Score 3 = light yellow
        {
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [{"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": len(JOBS) + 1}],
                    "booleanRule": {
                        "condition": {"type": "CUSTOM_FORMULA", "values": [{"userEnteredValue": '=$I2=3'}]},
                        "format": {"backgroundColor": {"red": 1.0, "green": 0.98, "blue": 0.85}},
                    },
                },
                "index": 2,
            }
        },
        # Fit Score 1-2 = light gray
        {
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [{"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": len(JOBS) + 1}],
                    "booleanRule": {
                        "condition": {"type": "CUSTOM_FORMULA", "values": [{"userEnteredValue": '=$I2<=2'}]},
                        "format": {"backgroundColor": {"red": 0.93, "green": 0.93, "blue": 0.93}},
                    },
                },
                "index": 3,
            }
        },
        # VERIFIED = green text in Link Status column
        {
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [{"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": len(JOBS) + 1,
                                "startColumnIndex": 9, "endColumnIndex": 10}],
                    "booleanRule": {
                        "condition": {"type": "TEXT_EQ", "values": [{"userEnteredValue": "VERIFIED"}]},
                        "format": {"textFormat": {"bold": True, "foregroundColor": {"red": 0, "green": 0.5, "blue": 0}}},
                    },
                },
                "index": 4,
            }
        },
        # GENERIC = orange text
        {
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [{"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": len(JOBS) + 1,
                                "startColumnIndex": 9, "endColumnIndex": 10}],
                    "booleanRule": {
                        "condition": {"type": "TEXT_EQ", "values": [{"userEnteredValue": "GENERIC"}]},
                        "format": {"textFormat": {"bold": True, "foregroundColor": {"red": 0.8, "green": 0.4, "blue": 0}}},
                    },
                },
                "index": 5,
            }
        },
        # Bold summary title
        {
            "repeatCell": {
                "range": {"sheetId": summary_sheet_id, "startRowIndex": 0, "endRowIndex": 1},
                "cell": {"userEnteredFormat": {"textFormat": {"bold": True, "fontSize": 14}}},
                "fields": "userEnteredFormat(textFormat)",
            }
        },
        {"autoResizeDimensions": {
            "dimensions": {"sheetId": summary_sheet_id, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 3}
        }},
        # Sort by Fit Score descending
        {
            "sortRange": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 1,
                    "endRowIndex": len(JOBS) + 1,
                    "startColumnIndex": 0,
                    "endColumnIndex": 12,
                },
                "sortSpecs": [{"dimensionIndex": 8, "sortOrder": "DESCENDING"}],
            }
        },
    ]

    sheets.spreadsheets().batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={"requests": requests},
    ).execute()
    print("Applied formatting, conditional colors, and sorting.")
    print(f"\nDONE! Sheet: https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit")


if __name__ == "__main__":
    update_sheet()
