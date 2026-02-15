"""Fix SY0-701 concept coverage: rename, remap objectives, add missing concepts.

Compared against official CompTIA SY0-701 V7 exam objectives PDF.
"""

import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from jaybrain.db import (
    get_connection,
    init_db,
    get_forge_objective_by_code,
    insert_forge_concept,
    link_concept_objective,
    update_forge_concept,
)
from jaybrain.forge import _generate_id, add_concept, link_concept_to_objective

init_db()
conn = get_connection()

# Get subject_id
subject_row = conn.execute("SELECT id FROM forge_subjects LIMIT 1").fetchone()
SUBJECT_ID = subject_row["id"]
print(f"Subject: {SUBJECT_ID}")


# =============================================================================
# PHASE 1: Rename existing concepts (add acronyms / fix names)
# =============================================================================
RENAMES = {
    "Symmetric Encryption": "Symmetric Encryption (AES, 3DES)",
    "Asymmetric Encryption": "Asymmetric Encryption (RSA, ECC, Diffie-Hellman)",
    "Hashing": "Hashing (SHA-256, MD5)",
    "Digital Signature": "Digital Signatures",
    "On-Path Attack (MITM)": "On-Path Attack (MITM / Man-in-the-Middle)",
    "Honeypot / Honeynet / Honeyfile": "Deception Technology (Honeypot, Honeynet, Honeyfile, Honeytoken)",
    "SCAP and Automated Compliance": "Automation and Orchestration",
    "Backup Types": "Backup Strategies (Full, Incremental, Differential)",
    "RAID Levels": "RAID Levels (0, 1, 5, 10)",
    "Secure Boot / TPM / HSM": "Secure Boot and Trusted Execution",
    "Data at Rest vs In Transit vs In Use": "Data States (At Rest, In Transit, In Use)",
}

print("\n--- PHASE 1: Renaming concepts ---")
renamed = 0
for old_name, new_name in RENAMES.items():
    row = conn.execute(
        "SELECT id FROM forge_concepts WHERE term = ?", (old_name,)
    ).fetchone()
    if row:
        update_forge_concept(conn, row["id"], term=new_name)
        print(f"  {old_name} -> {new_name}")
        renamed += 1
    else:
        print(f"  [SKIP] Not found: {old_name}")
print(f"  Renamed: {renamed}")


# =============================================================================
# PHASE 2: Fix objective mappings (move misplaced concepts)
# =============================================================================
# (concept_term_substring, remove_from_code, add_to_code)
REMAPS = [
    # 1.1 -> 1.2 (these are fundamental concepts, not control types)
    ("AAA Framework", "1.1", "1.2"),
    ("CIA Triad", "1.1", "1.2"),
    ("Gap Analysis", "1.1", "1.2"),
    ("Non-repudiation", "1.1", "1.2"),

    # Deception tech belongs under 1.2 per PDF, not 4.1
    ("Deception Technology", "4.1", "1.2"),

    # 3.3 network protocols -> 3.2 (infrastructure) or 4.1 (wireless)
    ("802.1X", "3.3", "3.2"),
    ("DNSSEC", "3.3", "3.2"),
    ("IPsec", "3.3", "3.2"),
    ("TLS 1.3", "3.3", "3.2"),
    ("Certificate Types", "3.3", "1.4"),
    ("Site Survey and Heat Map", "3.3", "4.1"),
    ("Wireless Security Protocols", "3.3", "4.1"),

    # 3.4 data concepts -> 3.3 (data protection)
    ("Data Classification", "3.4", "3.3"),
    ("Data Sovereignty", "3.4", "3.3"),
    ("Data States", "3.4", "3.3"),

    # DLP -> 4.5 per PDF
    ("Data Loss Prevention", "3.4", "4.5"),

    # Data Sanitization -> 4.2 (disposal)
    ("Data Sanitization", "3.4", "4.2"),

    # 4.3 forensics concepts -> 4.8 (incident response)
    ("Chain of Custody", "4.3", "4.8"),
    ("Containment Strategies", "4.3", "4.8"),
    ("Forensic Imaging", "4.3", "4.8"),
    ("Incident Response Phases", "4.3", "4.8"),
    ("Order of Volatility", "4.3", "4.8"),
    ("Playbook/Runbook", "4.3", "4.8"),

    # 4.4 -> 4.8
    ("Legal Hold", "4.4", "4.8"),
    ("e-Discovery", "4.4", "4.8"),

    # 4.5 forensics -> 4.9 (data sources for investigation)
    ("Memory Forensics", "4.5", "4.9"),
    ("Packet Capture", "4.5", "4.9"),

    # Log/NetFlow/SNMP belong under 4.4 (monitoring tools), not 4.2
    ("Log Management", "4.2", "4.4"),
    ("NetFlow", "4.2", "4.4"),
    ("SNMP", "4.2", "4.4"),

    # Disaster Recovery Sites -> 3.4 (resilience) per PDF
    ("Disaster Recovery Sites", "5.2", "3.4"),
]

