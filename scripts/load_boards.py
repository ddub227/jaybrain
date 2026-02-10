"""One-time script to bulk-load JJ's job board URLs into the database."""

import uuid
from jaybrain.config import ensure_data_dirs
from jaybrain.db import init_db, get_connection, insert_job_board

ensure_data_dirs()
init_db()

boards = [
    # Remote-First (priority order)
    ("We Work Remotely", "https://weworkremotely.com", "general", ["remote", "priority"]),
    ("FlexJobs", "https://www.flexjobs.com", "general", ["remote", "priority"]),
    ("RemoteOK", "https://remoteok.com", "general", ["remote", "priority"]),
    ("Remotive", "https://remotive.com", "general", ["remote", "priority"]),
    ("Working Nomads", "https://www.workingnomads.com", "general", ["remote"]),
    ("Nodesk", "https://nodesk.co", "general", ["remote"]),
    ("Remote.co", "https://remote.co", "general", ["remote"]),
    ("Dynamite Jobs", "https://dynamitejobs.com", "general", ["remote"]),
    ("Virtual Vocations", "https://www.virtualvocations.com", "general", ["remote"]),
    ("Jobspresso", "https://jobspresso.co", "general", ["remote"]),
    ("JustRemote", "https://justremote.co", "general", ["remote"]),
    ("Himalayas", "https://himalayas.app", "general", ["remote"]),
    ("DailyRemote", "https://dailyremote.com", "general", ["remote"]),
    ("Remote Rocketship", "https://www.remoterocketship.com", "general", ["remote"]),
    ("Remote 100K", "https://remote100k.com", "general", ["remote"]),
    ("Remote.io", "https://www.remote.io", "general", ["remote"]),
    ("4 Day Week", "https://4dayweek.io", "general", ["remote"]),
    ("Hidden Jobs", "https://hidden-jobs.com", "general", ["remote"]),
    ("Pangian", "https://www.pangian.com", "general", ["remote"]),
    ("PowerToFly", "https://powertofly.com", "general", ["remote"]),
    ("NewGrad Jobs", "https://www.newgrad-jobs.com", "general", ["remote", "entry-level"]),
    ("Skip the Commute", "https://www.skipthecommute.com", "general", ["remote"]),
    # Tech / IT-Specific
    ("BuiltIn Remote", "https://builtin.com/jobs/remote", "niche", ["tech", "remote"]),
    ("Dice", "https://www.dice.com", "niche", ["tech"]),
    ("Wellfound", "https://wellfound.com", "niche", ["tech", "startups"]),
    ("Hired", "https://hired.com", "niche", ["tech"]),
    ("Arc.dev", "https://arc.dev", "niche", ["tech", "remote"]),
    ("Turing", "https://www.turing.com", "niche", ["tech", "remote"]),
    ("Gun.io", "https://gun.io", "niche", ["tech", "freelance"]),
    ("Lemon.io", "https://lemon.io", "niche", ["tech", "freelance"]),
    ("Terminal.io", "https://www.terminal.io", "niche", ["tech", "remote"]),
    # Cybersecurity / InfoSec
    ("CyberSecurity Jobs", "https://www.cybersecurityjobs.com", "niche", ["cybersecurity", "priority"]),
    ("InfoSec Job Board", "https://www.infosecjobboard.com", "niche", ["cybersecurity"]),
    ("InfoSec Jobs Net", "https://infosec-jobs.net", "niche", ["cybersecurity"]),
    ("Hack The Box Jobs", "https://jobs.hackthebox.com", "niche", ["cybersecurity"]),
    ("ClearanceJobs", "https://www.clearancejobs.com", "niche", ["cybersecurity", "clearance"]),
    ("ClearedJobs", "https://clearedjobs.net", "niche", ["cybersecurity", "clearance"]),
    ("USAJOBS Cyber", "https://cybersecurity.usajobs.gov", "niche", ["cybersecurity", "government"]),
    # Government
    ("USAJOBS", "https://www.usajobs.gov", "niche", ["government"]),
    # Major Job Boards
    ("LinkedIn Jobs", "https://www.linkedin.com/jobs", "general", ["major", "remote-filter"]),
    ("Indeed", "https://www.indeed.com", "general", ["major", "remote-filter"]),
    ("Glassdoor", "https://www.glassdoor.com", "general", ["major", "remote-filter"]),
    ("ZipRecruiter", "https://www.ziprecruiter.com", "general", ["major", "remote-filter"]),
    ("SimplyHired", "https://www.simplyhired.com", "general", ["major", "remote-filter"]),
    # Freelance / Contract
    ("Upwork", "https://www.upwork.com", "general", ["freelance", "contract"]),
    ("Fiverr", "https://www.fiverr.com", "general", ["freelance"]),
    ("Toptal", "https://www.toptal.com", "niche", ["freelance", "tech"]),
    ("Contra", "https://contra.com", "general", ["freelance"]),
    ("Freelancer", "https://www.freelancer.com", "general", ["freelance"]),
    ("Guru", "https://www.guru.com", "general", ["freelance"]),
    ("PeoplePerHour", "https://www.peopleperhour.com", "general", ["freelance"]),
    ("SolidGigs", "https://solidgigs.com", "general", ["freelance"]),
    ("Outsourcely", "https://www.outsourcely.com", "general", ["freelance", "remote"]),
    # Design / Creative
    ("Dribbble Jobs", "https://dribbble.com/jobs", "niche", ["design", "creative"]),
    ("Behance Jobs", "https://www.behance.net/joblist", "niche", ["design", "creative"]),
    ("MediaBistro", "https://www.mediabistro.com", "niche", ["media", "creative"]),
    ("Authentic Jobs", "https://authenticjobs.com", "niche", ["design", "tech"]),
    # Developer-Specific
    ("JS Remotely", "https://www.jsremotely.com", "niche", ["dev", "javascript", "remote"]),
    ("Remote Python", "https://www.remotepython.com", "niche", ["dev", "python", "remote"]),
    ("React Native Jobs", "https://reactnativejobs.com", "niche", ["dev", "mobile", "remote"]),
    # Meta-Resources
    ("Awesome Remote Job", "https://github.com/lukasz-madon/awesome-remote-job", "general", ["meta", "resource-list"]),
    ("Freaking Nomads", "https://freakingnomads.com/best-remote-job-boards", "general", ["meta", "resource-list"]),
    ("Remote People", "https://remotepeople.com", "general", ["meta", "resource-list"]),
    ("Job Board Search", "https://jobboardsearch.com", "general", ["meta", "resource-list"]),
]

conn = get_connection()
try:
    for name, url, board_type, tags in boards:
        bid = uuid.uuid4().hex[:12]
        insert_job_board(conn, bid, name, url, board_type, tags)
    print(f"Inserted {len(boards)} job boards")

    count = conn.execute("SELECT COUNT(*) FROM job_boards").fetchone()[0]
    print(f"Total boards in DB: {count}")
finally:
    conn.close()
