"""Create a Google Sheet with Security+ job listings near Statesville, NC.

One-time script -- run and discard.
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from jaybrain.gdocs import _get_credentials, _get_sheets_service, _get_drive_service, register_sheet_in_index
from jaybrain.config import GDOC_SHARE_EMAIL, GDOC_FOLDER_ID

TITLE = "Security+ Job Listings - Statesville NC Area (Feb 2026)"

# Headers
HEADERS = [
    "Company", "Job Title", "Location", "Distance from Statesville",
    "Salary", "Work Mode", "Experience Level", "Security+ Status",
    "Fit Score", "URL", "Notes"
]

# Deduplicated, compiled job listings from all research agents
# Fit Score: 1-5 (5 = best match for someone with Security+ and limited experience)
JOBS = [
    # --- ENTRY-LEVEL / ACCESSIBLE (Fit Score 4-5) ---
    ["Duke Energy", "Cybersecurity Operations Center Associate", "Charlotte, NC", "~40 min",
     "$18-$31/hr (~$37K-$64K)", "Hybrid/Remote after onboarding", "Entry (0-3 yrs)",
     "Likely valued", "5",
     "https://dukeenergy.wd1.myworkdayjobs.com/nosearch/job/Charlotte-NC/Cybersecurity-Operations-Center-Associate_R38230",
     "Best entry-level SOC fit. Associates degree or HS+2yrs. 24x7 CSOC. May be closed (deadline 2/1)."],

    ["Corvid Technologies", "HPC Systems Administrator", "Mooresville, NC", "~20 min",
     "Not listed", "On-site", "Entry (2+ yrs IT)",
     "REQUIRED", "5",
     "https://www.ziprecruiter.com/c/Corvid-Technologies/Job/HPC-Systems-Administrator/-in-Mooresville,NC",
     "Security+ EXPLICITLY required. Security clearance required. Very close to Statesville."],

    ["Corvid Technologies", "Security Specialist", "Mooresville, NC", "~20 min",
     "Not listed", "On-site", "Entry (2+ yrs IT)",
     "Required (within 1st year)", "5",
     "https://corvidtec.isolvedhire.com/jobs/1489639.html",
     "Security+ required within first year. Clearance eligible. Very close."],

    ["Apex Systems (bank client)", "Tier 1 SOC Analyst", "Charlotte, NC", "~40 min",
     "~$70K-$90K (est.)", "On-site (4 days, Tue-Fri)", "Entry",
     "Typically expected", "5",
     "https://www.apexsystems.com/job/3021139_usa/soc-analyst",
     "18-month contract w/ conversion. 9AM-7PM. Entry-level SOC at major bank."],

    ["Iredell County Government", "CyberSecurity Analyst", "Statesville, NC", "Local",
     "Not listed", "On-site", "Entry-Mid (1-3 yrs)",
     "Likely (govt role)", "5",
     "https://www.governmentjobs.com/careers/IredellCounty",
     "LOCAL to Statesville. Government = Sec+ usually required (DoD 8570). 1-3 yrs exp."],

    ["Honeywell", "IT/Cyber Engineer & Data Science - Recent Grad", "Charlotte, NC", "~40 min",
     "$75,000-$105,500", "On-site", "Entry (recent grad)",
     "Not confirmed", "4",
     "https://www.thefreshdev.com/job/information-systems-it-cyber-engineer-data-science-recent-grad-full-time-honeywell-2943",
     "Recent grad program. Bachelor's in CS/Cyber/IT/MIS. Apply by March 2026."],

    ["Ally Financial", "SOC L1 Analyst", "Charlotte, NC", "~40 min",
     "Not listed", "Contract-to-hire", "Entry",
     "Not confirmed", "4",
     "https://www.glassdoor.com/job-listing/soc-l1-analyst-ally-financial-JV_IC1138644_KO0,14_KE15,29.htm?jl=1009906287141",
     "DLP/DAR focus. 12+ month contract. May include 3rd shift."],

    ["Deloitte", "Cybersecurity Data & AI Consultant", "Charlotte, NC", "~40 min",
     "$80,000-$148,000", "Hybrid/Remote", "Entry-Mid",
     "YES - explicitly listed", "4",
     "https://apply.deloitte.com/en_US/careers/SearchJobs",
     "Security+ listed alongside CISSP/CISM as qualifying cert. Risk & Financial Advisory."],

    ["Deloitte", "Cyber Analyst", "Charlotte, NC", "~40 min",
     "~$85,000", "Hybrid/Remote", "Entry-Mid",
     "Not confirmed", "4",
     "https://apply.deloitte.com/en_US/careers/JobDetail/Deloitte-Cyber-Analyst/307110",
     "Incident response analyst. Deloitte Risk & Financial Advisory practice."],

    ["Booz Allen Hamilton", "Cybersecurity Analyst/Specialist", "Charlotte, NC", "~40 min",
     "$43,000-$79,190", "On-site", "Entry-Mid",
     "YES - commonly required", "4",
     "https://careers.boozallen.com/jobs/search",
     "Federal contractor. Security+ required for IAT Level II compliance. Clearance eligible."],

    ["TD Bank", "Information Security Analyst I - Cyber Incident & Forensics", "Charlotte, NC", "~40 min",
     "$57,000-$99,000", "Not specified", "Entry (1 yr exp)",
     "Industry certs valued", "4",
     "https://www.tealhq.com/job/information-security-analyst-i-us-cybersecurity-incident-forensics_6f4d87ed-a194-470c-9b99-d17c00a4d723",
     "Level I = entry. Bachelor's in IT/Cyber/CS. 1 year experience or equivalent training."],

    ["KPMG", "Associate, OT Cybersecurity", "Charlotte, NC", "~40 min",
     "$73,000-$112,000", "Not specified", "Entry-Mid",
     "Not confirmed", "4",
     "https://www.kpmguscareers.com/jobdetail/?jobId=130480",
     "OT cybersecurity assessments. IEC 62443, NIST CSF 2.0. Associate level."],

    ["Hearst Media Services", "Cybersecurity Audit Analyst", "Charlotte, NC", "~40 min",
     "$66,000-$108,000", "Not specified", "Entry-Mid",
     "Not confirmed", "4",
     "https://www.glassdoor.com/job-listing/cybersecurity-audit-analyst-hearst-media-services-JV_IC1138644_KO0,27_KE28,49.htm?jl=1010030096161",
     "Internal audit cybersecurity team. Assessing risk, strengthening controls."],

    ["Bank of America", "Cyber Rotation Program - 2026", "Charlotte, NC", "~40 min",
     "$108,000-$132,000", "On-site", "Entry-Mid (2+ yrs cyber)",
     "Not confirmed", "3",
     "https://careers.bankofamerica.com/en-us/job-detail/25042043/cyber-rotation-program-2026-multiple-locations",
     "Rotation program. Requires 2+ years cybersecurity experience."],

    ["AIG", "2026 Early Career Technology Analyst", "Charlotte, NC", "~40 min",
     "Not listed", "On-site", "Entry (new grad)",
     "Not confirmed", "3",
     "https://www.glassdoor.com/job-listing/2026-early-career-technology-analyst-aig-JV_IC1138644_KO0,89_KE90,93.htm?jl=1009873502500",
     "24-month rotation program. Cybersecurity track available. Starts July 2026. GPA 3.4+."],

    ["Compusoft Integrated Solutions", "Associate Cybersecurity Engineer", "Charlotte, NC", "~40 min",
     "~$55/hr (~$114K/yr)", "Remote", "Entry-Mid",
     "Not confirmed", "3",
     "https://www.dice.com/jobs/q-cyber+security-l-charlotte,+nc-jobs",
     "12+ month contract. Remote. Assisting InfoSec organization."],

    ["Not specified (staffing)", "Cybersecurity Technical Support Associate", "Charlotte, NC", "~40 min",
     "Not listed", "Remote", "Entry-Mid",
     "Not confirmed", "3",
     "https://www.indeed.com/viewjob?jk=f9fdb26e153e72bb",
     "Remote. Requires Linux experience."],

    # --- FEDERAL / GOVERNMENT ---
    ["Dept. of the Navy", "IT Cybersecurity Specialist (INFOSEC)", "North Carolina", "Varies",
     "Federal GS scale", "On-site", "Mid",
     "Likely required (DoD 8570)", "4",
     "https://don.usajobs.gov/job/791487200",
     "Federal position. DoD 8570 = Security+ required for INFOSEC."],

    ["FBI", "Special Agent - Cyber Division", "Charlotte, NC", "~40 min",
     "$100,000-$130,000", "On-site", "Mid (2+ yrs exp + degree)",
     "Certs valued", "2",
     "https://www.usajobs.gov/job/847989800",
     "Requires bachelor's + 2 yrs work exp. Background check, polygraph, urinalysis."],

    ["DHS", "Cybersecurity Service Positions", "Various (incl. NC)", "Varies",
     "Competitive", "Various", "Various",
     "Likely valued", "3",
     "https://dhscs.usajobs.gov/",
     "DHS Cybersecurity Service. Multiple roles and levels."],

    # --- MID-LEVEL (Fit Score 2-3, good targets in 6-12 months) ---
    ["MorganFranklin Consulting", "SOC Analyst", "Charlotte, NC", "~40 min",
     "~$119,000", "Not specified", "Mid (1+ yrs)",
     "Not confirmed", "3",
     "https://www.indeed.com/viewjob?jk=c4f0b7884736f377",
     "Cyber Fusion Center. 24/7 Advanced Threat Detection. 1+ yrs incident response."],

    ["Duke Energy", "Cybersecurity Operations Center Analyst", "Charlotte, NC", "~40 min",
     "~$82K-$124K", "Hybrid", "Mid (3+ yrs)",
     "Likely valued", "3",
     "https://www.duke-energy.com/our-company/careers",
     "Step up from Associate role. Bachelor's + 3 yrs SOC/sysadmin."],

    ["SMBC", "Cyber Security Analyst - Vulnerability Mgmt (Associate)", "Charlotte, NC", "~40 min",
     "$97,000-$154,000", "Hybrid", "Mid (2+ yrs)",
     "Not confirmed", "3",
     "https://careers.smbcgroup.com/smbc/job/Charlotte-Cyber-Security-Analyst-Vulnerability-Management-Associate-NC-28202/1325354300/",
     "SOC team. Vuln remediation. Defender, Wiz, Qualys, CrowdStrike."],

    ["Coca-Cola Consolidated", "IT Cyber Security Analyst", "Charlotte, NC", "~40 min",
     "$76,000-$111,000", "Hybrid (3 days on-site)", "Mid (3-5 yrs)",
     "Not confirmed", "3",
     "https://www.ziprecruiter.com/c/Coca-Cola-Consolidated,-Inc./Job/IT-Cyber-Security-Analyst/-in-Charlotte,NC?jid=d2b5b2100acf86dc",
     "PCI compliance, incident response, threat monitoring. 4-yr degree preferred."],

    ["LPL Financial", "Cyber Defense Senior Analyst", "Charlotte, NC", "~40 min",
     "$93,000-$155,000", "In-Office", "Mid-Senior",
     "Not confirmed", "2",
     "https://career.lpl.com/",
     "Security event monitoring, SIEM. Azure, AWS, Splunk, Incident Response."],

    ["TIAA", "Cybersecurity Analyst II", "Charlotte, NC", "~40 min",
     "$30.91-$43.60/hr", "Hybrid", "Mid (2+ yrs)",
     "Not confirmed", "3",
     "https://www.talentify.io/job/cybersecurity-analyst-ii-charlotte-north-carolina-us-tiaa-r250400298",
     "7-month engagement. Risk assessments, vulnerability scanning, access log analysis."],

    ["TIAA", "Cybersecurity Analyst - IAM", "Charlotte, NC", "~40 min",
     "~$120,000 median", "On-site", "Mid",
     "Not confirmed", "3",
     "https://www.ziprecruiter.com/c/TIAA/Job/Cybersecurity-Analyst,-Identity-Access-Management/-in-Charlotte,NC",
     "Identity & Access Management. Excel and SQL skills needed."],

    ["Trane Technologies", "OT Cyber Security Analyst", "Davidson, NC", "~30 min",
     "Not listed", "On-site", "Mid",
     "Not confirmed", "3",
     "https://ttcareers.referrals.selectminds.com/jobs/ot-cyber-security-analyst-56233",
     "NIST CSF, SIEM/SOAR (Splunk, LogRhythm, Sentinel). Davidson is close to Statesville."],

    ["Wells Fargo", "Information Security Analyst", "Charlotte, NC", "~40 min",
     "Not listed", "Not specified", "Mid",
     "General certs mentioned", "3",
     "https://www.wellsfargojobs.com/en/jobs/r-286198/information-security-analyst/",
     "Testing security controls, developing security standards."],

    ["City of Charlotte", "Cyber Security Analyst Lead", "Charlotte, NC", "~40 min",
     "Not listed", "On-site", "Mid (3+ yrs)",
     "Not confirmed", "2",
     "https://www.charlottenc.gov/City-Government/City-Jobs",
     "Government. Automating cybersecurity processes."],

    ["RSM", "Cloud DevOps Engineer, CyberSecurity Associate", "Charlotte, NC", "~40 min",
     "$85,000-$162,000", "Not specified", "Mid",
     "Not confirmed", "3",
     "https://rsmus.com/careers.html",
     "Cloud DevOps + Security. Good if pursuing AWS cert too."],

    ["Corvid Cyberdefense", "Junior Security Specialist", "Mooresville, NC", "~20 min",
     "~$66,600-$78,500 (est.)", "Not specified", "Entry-Mid",
     "Not confirmed", "4",
     "https://www.indeed.com/q-corvid-cyberdefense-l-mooresville,-nc-jobs.html",
     "Internal security team. SIEM logs, alert rules. Close to Statesville."],

    ["Corvid Cyberdefense", "Information Security Analyst", "Mooresville, NC", "~20 min",
     "~$72,500 avg", "Not specified", "Mid",
     "Not confirmed", "3",
     "https://www.indeed.com/q-corvid-cyberdefense-l-mooresville,-nc-jobs.html",
     "SIEM analysis, incident identification, security posture enhancement."],

    ["Staffing (via Dice)", "SOC Analyst (Contract)", "Charlotte, NC", "~40 min",
     "$53-$57/hr (~$110K-$119K)", "Hybrid", "Mid",
     "Typically required", "3",
     "https://www.dice.com/jobs/q-soc+analyst-l-charlotte,+nc-jobs",
     "12+ month contract. Multiple openings."],

    ["Strategic Staffing Solutions", "Cybersecurity Analyst III", "Charlotte, NC", "~40 min",
     "$80/hr W2 (~$166K)", "Hybrid (3 days on-site)", "Mid-Senior (4+ yrs)",
     "Not confirmed", "2",
     "https://www.dice.com/job-detail/6b8d26f8-5de2-4807-a870-1cdfd855c258",
     "12+ month contract. SOC, endpoint security, incident management."],

    # --- SENIOR / STRETCH GOALS ---
    ["Lowe's", "Sr Analyst, Information Security (Offensive Security)", "Mooresville, NC", "~20 min",
     "$70,700-$180,700", "Hybrid (3 days)", "Senior (4+ yrs)",
     "Not confirmed", "2",
     "https://talent.lowes.com/us/en/job/JR-02345522/Sr-Analyst-Information-Security-Offensive-Security",
     "Lowe's HQ is very close. Offensive security focus. Senior level."],

    ["Lowe's", "Sr Analyst, Information Security (SOC)", "Mooresville, NC", "~20 min",
     "$70,700-$170,000", "Hybrid", "Senior (4+ yrs)",
     "Not confirmed", "2",
     "https://builtin.com/job/sr-analyst-information-security-security-operations-center-soc/3435113",
     "SOC focused. Lowe's HQ. Senior level but great long-term target."],

    ["Lowe's", "Sr Analyst, Information Security", "Mooresville, NC", "~20 min",
     "$92,300-$175,400", "On-site", "Senior (4+ yrs)",
     "Not confirmed", "2",
     "https://talent.lowes.com/us/en/job/JR-01975529/Sr-Analyst-Information-Security",
     "General infosec. Bachelor's + 4 yrs exp."],

    ["Wells Fargo", "Sr Info Security Engineer - Threat Monitoring", "Charlotte, NC", "~40 min",
     "$98,000-$141,000", "Hybrid", "Senior",
     "Not confirmed", "2",
     "https://www.glassdoor.com/job-listing/senior-information-security-engineer-cybersecurity-threat-monitoring-wells-fargo-JV_IC1138644_KO0,68_KE69,80.htm",
     "Cyber Threat Fusion Center. Network, endpoint, cybersecurity skills."],

    ["SMBC", "Cyber Security Analyst - Threat Researcher", "Charlotte, NC", "~40 min",
     "$97,000-$154,000", "Hybrid", "Senior (3+ yrs dedicated CTI)",
     "Not confirmed", "2",
     "https://careers.smbcgroup.com/smbc/job/Charlotte-Cyber-Security-Analyst-Threat-Researcher-NC-28202/1293334100/",
     "Threat intelligence/hunting. MITRE ATT&CK, Diamond Model expertise."],

    ["AT&T", "Lead Cybersecurity - SOC Team Lead", "Charlotte, NC", "~40 min",
     "$128,400-$216,600", "Not specified", "Senior",
     "Not confirmed", "1",
     "https://www.att.jobs/job/charlotte/lead-cybersecurity-soc-team-lead/117/91690211872",
     "24x7 SOC leadership. Long-term target. Posted 2/13/2026."],

    ["Pacific Life", "Sr. Network Security Engineer", "Charlotte, NC", "~40 min",
     "$125,000-$153,000", "Hybrid", "Senior",
     "Not confirmed", "1",
     "https://www.pacificlife.com/home/Careers/locations/charlotte.html",
     "New Charlotte office opening 2026. Network security focus."],

    ["USAA", "Senior Info Security & Privacy Advisor", "Charlotte, NC", "~40 min",
     "$103,450-$197,730", "Hybrid (4 days in-office)", "Senior",
     "Not confirmed", "1",
     "https://www.complyapply.com/jobs/500585453-senior-information-security-privacy-advisor-risk-controls-at-usaa",
     "Risk & controls. Posted 2/18/2026. Senior level."],

    ["Capital One", "Senior Auditor - Cyber Risk & Analysis", "Charlotte, NC", "~40 min",
     "$101,100-$115,400", "Hybrid", "Senior",
     "Not confirmed", "2",
     "https://www.capitalonecareers.com/job/mclean/senior-auditor-cyber-risk-and-analysis-technology-audit-hybrid/1732/91458119776",
     "Technology audit. Cyber risk focus."],

    ["Ally Financial", "Principal Cyber Security Engineer", "Charlotte, NC", "~40 min",
     "$110,000-$180,000", "Hybrid", "Senior (8+ yrs)",
     "No (prefers CISSP/CISM)", "1",
     "https://ally.avature.net/careers/JobDetail/Principal-Cyber-Security-Engineer/13601",
     "Data analytics and automation. 8+ yrs. Long-term aspirational."],

    ["Parsons Corporation", "Federal Solutions Cybersecurity", "Charlotte, NC", "~40 min",
     "$121,000-$217,000", "Not confirmed", "Mid-Senior",
     "Likely (federal)", "2",
     "https://jobs.parsons.com/career-search",
     "Federal government and financial services security controls."],

    ["Sia Partners", "Senior Consultant - Cybersecurity", "Charlotte, NC", "~40 min",
     "$117,000-$121,000", "In-Office", "Senior",
     "Not confirmed", "1",
     "https://www.sia-partners.com/en/career/senior-cybersecurity-consultant",
     "Consulting. Project management, client relationships."],

    ["Spectrum", "Cyber & IT Audit Manager", "Charlotte, NC", "~40 min",
     "Not listed", "Not specified", "Senior",
     "Not confirmed", "1",
     "https://jobs.spectrum.com/job/charlotte/cyber-and-it-audit-manager/4673/91807839744",
     "Posted 2/16/2026. Cybersecurity assessments."],

    ["Truist", "Cybersecurity Risk Specialist", "Charlotte, NC", "~40 min",
     "~$108K-$147K (est.)", "On-site (5 days)", "Mid-Senior",
     "Not confirmed", "2",
     "https://jobs.truist.com",
     "LOD2 Technology Risk team. Risk oversight."],

    ["Trane Technologies", "Sr Analyst, Cybersecurity Third Party Risk Mgmt", "Davidson, NC", "~30 min",
     "Not listed", "On-site", "Senior",
     "Not confirmed", "2",
     "https://ttcareers.referrals.selectminds.com/jobs/senior-analyst-cybersecurity-third-party-risk-management-58589",
     "Third-party risk. Davidson is close. Good Sec+ stepping stone if GRC focused."],

    ["Bank of America", "Cyber Crime Specialist", "Charlotte, NC", "~40 min",
     "Not listed", "On-site", "Senior (5+ yrs)",
     "No (CISSP/CISM)", "1",
     "https://careers.bankofamerica.com/en-us/job-detail/26002204/cyber-crime-specialist-charlotte-north-carolina-united-states",
     "5+ yrs fraud/risk. MITRE ATT&CK. Financial crimes focus."],
]


def create_sheet():
    creds = _get_credentials()
    if creds is None:
        print("ERROR: Could not get Google credentials.", file=sys.stderr)
        sys.exit(1)

    sheets = _get_sheets_service(creds)
    drive = _get_drive_service(creds)

    # Create the spreadsheet
    spreadsheet_body = {
        "properties": {"title": TITLE},
        "sheets": [
            {
                "properties": {
                    "title": "Job Listings",
                    "gridProperties": {"frozenRowCount": 1},
                },
            },
            {
                "properties": {"title": "Summary"},
            },
        ],
    }

    result = sheets.spreadsheets().create(body=spreadsheet_body).execute()
    spreadsheet_id = result["spreadsheetId"]
    sheet_id = result["sheets"][0]["properties"]["sheetId"]
    summary_sheet_id = result["sheets"][1]["properties"]["sheetId"]
    url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
    print(f"Created spreadsheet: {url}")

    # Build data rows (headers + jobs)
    all_rows = [HEADERS] + JOBS

    # Write job data
    sheets.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range="'Job Listings'!A1",
        valueInputOption="USER_ENTERED",
        body={"values": all_rows},
    ).execute()
    print(f"Wrote {len(JOBS)} job listings.")

    # Write summary sheet
    summary_data = [
        ["Security+ Job Search - Statesville, NC Area"],
        ["Generated: February 19, 2026"],
        [""],
        ["QUICK STATS"],
        ["Total Listings", str(len(JOBS))],
        ["Fit Score 5 (Apply NOW)", str(sum(1 for j in JOBS if j[8] == "5"))],
        ["Fit Score 4 (Strong fit)", str(sum(1 for j in JOBS if j[8] == "4"))],
        ["Fit Score 3 (Good w/ some exp)", str(sum(1 for j in JOBS if j[8] == "3"))],
        ["Fit Score 2 (Stretch/future)", str(sum(1 for j in JOBS if j[8] == "2"))],
        ["Fit Score 1 (Long-term goal)", str(sum(1 for j in JOBS if j[8] == "1"))],
        [""],
        ["Security+ Explicitly Required/Listed", str(sum(1 for j in JOBS if "YES" in j[7].upper() or "REQUIRED" in j[7].upper()))],
        ["Remote/Hybrid Available", str(sum(1 for j in JOBS if "remote" in j[5].lower() or "hybrid" in j[5].lower()))],
        ["Within 20 min of Statesville", str(sum(1 for j in JOBS if "20 min" in j[3] or "Local" in j[3]))],
        ["Within 30 min of Statesville", str(sum(1 for j in JOBS if "20 min" in j[3] or "30 min" in j[3] or "Local" in j[3]))],
        [""],
        ["FIT SCORE LEGEND"],
        ["5", "Apply immediately - entry-level, Security+ valued, accessible"],
        ["4", "Strong fit - may need minor additional experience"],
        ["3", "Good target with 6-12 months experience"],
        ["2", "Stretch goal / 1-2 years out"],
        ["1", "Long-term aspirational target"],
        [""],
        ["TOP PRIORITY APPLICATIONS (Fit Score 5)"],
    ]
    for j in JOBS:
        if j[8] == "5":
            summary_data.append([f"  {j[0]} - {j[1]}", j[2], j[4]])

    summary_data.append([""])
    summary_data.append(["CLOSEST TO STATESVILLE (< 30 min)"])
    for j in JOBS:
        if "20 min" in j[3] or "30 min" in j[3] or "Local" in j[3]:
            summary_data.append([f"  {j[0]} - {j[1]}", j[2], j[4]])

    sheets.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range="'Summary'!A1",
        valueInputOption="USER_ENTERED",
        body={"values": summary_data},
    ).execute()
    print("Wrote summary sheet.")

    # Format the spreadsheet
    requests = [
        # Bold header row
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": 1,
                },
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
            "dimensions": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 11}
        }},
        # Conditional formatting: Fit Score 5 = green
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
        # Conditional formatting: Fit Score 4 = light green
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
        # Conditional formatting: Fit Score 3 = light yellow
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
        # Conditional formatting: Fit Score 1-2 = light gray
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
        # Bold summary title
        {
            "repeatCell": {
                "range": {
                    "sheetId": summary_sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": 1,
                },
                "cell": {
                    "userEnteredFormat": {
                        "textFormat": {"bold": True, "fontSize": 14},
                    }
                },
                "fields": "userEnteredFormat(textFormat)",
            }
        },
        # Auto-resize summary columns
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
                    "endColumnIndex": 11,
                },
                "sortSpecs": [{"dimensionIndex": 8, "sortOrder": "DESCENDING"}],
            }
        },
    ]

    sheets.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": requests},
    ).execute()
    print("Applied formatting and sorting.")

    # Move to JayBrain folder
    if GDOC_FOLDER_ID:
        try:
            file_info = drive.files().get(fileId=spreadsheet_id, fields="parents").execute()
            previous_parents = ",".join(file_info.get("parents", []))
            drive.files().update(
                fileId=spreadsheet_id,
                addParents=GDOC_FOLDER_ID,
                removeParents=previous_parents,
                fields="id, parents",
            ).execute()
            print(f"Moved to JayBrain Drive folder.")
        except Exception as e:
            print(f"Warning: Could not move to folder: {e}", file=sys.stderr)

    # Share with JJ
    if GDOC_SHARE_EMAIL:
        try:
            drive.permissions().create(
                fileId=spreadsheet_id,
                body={
                    "type": "user",
                    "role": "writer",
                    "emailAddress": GDOC_SHARE_EMAIL,
                },
                sendNotificationEmail=False,
            ).execute()
            print(f"Shared with {GDOC_SHARE_EMAIL}")
        except Exception as e:
            print(f"Warning: Could not share: {e}", file=sys.stderr)

    # Register in master index
    register_sheet_in_index(
        spreadsheet_id=spreadsheet_id,
        title=TITLE,
        purpose="Job listings within 1hr of Statesville NC for Security+ holders",
        category="job_search",
    )
    print("Registered in master index.")

    print(f"\nDONE! Sheet URL: {url}")
    return url


if __name__ == "__main__":
    create_sheet()