print("\n--- PHASE 2: Fixing objective mappings ---")
remapped = 0
for term_substr, old_code, new_code in REMAPS:
    # Find concept
    concept = conn.execute(
        "SELECT id, term FROM forge_concepts WHERE term LIKE ?",
        (f"%{term_substr}%",),
    ).fetchone()
    if not concept:
        print(f"  [SKIP] Concept not found: {term_substr}")
        continue

    # Find old and new objectives
    old_obj = get_forge_objective_by_code(conn, SUBJECT_ID, old_code)
    new_obj = get_forge_objective_by_code(conn, SUBJECT_ID, new_code)
    if not old_obj or not new_obj:
        print(f"  [SKIP] Objective not found: {old_code} or {new_code}")
        continue

    # Remove old link
    conn.execute(
        "DELETE FROM forge_concept_objectives WHERE concept_id = ? AND objective_id = ?",
        (concept["id"], old_obj["id"]),
    )
    # Add new link
    conn.execute(
        "INSERT OR IGNORE INTO forge_concept_objectives (concept_id, objective_id) VALUES (?, ?)",
        (concept["id"], new_obj["id"]),
    )
    conn.commit()
    print(f"  {concept['term']}: {old_code} -> {new_code}")
    remapped += 1
print(f"  Remapped: {remapped}")


# =============================================================================
# PHASE 3: Add missing concepts
# =============================================================================
# (term, definition, objective_code, difficulty)
NEW_CONCEPTS = [
    # --- 1.2: Fundamental Security Concepts ---
    ("Physical Security Controls (Bollards, Fencing, Lighting)",
     "Physical barriers and environmental controls protecting facilities. Bollards prevent vehicle ramming, fencing defines perimeters, lighting deters intruders, sensors (infrared, pressure, microwave, ultrasonic) detect motion.",
     "1.2", "beginner"),

    ("Access Control Vestibule (Mantrap)",
     "A small room with two interlocking doors where only one opens at a time, preventing tailgating. Person enters, first door locks, authentication required to open second door.",
     "1.2", "beginner"),

    # --- 1.4: Cryptographic Solutions ---
    ("Trusted Platform Module (TPM)",
     "Hardware chip on motherboard that stores cryptographic keys, performs encryption, and ensures platform integrity. Used for secure boot, BitLocker, and hardware-based key storage.",
     "1.4", "intermediate"),

    ("Hardware Security Module (HSM)",
     "Dedicated hardware device for managing, processing, and storing cryptographic keys. Tamper-resistant, used by CAs and enterprises for high-security key operations.",
     "1.4", "intermediate"),

    ("Key Escrow",
     "Arrangement where cryptographic keys are held by a trusted third party (escrow agent). Allows authorized key recovery if original holder is unavailable. Controversial for privacy.",
     "1.4", "intermediate"),

    ("Tokenization",
     "Replacing sensitive data with a non-sensitive token that maps back to the original in a secure vault. Unlike encryption, tokens have no mathematical relationship to original data. Common for credit card numbers.",
     "1.4", "intermediate"),

    ("Data Masking",
     "Replacing real data with realistic but fake data for non-production use. Static masking creates permanent copies; dynamic masking applies in real-time. Used for development and testing environments.",
     "1.4", "beginner"),

    ("Certificate Revocation (CRL and OCSP)",
     "CRL (Certificate Revocation List) is a published list of revoked certificate serial numbers. OCSP (Online Certificate Status Protocol) provides real-time certificate status checks. OCSP is faster but requires the responder to be online.",
     "1.4", "intermediate"),

    ("Encryption Levels (Full-Disk, File, Volume, Database, Record)",
     "Granularity of encryption. Full-disk encrypts entire drive (BitLocker, FileVault). File encrypts individual files. Volume encrypts partitions. Database encrypts DB contents. Record encrypts individual rows/fields.",
     "1.4", "intermediate"),

    ("Key Exchange (Diffie-Hellman)",
     "Method for two parties to establish a shared secret over an insecure channel without transmitting the key. Diffie-Hellman is the foundational algorithm. Vulnerable to MITM without authentication.",
     "1.4", "intermediate"),

    ("Obfuscation",
     "Making code or data difficult to understand or reverse-engineer. Includes steganography (hiding data in images), tokenization (replacing sensitive values), and data masking. Goal is reducing exposure.",
     "1.4", "beginner"),

    # --- 2.2: Threat Vectors ---
    ("Vishing and Smishing",
     "Vishing: voice phishing via phone calls impersonating banks, IT support, etc. Smishing: SMS phishing via text messages with malicious links. Both exploit urgency and trust in communication channels.",
     "2.2", "beginner"),

    ("Removable Device Attacks",
     "Attacks using USB drives, external media, or cables. Includes USB drop attacks (leaving infected drives in parking lots), BadUSB (firmware-modified devices that emulate keyboards), and data exfiltration via removable media.",
     "2.2", "beginner"),

    ("Bluetooth Attacks (Bluejacking, Bluesnarfing)",
     "Bluejacking: sending unsolicited messages via Bluetooth. Bluesnarfing: unauthorized access to data through Bluetooth. Bluebugging: taking control of a device. Mitigate by disabling Bluetooth when not in use.",
     "2.2", "intermediate"),

    ("Brand Impersonation and Typosquatting",
     "Brand impersonation: creating fake websites/emails mimicking legitimate organizations. Typosquatting: registering misspelled domain names (gooogle.com) to catch user typos. Both used for credential theft and malware distribution.",
     "2.2", "beginner"),

    ("Pretexting and Impersonation",
     "Pretexting: creating a fabricated scenario to manipulate victims into divulging information. Impersonation: posing as an authority figure (IT admin, executive). Both are social engineering techniques relying on trust and urgency.",
     "2.2", "beginner"),

    ("Unsupported Systems and Applications",
     "Software or hardware past end-of-life (EOL) that no longer receives security patches. Running unsupported systems creates unmitigated vulnerabilities. Examples: Windows 7, outdated firmware, legacy applications.",
     "2.2", "beginner"),

    # --- 2.3: Vulnerabilities ---
    ("Memory Injection",
     "Injecting malicious code into a running process's memory space. Includes DLL injection (loading malicious DLL), process hollowing (replacing legitimate process memory), and thread hijacking. Evades file-based antivirus.",
     "2.3", "advanced"),

    ("Virtual Machine (VM) Escape",
     "Exploit allowing an attacker to break out of a guest VM and interact with the host OS or hypervisor. Extremely dangerous as it compromises all VMs on the host. Mitigated by patching hypervisors.",
     "2.3", "advanced"),

    ("Side Loading and Jailbreaking",
     "Side loading: installing apps from unofficial sources, bypassing app store security review. Jailbreaking (iOS) / rooting (Android): removing OS restrictions to gain elevated access. Both increase attack surface on mobile devices.",
     "2.3", "intermediate"),

    ("Misconfiguration Vulnerabilities",
     "Security weaknesses from improper system configuration: default credentials, open ports, overly permissive ACLs, unnecessary services enabled, directory listing exposed. One of the most common vulnerability types.",
     "2.3", "beginner"),

    ("Hardware Vulnerabilities (Firmware, End-of-Life)",
     "Security issues in physical components. Firmware vulnerabilities exploit updatable chip software. End-of-life hardware receives no patches. Legacy systems may lack modern security features. Supply chain risks in hardware providers.",
     "2.3", "intermediate"),

    # --- 2.4: Indicators of Malicious Activity ---
    ("Spyware",
     "Malware that secretly monitors user activity, captures keystrokes, screenshots, browsing habits, and credentials. Transmits data to attacker. Often bundled with free software. Unlike keyloggers, spyware has broader surveillance scope.",
     "2.4", "beginner"),

    ("Bloatware",
     "Pre-installed or bundled software that consumes resources and may introduce vulnerabilities. Not always malicious but increases attack surface. Can include adware, trial software, and manufacturer utilities.",
     "2.4", "beginner"),

    ("Virus",
     "Malicious code that attaches to a host program and replicates when the host executes. Unlike worms, viruses require user action to spread. Types: boot sector, macro, polymorphic, metamorphic, armored.",
     "2.4", "beginner"),

    ("Downgrade Attack",
     "Forcing a system to use an older, weaker protocol version (e.g., TLS 1.0 instead of 1.3). Attacker intercepts negotiation and manipulates version selection to exploit known vulnerabilities in older protocols.",
     "2.4", "intermediate"),

    ("Collision and Birthday Attacks",
     "Collision attack: finding two different inputs that produce the same hash output. Birthday attack: exploiting the birthday paradox to find collisions faster than brute force. Both target weak hash algorithms like MD5.",
     "2.4", "advanced"),

    ("Password Spraying",
     "Trying a few common passwords across many accounts rather than many passwords against one account. Avoids account lockout thresholds. Effective against organizations with weak password policies.",
     "2.4", "intermediate"),

    ("Credential Replay",
     "Capturing and retransmitting valid authentication credentials (tokens, hashes, tickets). Unlike replay attacks on network packets, credential replay specifically reuses authentication material. Mitigated by session tokens and timestamps.",
     "2.4", "intermediate"),

    ("RFID Cloning",
     "Copying data from an RFID access badge using a portable reader, then writing it to a blank card to gain unauthorized physical access. Mitigated by Faraday sleeves, MFA, and encrypted RFID protocols.",
     "2.4", "intermediate"),

    # --- 2.5: Mitigation Techniques ---
    ("Access Control List (ACL)",
     "Ordered list of rules that permit or deny traffic based on source/destination IP, port, and protocol. Applied to network interfaces, firewalls, and file systems. Processed top-down; first match wins.",
     "2.5", "beginner"),

    ("Application Allow List (Whitelisting)",
     "Only explicitly approved applications are permitted to run. Everything not on the list is blocked by default. Stronger than blocklisting but harder to maintain. Prevents unknown malware execution.",
     "2.5", "intermediate"),

    ("Isolation",
     "Separating compromised or untrusted systems from the network to prevent lateral movement. Used during incident response (quarantine) and for high-security environments (air-gapped networks). Includes network and process isolation.",
     "2.5", "beginner"),

    ("Decommissioning",
     "Securely retiring systems and hardware from service. Includes data sanitization, license reclamation, documentation updates, and certificate revocation. Improperly decommissioned systems can leak sensitive data.",
     "2.5", "beginner"),

    ("Host-Based Firewall and HIPS",
     "Host-based firewall: software firewall running on individual endpoints controlling inbound/outbound traffic. HIPS (Host-Based Intrusion Prevention System): monitors system calls and blocks suspicious activity at the host level.",
     "2.5", "intermediate"),

    ("Configuration Enforcement",
     "Ensuring systems maintain approved security configurations through automated tools, group policies, and compliance scanning. Prevents configuration drift. Includes disabling ports/protocols and removing unnecessary software.",
     "2.5", "intermediate"),

    # --- 3.1: Architecture Models ---
    ("Internet of Things (IoT) Security",
     "Securing network-connected devices (cameras, sensors, appliances) with limited computing power. Challenges: weak default credentials, infrequent patching, large attack surface. Mitigate with network segmentation and firmware updates.",
     "3.1", "intermediate"),

    ("Industrial Control Systems (ICS/SCADA)",
     "Systems controlling physical processes in manufacturing, utilities, and infrastructure. SCADA (Supervisory Control and Data Acquisition) monitors and controls remote equipment. Critical infrastructure target requiring air-gapping and specialized security.",
     "3.1", "intermediate"),

    ("Embedded Systems and RTOS",
     "Embedded systems: purpose-built computers within larger devices (medical, automotive). RTOS (Real-Time Operating System): OS with guaranteed response times for time-critical operations. Both have limited patching capability and long lifecycles.",
     "3.1", "intermediate"),

    ("Air-Gapped Networks",
     "Networks physically isolated from the internet and other networks. No wired or wireless connections to external systems. Used for classified systems, SCADA, and high-security environments. Data transfer via approved removable media only.",
     "3.1", "intermediate"),

    ("Virtualization Security",
     "Security considerations for virtual environments. VM sprawl increases attack surface. VM escape allows breaking out of guest to host. Hypervisor hardening is critical. Snapshots can preserve pre-attack states for forensics.",
     "3.1", "intermediate"),

    # --- 3.2: Secure Enterprise Infrastructure ---
    ("Jump Server (Jump Box)",
     "Hardened intermediary server used to access systems in a different security zone. Admins connect to the jump server first, then to target systems. Provides a single auditable access point and reduces direct exposure.",
     "3.2", "intermediate"),

    ("Web Application Firewall (WAF)",
     "Firewall specifically designed to filter, monitor, and block HTTP/HTTPS traffic to web applications. Protects against XSS, SQL injection, CSRF. Operates at Layer 7 (application layer). Can be hardware, software, or cloud-based.",
     "3.2", "intermediate"),

    ("Next-Generation Firewall (NGFW)",
     "Combines traditional firewall with advanced features: deep packet inspection, intrusion prevention, application awareness, SSL/TLS inspection, and threat intelligence feeds. Goes beyond port/protocol filtering to inspect application-layer content.",
     "3.2", "intermediate"),

    ("Unified Threat Management (UTM)",
     "All-in-one security appliance combining firewall, IDS/IPS, antivirus, content filtering, VPN, and anti-spam in a single device. Simplifies management for small/mid-size organizations but creates a single point of failure.",
     "3.2", "intermediate"),

    ("Extensible Authentication Protocol (EAP)",
     "Authentication framework used with 802.1X for network access control. Variants include EAP-TLS (certificate-based, most secure), PEAP (password in TLS tunnel), and EAP-FAST (Cisco, flexible). Not a protocol itself but a framework.",
     "3.2", "intermediate"),

    ("Secure Access Service Edge (SASE)",
     "Cloud-delivered framework combining SD-WAN with security functions (CASB, FWaaS, SWG, ZTNA). Provides secure access regardless of user location. Converges networking and security into a single cloud service.",
     "3.2", "advanced"),

    ("Software-Defined Wide Area Network (SD-WAN)",
     "Virtual WAN architecture that abstracts networking hardware, using software to intelligently route traffic across multiple connection types (MPLS, broadband, LTE). Centralizes management and improves performance for distributed organizations.",
     "3.2", "intermediate"),

    ("Fail-Open vs Fail-Closed",
     "Fail-open: system defaults to allowing access when it fails (prioritizes availability). Fail-closed: system defaults to denying access when it fails (prioritizes security). Choice depends on whether availability or security is more critical.",
     "3.2", "beginner"),

    # --- 3.3: Data Protection (previously had wrong concepts) ---
    ("Data Types (Regulated, PII, PHI, Financial)",
     "Categories of data requiring different protections. Regulated: subject to laws (HIPAA, GDPR). PII (Personally Identifiable Information): identifies individuals. PHI (Protected Health Information): health records. Financial: payment/banking data. Trade secrets and IP also protected.",
     "3.3", "beginner"),

    ("Data Classifications (Public, Confidential, Restricted, Critical)",
     "Labeling data by sensitivity to determine handling requirements. Public: no restrictions. Confidential: internal use only. Restricted: limited access. Critical: highest protection. Classification drives encryption, access controls, and storage requirements.",
     "3.3", "beginner"),

    ("Geographic Restrictions and Geolocation",
     "Controlling where data can be stored, processed, or accessed based on physical location. Geofencing restricts access by GPS/IP location. Data sovereignty laws (GDPR) mandate data stays within specific borders.",
     "3.3", "intermediate"),

    ("Data Protection Methods (Masking, Tokenization, Obfuscation)",
     "Techniques to protect data beyond encryption. Masking: replacing with realistic fakes. Tokenization: substituting with non-reversible tokens. Obfuscation: making data unclear. Segmentation: isolating sensitive data. Permission restrictions: limiting who can access.",
     "3.3", "intermediate"),

    # --- 3.4: Resilience and Recovery ---
    ("High Availability (Load Balancing, Clustering, Failover)",
     "Ensuring systems remain operational. Load balancing distributes traffic across servers. Clustering groups servers to act as one. Failover automatically switches to a standby system when primary fails. Goal: minimize downtime.",
     "3.4", "intermediate"),

    ("Platform Diversity and Multi-Cloud",
     "Using multiple vendors, operating systems, or cloud providers to reduce single points of failure. If one platform is compromised, others remain operational. Multi-cloud distributes workloads across AWS, Azure, GCP, etc.",
     "3.4", "intermediate"),

    ("Continuity of Operations (COOP)",
     "Plan for maintaining essential functions during and after a disaster. Includes alternate sites, succession planning, communication plans, and vital records protection. Broader than disaster recovery -- focuses on keeping the mission going.",
     "3.4", "intermediate"),

    ("Capacity Planning (People, Technology, Infrastructure)",
     "Ensuring sufficient resources to meet current and future demands. People: staffing and skills. Technology: compute, storage, bandwidth. Infrastructure: power, cooling, space. Prevents outages from resource exhaustion.",
     "3.4", "beginner"),

    ("Power Systems (UPS, Generators)",
     "UPS (Uninterruptible Power Supply): battery backup providing short-term power during outages, protecting against surges and sags. Generators: fuel-powered long-term backup power. Together they ensure continuous operations during extended outages.",
     "3.4", "beginner"),

    ("Testing Exercises (Tabletop, Simulation, Parallel Processing)",
     "Tabletop: discussion-based walkthrough of scenarios with no actual systems affected. Simulation: realistic test with some live elements. Parallel processing: running backup systems simultaneously to validate failover. Increasing levels of realism and risk.",
     "3.4", "intermediate"),

    # --- 4.1: Security Techniques for Computing Resources ---
    ("Secure Baselines",
     "Documented security configurations that all systems must meet before deployment. Establish the baseline, deploy consistently, and maintain through continuous monitoring. Deviations are flagged and remediated. Foundation for configuration management.",
     "4.1", "intermediate"),

    ("Mobile Device Management (MDM)",
     "Enterprise solution for managing mobile devices. Enforces policies (encryption, PIN, remote wipe), controls app installation, manages deployment models: BYOD (Bring Your Own Device), COPE (Corporate-Owned, Personally Enabled), CYOD (Choose Your Own Device).",
     "4.1", "intermediate"),

    ("Wi-Fi Protected Access 3 (WPA3)",
     "Latest wireless security protocol replacing WPA2. Uses SAE (Simultaneous Authentication of Equals) instead of PSK, providing forward secrecy. WPA3-Enterprise uses 192-bit encryption. Protects against offline dictionary attacks.",
     "4.1", "intermediate"),

    ("RADIUS (Remote Authentication Dial-In User Service)",
     "AAA protocol providing centralized authentication for network access. Used with 802.1X and VPNs. Encrypts only the password (not entire packet). Uses UDP. TACACS+ is the Cisco alternative that encrypts entire payload and uses TCP.",
     "4.1", "intermediate"),

    ("Application Security (Input Validation, Code Signing, Static Analysis)",
     "Input validation: checking all user input against expected formats to prevent injection. Static code analysis: reviewing source code without execution (SAST). Code signing: digitally signing executables to verify integrity and publisher identity.",
     "4.1", "intermediate"),

    ("Sandboxing",
     "Running untrusted code in an isolated environment where it cannot affect the host system. Used for malware analysis, testing patches, and browser security. If malicious behavior is detected, the sandbox contains the damage.",
     "4.1", "intermediate"),

    # --- 4.2: Asset Management ---
    ("Asset Management (Acquisition, Tracking, Disposal)",
     "Full lifecycle of hardware and software assets. Acquisition: procurement and approval processes. Tracking: inventory, enumeration, and ownership assignment. Disposal: sanitization, destruction, and certification that data is unrecoverable.",
     "4.2", "beginner"),

    ("Data Retention Policies",
     "Rules governing how long data must be kept and when it must be destroyed. Driven by regulatory requirements (HIPAA: 6 years, SOX: 7 years), business needs, and legal holds. Improper retention creates liability; premature destruction violates compliance.",
     "4.2", "intermediate"),

    ("Enumeration and Inventory",
     "Enumeration: systematically discovering and listing all assets, services, and resources on a network. Inventory: maintaining a current database of all hardware, software, licenses, and configurations. Foundation for vulnerability management.",
     "4.2", "beginner"),

    # --- 4.3: Vulnerability Management ---
    ("Vulnerability Scanning Methods",
     "Techniques for identifying vulnerabilities. Credentialed scans: log into systems for deep inspection. Non-credentialed: external perspective only. Agent-based: software on endpoints. Agentless: network-based scanning. Each has different depth and impact.",
     "4.3", "intermediate"),

    ("Common Vulnerabilities and Exposures (CVE)",
     "Standardized naming system for publicly known vulnerabilities. Each CVE gets a unique ID (CVE-2024-12345). Referenced by CVSS scores for severity. CVE database maintained by MITRE. Essential for vulnerability tracking and patch prioritization.",
     "4.3", "intermediate"),

    ("False Positive vs False Negative",
     "False positive: alert triggered when no real threat exists (wastes analyst time). False negative: real threat not detected (dangerous). Tuning IDS/IPS rules and vulnerability scanners balances detection rate against false alarm rate.",
     "4.3", "beginner"),

    ("Responsible Disclosure and Bug Bounty",
     "Responsible disclosure: reporting vulnerabilities to vendors before public release, giving time to patch. Bug bounty: programs paying researchers for finding and reporting vulnerabilities. Both encourage ethical vulnerability reporting over exploitation.",
     "4.3", "intermediate"),

    # --- 4.4: Security Monitoring ---
    ("SIEM Operations (Log Aggregation, Alerting, Correlation)",
     "SIEM (Security Information and Event Management) collects logs from across the enterprise, correlates events, generates alerts, and provides dashboards. Log aggregation centralizes data. Correlation rules detect attack patterns across multiple sources.",
     "4.4", "intermediate"),

    ("Data Loss Prevention (DLP) Systems",
     "Technology preventing unauthorized data exfiltration. Network DLP: monitors data in transit. Endpoint DLP: monitors data on devices. Cloud DLP: monitors cloud storage. Uses content inspection, pattern matching, and policy enforcement.",
     "4.4", "intermediate"),

    ("Antivirus and Anti-Malware",
     "Software detecting and removing malicious code. Signature-based: matches known malware patterns. Heuristic: analyzes behavior for suspicious activity. Sandboxing: executes suspicious files in isolation. Must be regularly updated with new signatures.",
     "4.4", "beginner"),

    ("Benchmarks and Security Baselines",
     "CIS Benchmarks: community-developed secure configuration guides for OS, applications, and devices. SCAP (Security Content Automation Protocol) automates compliance checking against these benchmarks. STIG: DoD-specific hardening guides.",
     "4.4", "intermediate"),

    # --- 4.5: Enterprise Security Capabilities ---
    ("Firewall Rules and Access Lists",
     "Configuring firewall policies: rules define permit/deny based on source, destination, port, and protocol. Screened subnets (DMZ) isolate public-facing servers. Port selection and protocol selection determine what traffic is allowed.",
     "4.5", "intermediate"),

    ("IDS/IPS Configuration (Trends, Signatures)",
     "IDS (Intrusion Detection System) monitors and alerts. IPS (Intrusion Prevention System) monitors and blocks. Signature-based: matches known attack patterns. Anomaly-based: detects deviations from baseline. Trends analysis identifies emerging patterns.",
     "4.5", "intermediate"),

    ("DNS Filtering",
     "Blocking access to malicious or prohibited domains at the DNS level. Queries to known-bad domains return a sinkhole address instead of the real IP. Effective against phishing, malware C2 servers, and policy-violating content.",
     "4.5", "intermediate"),

    ("Web Content Filtering",
     "Controlling web access through URL categorization, content inspection, and reputation scoring. Agent-based: runs on endpoints. Centralized proxy: routes all traffic through a filter. Block rules prevent access to malicious or policy-violating sites.",
     "4.5", "intermediate"),

    ("Email Security (DMARC, DKIM, SPF)",
     "SPF (Sender Policy Framework): DNS record listing authorized mail servers. DKIM (DomainKeys Identified Mail): cryptographic signature on emails proving domain authenticity. DMARC: policy framework combining SPF and DKIM, telling receivers how to handle failures.",
     "4.5", "intermediate"),

    ("Endpoint Detection and Response (EDR/XDR)",
     "EDR: monitors endpoints for suspicious activity, records events, and enables investigation/response. XDR (Extended Detection and Response): extends EDR across network, cloud, and email. Both provide continuous monitoring beyond traditional antivirus.",
     "4.5", "intermediate"),

    ("Network Access Control (NAC)",
     "Controls which devices can access the network. Checks device health (patches, antivirus, configuration) before granting access. Non-compliant devices are quarantined or given limited access. Often uses 802.1X for authentication.",
     "4.5", "intermediate"),

    ("File Integrity Monitoring (FIM)",
     "Detects unauthorized changes to critical system files, configurations, and registry entries by comparing current state against a known-good baseline hash. Alerts on modifications that could indicate compromise or configuration drift.",
     "4.5", "intermediate"),

    ("User Behavior Analytics (UBA)",
     "Machine learning-based analysis of user activity patterns to detect anomalies: unusual login times, impossible travel, excessive file access, privilege escalation patterns. Identifies insider threats and compromised accounts.",
     "4.5", "advanced"),

    ("Group Policy and SELinux",
     "Group Policy: Windows-based centralized configuration management through Active Directory. Enforces security settings across domain-joined machines. SELinux (Security-Enhanced Linux): mandatory access control for Linux providing fine-grained process/file permissions.",
     "4.5", "intermediate"),

    # --- 4.6: Identity and Access Management ---
    ("Provisioning and De-Provisioning",
     "Provisioning: creating user accounts and assigning appropriate access rights when hired. De-provisioning: disabling/removing accounts and revoking access when employees leave or change roles. Timely de-provisioning prevents unauthorized access from former employees.",
     "4.6", "beginner"),

    ("Mandatory Access Control (MAC)",
     "Access decisions based on security labels (classifications) assigned by the system, not the owner. Users cannot change permissions. Data is labeled (Top Secret, Secret, Confidential). Used in military and government environments. Most restrictive model.",
     "4.6", "intermediate"),

    ("Discretionary Access Control (DAC)",
     "Resource owners decide who can access their resources. Most common in everyday systems (Windows file permissions). Flexible but risky -- owners may grant excessive access. Based on user identity and group membership.",
     "4.6", "intermediate"),

    ("Rule-Based Access Control (RuBAC)",
     "Access decisions based on predefined rules and conditions, not user identity. Example: firewall rules, time-of-day restrictions. If-then logic: IF request matches rule conditions THEN allow/deny. Different from RBAC (role-based).",
     "4.6", "intermediate"),

    ("Lightweight Directory Access Protocol (LDAP)",
     "Protocol for accessing and maintaining directory services (like Active Directory). Organizes users, groups, and resources in a hierarchical structure. LDAPS adds TLS encryption. Used for centralized authentication and authorization.",
     "4.6", "intermediate"),

    ("Biometrics (Fingerprint, Facial, Iris)",
     "Authentication using physical characteristics. Something you are factor. FAR (False Acceptance Rate): unauthorized person accepted. FRR (False Rejection Rate): authorized person rejected. CER (Crossover Error Rate): where FAR=FRR, lower is better.",
     "4.6", "intermediate"),

    ("Password Policies (Length, Complexity, Expiration, Managers)",
     "Rules governing password security. Length: minimum characters (12+ recommended). Complexity: mix of upper/lower/numbers/symbols. Expiration: forced periodic changes (controversial). Password managers: encrypted vaults storing unique passwords. Passwordless: using biometrics or security keys instead.",
     "4.6", "beginner"),

    ("Just-in-Time Permissions and Ephemeral Credentials",
     "Just-in-time: granting elevated access only when needed for a specific task, automatically revoking after completion. Ephemeral credentials: temporary credentials that expire quickly. Both follow least privilege principle and reduce standing privileges.",
     "4.6", "advanced"),

    ("TACACS+ (Terminal Access Controller Access-Control System Plus)",
     "Cisco-developed AAA protocol. Unlike RADIUS, encrypts entire payload (not just password), uses TCP (more reliable), and separates authentication, authorization, and accounting functions. Preferred for device administration.",
     "4.6", "intermediate"),

    # --- 4.7: Automation and Orchestration ---
    ("Automation Use Cases (Provisioning, Guard Rails, Escalation)",
     "Key automation scenarios: user/resource provisioning, security group management, ticket creation and escalation, enabling/disabling services, CI/CD pipelines, and API integrations. Reduces human error and response time.",
     "4.7", "intermediate"),

    ("Automation Benefits and Considerations",
     "Benefits: efficiency, enforcing baselines, standard configurations, secure scaling, faster reaction time, workforce multiplier. Considerations: complexity, cost, single point of failure, technical debt, ongoing supportability.",
     "4.7", "intermediate"),

    # --- 4.8: Incident Response ---
    ("Root Cause Analysis (RCA)",
     "Systematic investigation to identify the fundamental reason an incident occurred, not just the symptoms. Methods include 5 Whys, fishbone diagrams, and fault tree analysis. Findings drive preventive measures to avoid recurrence.",
     "4.8", "intermediate"),

    ("Threat Hunting",
     "Proactive search for threats that evade automated detection. Assumes the network is already compromised. Uses hypothesis-driven investigation, IOC searching, and behavioral analysis. Requires skilled analysts and threat intelligence.",
     "4.8", "advanced"),

    # --- 4.9: Data Sources for Investigation ---
    ("Log Data Sources (Firewall, Application, Endpoint, OS, IDS/IPS)",
     "Firewall logs: connection attempts and rule matches. Application logs: app-specific events and errors. Endpoint logs: user/process activity. OS security logs: authentication and authorization events. IDS/IPS logs: detected/blocked attacks. Network logs: traffic flows.",
     "4.9", "intermediate"),

    ("Metadata Analysis",
     "Examining data about data: file creation dates, author information, GPS coordinates in photos, email headers, document revision history. Metadata can reveal who created files, when, where, and how they were modified. Critical in forensic investigations.",
     "4.9", "intermediate"),

    ("Dashboards and Automated Reports",
     "Visual interfaces aggregating security data from multiple sources. Dashboards show real-time status (threat level, active incidents, compliance). Automated reports generate scheduled summaries for management, auditors, and compliance requirements.",
     "4.9", "beginner"),

    ("Vulnerability Scan Reports",
     "Output from vulnerability scanners showing discovered weaknesses, severity ratings (CVSS scores), affected systems, and remediation guidance. Used during investigations to determine if known vulnerabilities were exploited. Scheduled and on-demand scanning.",
     "4.9", "intermediate"),

    # --- 5.1: Security Governance ---
    ("Acceptable Use Policy (AUP)",
     "Document defining permitted and prohibited use of organization's IT resources. Covers internet usage, email, social media, personal devices, and data handling. Employees typically sign during onboarding. Violation can result in disciplinary action.",
     "5.1", "beginner"),

    ("Software Development Lifecycle (SDLC) Security",
     "Integrating security into every phase of software development. Requirements: security requirements. Design: threat modeling. Implementation: secure coding. Testing: SAST/DAST. Deployment: hardening. Maintenance: patching. Shift-left security emphasizes early integration.",
     "5.1", "intermediate"),

    ("Onboarding and Offboarding Procedures",
     "Onboarding: background checks, security awareness training, account provisioning, signing AUP, issuing equipment and badges. Offboarding: revoking access, returning equipment, exit interviews, knowledge transfer. Both are critical security processes.",
     "5.1", "beginner"),

    ("Governance Structures (Boards, Committees)",
     "Organizational bodies overseeing security programs. Board of directors: ultimate accountability. Security steering committee: strategic decisions. Centralized governance: single authority sets policy. Decentralized: business units manage their own security within guidelines.",
     "5.1", "intermediate"),

    ("Data Roles (Owner, Controller, Processor, Custodian, Steward)",
     "Owner: executive responsible for data, sets classification. Controller: determines purpose and means of processing (GDPR term). Processor: processes data on behalf of controller. Custodian: manages day-to-day data handling. Steward: ensures data quality and compliance.",
     "5.1", "intermediate"),

    # --- 5.2: Risk Management ---
    ("Single Loss Expectancy (SLE) and Annualized Loss Expectancy (ALE)",
     "SLE = Asset Value x Exposure Factor (single incident cost). ALE = SLE x ARO (Annualized Rate of Occurrence). Example: $100K server, 25% damage likelihood, once per 5 years. SLE=$25K, ARO=0.2, ALE=$5K/year. Used to justify security spending.",
     "5.2", "intermediate"),

    ("Mean Time to Repair (MTTR) and Mean Time Between Failures (MTBF)",
     "MTTR: average time to fix a failed system and restore service. Lower is better. MTBF: average time between system failures. Higher is better. Both measure system reliability. Used in BIA to estimate downtime impact and set recovery objectives.",
     "5.2", "intermediate"),

    ("Key Risk Indicators (KRI)",
     "Measurable metrics that signal increasing risk levels. Examples: number of unpatched systems, failed login attempts, policy violations, overdue security training. Tracked in the risk register to trigger management action before incidents occur.",
     "5.2", "intermediate"),

    # --- 5.3: Third-Party Risk ---
    ("Agreement Types (MOA, MOU, MSA, NDA, BPA, SOW)",
     "MOA (Memorandum of Agreement): formal agreement between parties. MOU (Memorandum of Understanding): less formal intent document. MSA (Master Service Agreement): overarching contract terms. NDA: confidentiality agreement. BPA (Business Partners Agreement): joint venture terms. SOW (Statement of Work): specific deliverables.",
     "5.3", "intermediate"),

    ("Supply Chain Risk Assessment",
     "Evaluating security risks from vendors, suppliers, and service providers throughout the supply chain. Includes right-to-audit clauses, evidence of internal audits, independent assessments, penetration testing results, and ongoing vendor monitoring.",
     "5.3", "intermediate"),

    # --- 5.4: Security Compliance ---
    ("Compliance Reporting (Internal and External)",
     "Internal: self-assessments, audit committee reviews, internal audits measuring policy adherence. External: regulatory filings, third-party audit reports (SOC 2), certification renewals. Non-compliance consequences: fines, sanctions, reputational damage, loss of license.",
     "5.4", "intermediate"),

    ("Data Inventory and Right to Be Forgotten",
     "Data inventory: cataloging all data assets, locations, and retention requirements. Right to be forgotten (GDPR Article 17): individuals can request deletion of their personal data. Organizations must track data to fulfill deletion requests and prove compliance.",
     "5.4", "intermediate"),

    # --- 5.5: Audits and Assessments ---
    ("Penetration Testing Types (Known, Unknown, Partially Known Environment)",
     "Known environment (white box): tester has full knowledge of systems, source code, architecture. Unknown environment (black box): tester has no prior knowledge, simulates external attacker. Partially known (gray box): limited information provided. Reconnaissance can be passive or active.",
     "5.5", "intermediate"),

    ("Internal vs External Audits",
     "Internal: conducted by organization's own audit team, includes self-assessments and compliance checks. External: performed by independent third parties, includes regulatory audits, examinations, and formal assessments. External audits carry more weight with regulators.",
     "5.5", "intermediate"),

    # --- 5.6: Security Awareness ---
    ("Phishing Campaigns and Simulation",
     "Organizational exercises sending fake phishing emails to test employee awareness. Tracks who clicks links, submits credentials, or reports the email. Results drive targeted training. Regular campaigns measurably improve phishing resistance over time.",
     "5.6", "intermediate"),

    ("Anomalous Behavior Recognition",
     "Training users to identify and report unusual activity: risky behavior (policy violations), unexpected behavior (unfamiliar processes), and unintentional actions (accidental data sharing). Complements technical controls with human detection.",
     "5.6", "beginner"),

    ("Operational Security (OPSEC) for Remote/Hybrid Work",
     "Security practices for distributed workforces: VPN usage, secure Wi-Fi, physical screen privacy, clean desk policy, secure document disposal, avoiding public discussions of sensitive topics. Addresses unique risks of working outside the office.",
     "5.6", "beginner"),
]

print(f"\n--- PHASE 3: Adding {len(NEW_CONCEPTS)} new concepts ---")
added = 0
skipped = 0
for term, definition, obj_code, difficulty in NEW_CONCEPTS:
    # Check if already exists
    existing = conn.execute(
        "SELECT id FROM forge_concepts WHERE LOWER(term) = LOWER(?)",
        (term,),
    ).fetchone()
    if existing:
        print(f"  [EXISTS] {term}")
        skipped += 1
        continue

    try:
        concept = add_concept(
            term=term,
            definition=definition,
            category="security",
            difficulty=difficulty,
            tags=[obj_code, f"domain-{obj_code.split('.')[0]}", "sy0-701"],
            source="CompTIA SY0-701",
            subject_id=SUBJECT_ID,
            bloom_level="remember",
        )
        link_concept_to_objective(concept.id, obj_code, SUBJECT_ID)
        added += 1
    except Exception as e:
        print(f"  [ERROR] {term}: {e}")
        skipped += 1

print(f"  Added: {added}, Skipped: {skipped}")

# Final stats
total = conn.execute("SELECT COUNT(*) FROM forge_concepts").fetchone()[0]
linked = conn.execute("SELECT COUNT(*) FROM forge_concept_objectives").fetchone()[0]
print(f"\n=== FINAL STATS ===")
print(f"Total concepts: {total}")
print(f"Concept-objective links: {linked}")

# Show per-objective counts
objectives = conn.execute(
    "SELECT fo.code, fo.title, COUNT(fco.concept_id) as cnt "
    "FROM forge_objectives fo "
    "LEFT JOIN forge_concept_objectives fco ON fo.id = fco.objective_id "
    "WHERE fo.subject_id = ? "
    "GROUP BY fo.code ORDER BY fo.code",
    (SUBJECT_ID,),
).fetchall()
print("\nConcepts per objective:")
for obj in objectives:
    print(f"  {obj['code']} {obj['title'][:50]:50s} {obj['cnt']:3d}")

conn.close()
