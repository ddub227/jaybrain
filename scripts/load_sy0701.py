"""Load CompTIA Security+ SY0-701 concept deck into SynapseForge.

SY0-701 LOCKDOWN - Full exam domain coverage.
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

from src.jaybrain.config import ensure_data_dirs
from src.jaybrain.db import init_db
from src.jaybrain.forge import add_concept

ensure_data_dirs()
init_db()

# SY0-701 Exam Domains:
# 1.0 General Security Concepts (12%)
# 2.0 Threats, Vulnerabilities, and Mitigations (22%)
# 3.0 Security Architecture (18%)
# 4.0 Security Operations (28%)
# 5.0 Security Program Management and Oversight (20%)

CONCEPTS = [
    # =========================================================================
    # DOMAIN 1: General Security Concepts (12%)
    # =========================================================================

    # 1.1 Security controls
    {
        "term": "CIA Triad",
        "definition": "The three pillars of information security: Confidentiality (only authorized access), Integrity (data is accurate and unaltered), and Availability (systems are accessible when needed). Every security control maps to one or more of these.",
        "difficulty": "beginner",
        "tags": ["sy0-701", "domain-1", "1.1", "fundamentals"],
    },
    {
        "term": "Non-repudiation",
        "definition": "Assurance that someone cannot deny an action they performed. Achieved through digital signatures, audit logs, and certificates. Provides proof of origin and proof of delivery.",
        "difficulty": "beginner",
        "tags": ["sy0-701", "domain-1", "1.1", "fundamentals"],
    },
    {
        "term": "AAA Framework",
        "definition": "Authentication (verify identity), Authorization (grant permissions), and Accounting (log actions). Implemented by protocols like RADIUS and TACACS+. The foundation of access control systems.",
        "difficulty": "beginner",
        "tags": ["sy0-701", "domain-1", "1.1", "access-control"],
    },
    {
        "term": "Gap Analysis",
        "definition": "Process of comparing current security posture against desired state or compliance requirements. Identifies gaps between where you are and where you need to be. Used for roadmap planning and risk assessment.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-1", "1.1", "assessment"],
    },
    {
        "term": "Technical Controls",
        "definition": "Security measures implemented through technology: firewalls, encryption, IDS/IPS, antivirus, ACLs, DLP. Also called logical controls. Enforce security policy automatically through hardware or software.",
        "difficulty": "beginner",
        "tags": ["sy0-701", "domain-1", "1.1", "controls"],
    },
    {
        "term": "Managerial Controls",
        "definition": "Administrative security measures: policies, procedures, risk assessments, security awareness training, background checks. Also called administrative controls. Focus on managing risk through documentation and oversight.",
        "difficulty": "beginner",
        "tags": ["sy0-701", "domain-1", "1.1", "controls"],
    },
    {
        "term": "Operational Controls",
        "definition": "Day-to-day security procedures performed by people: guard patrols, incident response procedures, change management, backup verification. Bridge between managerial policy and technical implementation.",
        "difficulty": "beginner",
        "tags": ["sy0-701", "domain-1", "1.1", "controls"],
    },
    {
        "term": "Physical Controls",
        "definition": "Tangible security measures: locks, fences, mantraps, bollards, cameras, biometric scanners, lighting, cable locks. Protect physical assets and deter/detect unauthorized physical access.",
        "difficulty": "beginner",
        "tags": ["sy0-701", "domain-1", "1.1", "controls"],
    },
    {
        "term": "Preventive Controls",
        "definition": "Controls designed to stop security incidents before they occur. Examples: firewalls, encryption, access controls, security training, locks. The first line of defense -- block the threat entirely.",
        "difficulty": "beginner",
        "tags": ["sy0-701", "domain-1", "1.1", "control-types"],
    },
    {
        "term": "Detective Controls",
        "definition": "Controls that identify and alert on security incidents during or after occurrence. Examples: IDS, log monitoring, SIEM, security cameras, audit trails. Critical for incident response and forensics.",
        "difficulty": "beginner",
        "tags": ["sy0-701", "domain-1", "1.1", "control-types"],
    },
    {
        "term": "Corrective Controls",
        "definition": "Controls that fix or restore systems after a security incident. Examples: patching, backup restoration, incident response procedures, antivirus quarantine. Minimize damage and restore normal operations.",
        "difficulty": "beginner",
        "tags": ["sy0-701", "domain-1", "1.1", "control-types"],
    },
    {
        "term": "Deterrent Controls",
        "definition": "Controls that discourage security violations through fear of consequence. Examples: warning banners, security cameras (visible), guard presence, acceptable use policies. Psychological -- may not physically prevent access.",
        "difficulty": "beginner",
        "tags": ["sy0-701", "domain-1", "1.1", "control-types"],
    },
    {
        "term": "Compensating Controls",
        "definition": "Alternative controls used when primary controls cannot be implemented. Must meet the intent of the original requirement. Example: using MFA when smart cards are not feasible. Must be documented and approved.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-1", "1.1", "control-types"],
    },
    {
        "term": "Directive Controls",
        "definition": "Controls that direct or mandate behavior through policy. Examples: acceptable use policies, security policies, procedures, standards. Tell people what they should or should not do.",
        "difficulty": "beginner",
        "tags": ["sy0-701", "domain-1", "1.1", "control-types"],
    },

    # 1.2 Fundamental security concepts
    {
        "term": "Zero Trust",
        "definition": "Security model that assumes no implicit trust regardless of network location. 'Never trust, always verify.' Core principles: verify explicitly, least privilege access, assume breach. Requires continuous authentication and micro-segmentation.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-1", "1.2", "architecture"],
    },
    {
        "term": "Control Plane vs Data Plane",
        "definition": "Control plane: manages how data is forwarded (routing tables, policies, adaptive identity, threat scope reduction). Data plane: handles the actual forwarding of traffic based on control plane decisions. Zero trust uses control plane for policy enforcement.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-1", "1.2", "zero-trust"],
    },
    {
        "term": "Adaptive Identity",
        "definition": "Zero trust concept where authentication requirements change based on context: location, device, behavior, risk level. Higher risk contexts require stronger authentication. Part of the control plane in zero trust architecture.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-1", "1.2", "zero-trust"],
    },
    {
        "term": "Defense in Depth",
        "definition": "Layered security strategy using multiple overlapping controls at different levels. If one layer fails, others still protect. Layers: physical, network, host, application, data. Also called layered security or onion model.",
        "difficulty": "beginner",
        "tags": ["sy0-701", "domain-1", "1.2", "strategy"],
    },
    {
        "term": "Least Privilege",
        "definition": "Users and processes should have only the minimum permissions necessary to perform their function. Reduces attack surface and limits blast radius of compromised accounts. Foundation of access control and zero trust.",
        "difficulty": "beginner",
        "tags": ["sy0-701", "domain-1", "1.2", "access-control"],
    },
    {
        "term": "Separation of Duties",
        "definition": "No single person should control all phases of a critical process. Prevents fraud and errors by requiring multiple people for sensitive operations. Example: one person writes code, another reviews and deploys.",
        "difficulty": "beginner",
        "tags": ["sy0-701", "domain-1", "1.2", "access-control"],
    },

    # 1.3 Change management
    {
        "term": "Change Management Process",
        "definition": "Structured approach to transitioning systems from current state to desired state. Steps: request, review/approve, test, implement, document. Prevents unauthorized changes and reduces risk of outages. Includes CAB (Change Advisory Board) review.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-1", "1.3", "operations"],
    },
    {
        "term": "Change Advisory Board (CAB)",
        "definition": "Group responsible for evaluating and approving change requests. Includes stakeholders from IT, security, management, and affected business units. Assesses risk, impact, and rollback plans before approving changes.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-1", "1.3", "governance"],
    },

    # 1.4 Cryptography
    {
        "term": "Symmetric Encryption",
        "definition": "Uses the same key for encryption and decryption. Fast, efficient for bulk data. Examples: AES (128/192/256-bit), 3DES, Blowfish, ChaCha20. Key distribution is the main challenge -- both parties need the shared secret.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-1", "1.4", "cryptography"],
    },
    {
        "term": "Asymmetric Encryption",
        "definition": "Uses a key pair: public key encrypts, private key decrypts (or private signs, public verifies). Slower than symmetric. Examples: RSA, ECC, Diffie-Hellman. Solves key distribution problem. Used for key exchange, digital signatures, PKI.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-1", "1.4", "cryptography"],
    },
    {
        "term": "Hashing",
        "definition": "One-way function producing fixed-length digest from variable input. Cannot be reversed. Used for integrity verification, password storage, digital signatures. Algorithms: SHA-256, SHA-3, MD5 (insecure), HMAC (keyed hash). Collision = two inputs producing same hash.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-1", "1.4", "cryptography"],
    },
    {
        "term": "Digital Signature",
        "definition": "Encrypted hash of a message using sender's private key. Provides authentication (proves sender identity), integrity (detects tampering), and non-repudiation (sender cannot deny signing). Verified using sender's public key.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-1", "1.4", "cryptography"],
    },
    {
        "term": "PKI (Public Key Infrastructure)",
        "definition": "Framework for managing digital certificates and public keys. Components: Certificate Authority (CA), Registration Authority (RA), Certificate Revocation List (CRL), OCSP. Trust hierarchy: root CA > intermediate CA > end-entity certificates.",
        "difficulty": "advanced",
        "tags": ["sy0-701", "domain-1", "1.4", "cryptography", "certificates"],
    },
    {
        "term": "Key Stretching",
        "definition": "Technique to strengthen weak passwords by adding computational cost to hashing. Makes brute force attacks slower. Algorithms: PBKDF2, bcrypt, scrypt, Argon2. Adds salt + multiple iterations to increase time per hash attempt.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-1", "1.4", "cryptography", "passwords"],
    },
    {
        "term": "Perfect Forward Secrecy (PFS)",
        "definition": "Property where compromise of long-term keys does not compromise past session keys. Each session uses unique ephemeral keys (Diffie-Hellman Ephemeral). If a server's private key is later stolen, previously captured traffic cannot be decrypted.",
        "difficulty": "advanced",
        "tags": ["sy0-701", "domain-1", "1.4", "cryptography", "tls"],
    },
    {
        "term": "Steganography",
        "definition": "Hiding data within other data (images, audio, video, text) so its existence is concealed. Unlike encryption which scrambles data visibly, steganography hides the fact that secret data exists at all. Can be combined with encryption.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-1", "1.4", "cryptography"],
    },
    {
        "term": "Blockchain",
        "definition": "Distributed, immutable ledger using cryptographic hashing to chain blocks together. Each block contains a hash of the previous block, creating tamper-evident chain. Used for cryptocurrency, supply chain verification, decentralized identity.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-1", "1.4", "cryptography"],
    },
    {
        "term": "Salting",
        "definition": "Adding random data to a password before hashing. Each password gets a unique salt, stored alongside the hash. Prevents rainbow table attacks and ensures identical passwords produce different hashes. Salt does not need to be secret.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-1", "1.4", "cryptography", "passwords"],
    },

    # =========================================================================
    # DOMAIN 2: Threats, Vulnerabilities, and Mitigations (22%)
    # =========================================================================

    # 2.1 Threat actors
    {
        "term": "Threat Actor Types",
        "definition": "Categories of adversaries: Nation-state (APT, highest sophistication/funding), organized crime (financially motivated), hacktivist (politically motivated), insider threat (authorized access), script kiddie (low skill, uses existing tools), shadow IT (unauthorized internal systems).",
        "difficulty": "beginner",
        "tags": ["sy0-701", "domain-2", "2.1", "threats"],
    },
    {
        "term": "Attack Surface",
        "definition": "Sum of all points where an attacker can try to enter or extract data. Includes network interfaces, open ports, APIs, user accounts, physical access points, supply chain. Reducing attack surface is a core security principle.",
        "difficulty": "beginner",
        "tags": ["sy0-701", "domain-2", "2.1", "fundamentals"],
    },
    {
        "term": "Threat Intelligence",
        "definition": "Evidence-based knowledge about existing or emerging threats. Sources: OSINT, dark web monitoring, ISACs, vendor feeds. Types: strategic (high-level trends), tactical (TTPs), operational (specific campaigns), technical (IOCs like IPs and hashes).",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-2", "2.1", "threat-intel"],
    },
    {
        "term": "Indicators of Compromise (IOC)",
        "definition": "Forensic evidence that a breach has occurred. Examples: unusual outbound traffic, known malicious IP addresses, suspicious file hashes, unexpected registry changes, anomalous login patterns. Shared via STIX/TAXII formats.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-2", "2.1", "threat-intel"],
    },

    # 2.2 Threat vectors and attack surfaces
    {
        "term": "Phishing",
        "definition": "Social engineering via fraudulent emails to steal credentials or deliver malware. Variants: spear phishing (targeted individual), whaling (executives), vishing (voice), smishing (SMS), pharming (DNS redirect). #1 initial attack vector.",
        "difficulty": "beginner",
        "tags": ["sy0-701", "domain-2", "2.2", "social-engineering"],
    },
    {
        "term": "Social Engineering",
        "definition": "Manipulating people into breaking security procedures. Techniques: pretexting (fake scenario), baiting (enticing offer), tailgating (following through secure door), shoulder surfing, dumpster diving, watering hole attack, typosquatting.",
        "difficulty": "beginner",
        "tags": ["sy0-701", "domain-2", "2.2", "social-engineering"],
    },
    {
        "term": "Business Email Compromise (BEC)",
        "definition": "Attacker impersonates executive or trusted partner via email to authorize fraudulent transactions. Often targets finance department. Uses spoofed or compromised email accounts. No malware -- purely social engineering. Costs businesses billions annually.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-2", "2.2", "social-engineering"],
    },
    {
        "term": "Supply Chain Attack",
        "definition": "Compromising a trusted vendor/supplier to attack their customers. Examples: SolarWinds (trojanized update), compromised npm packages, hardware implants. Exploits trust relationships. Hard to detect because malicious code comes from trusted source.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-2", "2.2", "attack-vectors"],
    },
    {
        "term": "Watering Hole Attack",
        "definition": "Compromising a website frequently visited by the target group. Attacker injects exploit code into the legitimate site. When targets visit, they get infected. Named after predators waiting at watering holes. Targets specific communities or industries.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-2", "2.2", "attack-vectors"],
    },

    # 2.3 Vulnerabilities
    {
        "term": "Zero-Day Vulnerability",
        "definition": "Previously unknown vulnerability with no available patch. Called 'zero-day' because defenders have had zero days to fix it. Extremely valuable to attackers (sold on dark web). Mitigated by defense in depth, behavioral detection, virtual patching.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-2", "2.3", "vulnerabilities"],
    },
    {
        "term": "SQL Injection",
        "definition": "Inserting malicious SQL statements into application queries via user input. Can read, modify, or delete database data, bypass authentication, execute OS commands. Mitigated by parameterized queries (prepared statements), input validation, least privilege DB accounts.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-2", "2.3", "application-attacks"],
    },
    {
        "term": "Cross-Site Scripting (XSS)",
        "definition": "Injecting malicious scripts into web pages viewed by other users. Types: Stored (persistent in DB), Reflected (in URL parameters), DOM-based (client-side). Can steal cookies, session tokens, redirect users. Mitigated by output encoding, CSP headers, input validation.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-2", "2.3", "application-attacks"],
    },
    {
        "term": "CSRF (Cross-Site Request Forgery)",
        "definition": "Tricking authenticated users into performing unintended actions on a web app. Attacker crafts a request that the victim's browser submits with their valid session. Mitigated by anti-CSRF tokens, SameSite cookies, requiring re-authentication for sensitive actions.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-2", "2.3", "application-attacks"],
    },
    {
        "term": "Buffer Overflow",
        "definition": "Writing data beyond allocated memory buffer, potentially overwriting adjacent memory. Can crash programs or enable arbitrary code execution. Mitigated by ASLR, DEP/NX bit, stack canaries, bounds checking, safe programming languages.",
        "difficulty": "advanced",
        "tags": ["sy0-701", "domain-2", "2.3", "application-attacks"],
    },
    {
        "term": "Race Condition",
        "definition": "Vulnerability where system behavior depends on timing of events. TOCTOU (Time of Check to Time of Use): resource changes between verification and usage. Can lead to privilege escalation or file manipulation. Mitigated by locking mechanisms and atomic operations.",
        "difficulty": "advanced",
        "tags": ["sy0-701", "domain-2", "2.3", "vulnerabilities"],
    },
    {
        "term": "Privilege Escalation",
        "definition": "Gaining higher access than authorized. Vertical: regular user to admin. Horizontal: accessing another user's resources. Exploits misconfigurations, unpatched vulnerabilities, or weak access controls. Key post-exploitation technique in attack chains.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-2", "2.3", "vulnerabilities"],
    },
    {
        "term": "Directory Traversal",
        "definition": "Accessing files outside the intended directory by manipulating file path input (e.g., ../../etc/passwd). Exploits insufficient input validation in web apps. Mitigated by chroot jails, input sanitization, proper access controls on the file system.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-2", "2.3", "application-attacks"],
    },
    {
        "term": "Insecure Direct Object Reference (IDOR)",
        "definition": "When an application exposes internal object references (like database IDs) and fails to verify authorization. Example: changing /profile?id=123 to id=456 to access another user's data. Part of broken access control (OWASP #1).",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-2", "2.3", "application-attacks"],
    },

    # 2.4 Malware
    {
        "term": "Ransomware",
        "definition": "Malware that encrypts victim's files and demands payment for decryption key. Modern variants exfiltrate data first (double extortion). Delivery: phishing, RDP brute force, exploit kits. Mitigation: offline backups, patching, network segmentation, EDR.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-2", "2.4", "malware"],
    },
    {
        "term": "Trojan Horse",
        "definition": "Malware disguised as legitimate software. Does not self-replicate (unlike viruses/worms). Types: RAT (Remote Access Trojan), banking trojan, backdoor. Often delivered via social engineering, drive-by downloads, or bundled with pirated software.",
        "difficulty": "beginner",
        "tags": ["sy0-701", "domain-2", "2.4", "malware"],
    },
    {
        "term": "Rootkit",
        "definition": "Malware that hides deep in the OS to maintain persistent, undetected access. Types: kernel-level (modifies OS kernel), bootkit (infects boot process), firmware rootkit. Extremely difficult to detect and remove. May require full OS reinstall.",
        "difficulty": "advanced",
        "tags": ["sy0-701", "domain-2", "2.4", "malware"],
    },
    {
        "term": "Fileless Malware",
        "definition": "Malware that operates entirely in memory without writing files to disk. Uses legitimate tools (PowerShell, WMI, macros) to execute malicious code. Evades traditional antivirus. Detected by behavioral analysis, EDR, and memory forensics.",
        "difficulty": "advanced",
        "tags": ["sy0-701", "domain-2", "2.4", "malware"],
    },
    {
        "term": "Keylogger",
        "definition": "Software or hardware that records keystrokes. Software keyloggers capture at OS or browser level. Hardware keyloggers are physical devices between keyboard and computer. Used to steal passwords, credit card numbers, sensitive communications.",
        "difficulty": "beginner",
        "tags": ["sy0-701", "domain-2", "2.4", "malware"],
    },
    {
        "term": "Worm",
        "definition": "Self-replicating malware that spreads across networks without user interaction. Unlike viruses, worms do not need a host file. Can consume bandwidth, deliver payloads, create botnets. Examples: WannaCry, NotPetya, Stuxnet.",
        "difficulty": "beginner",
        "tags": ["sy0-701", "domain-2", "2.4", "malware"],
    },
    {
        "term": "Logic Bomb",
        "definition": "Malicious code that triggers when specific conditions are met (date, event, user action). Often planted by insiders. Dormant until trigger condition. Example: code that deletes database if an employee's account is deactivated.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-2", "2.4", "malware"],
    },
    {
        "term": "Botnet",
        "definition": "Network of compromised devices (bots/zombies) controlled by an attacker (bot herder) via C2 server. Used for DDoS attacks, spam, cryptomining, credential stuffing. Communication via IRC, HTTP, P2P, or DNS tunneling.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-2", "2.4", "malware"],
    },

    # 2.5 Mitigation techniques
    {
        "term": "Patch Management",
        "definition": "Process of identifying, acquiring, testing, and deploying software updates. Critical for closing known vulnerabilities. Requires testing before production deployment. Automated tools: WSUS, SCCM, Ansible. Track via CVE database.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-2", "2.5", "mitigation"],
    },
    {
        "term": "Hardening",
        "definition": "Reducing attack surface by removing unnecessary services, closing unused ports, disabling default accounts, applying security baselines. Guides: CIS Benchmarks, DISA STIGs, vendor hardening guides. Applies to OS, applications, network devices, firmware.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-2", "2.5", "mitigation"],
    },
    {
        "term": "Network Segmentation",
        "definition": "Dividing a network into isolated segments to limit lateral movement. Uses VLANs, subnets, firewalls between segments. Limits blast radius of a breach. Critical for PCI-DSS (cardholder data isolation) and zero trust architecture.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-2", "2.5", "mitigation", "network"],
    },

    # =========================================================================
    # DOMAIN 3: Security Architecture (18%)
    # =========================================================================

    # 3.1 Security architecture models
    {
        "term": "Cloud Responsibility Models",
        "definition": "Shared responsibility between cloud provider and customer. IaaS: customer manages OS up. PaaS: customer manages apps/data. SaaS: provider manages almost everything. Provider always manages physical/network. Customer always manages data classification and access.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-3", "3.1", "cloud"],
    },
    {
        "term": "IaaS vs PaaS vs SaaS",
        "definition": "IaaS (Infrastructure): VMs, storage, networking (AWS EC2, Azure VMs). PaaS (Platform): runtime environment for apps (Heroku, App Engine). SaaS (Software): complete applications (Office 365, Salesforce). Each shifts more responsibility to provider.",
        "difficulty": "beginner",
        "tags": ["sy0-701", "domain-3", "3.1", "cloud"],
    },
    {
        "term": "Microservices Architecture",
        "definition": "Application design where each function runs as independent, loosely coupled service. Communicates via APIs. Benefits: independent scaling, technology diversity, fault isolation. Security considerations: API security, service mesh, container security.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-3", "3.1", "architecture"],
    },
    {
        "term": "Infrastructure as Code (IaC)",
        "definition": "Managing and provisioning infrastructure through code/templates rather than manual configuration. Tools: Terraform, CloudFormation, Ansible. Enables version control, consistency, automated deployment. Security: scan templates for misconfigurations before deployment.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-3", "3.1", "cloud", "devops"],
    },
    {
        "term": "Serverless Computing",
        "definition": "Cloud execution model where the provider manages all infrastructure. Code runs in response to events (functions). Examples: AWS Lambda, Azure Functions. Security: limited attack surface but requires securing function code, permissions, and dependencies.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-3", "3.1", "cloud"],
    },
    {
        "term": "Containerization",
        "definition": "Packaging applications with their dependencies into isolated containers. Docker is the most common runtime. Lighter than VMs (share host OS kernel). Security: image scanning, minimal base images, read-only filesystems, no root in containers.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-3", "3.1", "virtualization"],
    },

    # 3.2 Security infrastructure
    {
        "term": "Firewall Types",
        "definition": "Packet filter (Layer 3-4, ACL-based), stateful inspection (tracks connections), application/proxy firewall (Layer 7, deep inspection), NGFW (IPS + app awareness + TLS inspection), WAF (web application specific). Each adds inspection depth and overhead.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-3", "3.2", "network-security"],
    },
    {
        "term": "IDS vs IPS",
        "definition": "IDS (Intrusion Detection System): monitors and alerts on suspicious activity -- passive. IPS (Intrusion Prevention System): monitors AND blocks threats inline -- active. Detection methods: signature-based (known patterns), anomaly-based (deviation from baseline), heuristic.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-3", "3.2", "network-security"],
    },
    {
        "term": "SIEM (Security Information and Event Management)",
        "definition": "Platform that aggregates logs from multiple sources, correlates events, detects threats, and generates alerts. Features: log collection, real-time analysis, dashboards, compliance reporting. Examples: Splunk, Microsoft Sentinel, QRadar. Central nervous system of SOC.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-3", "3.2", "monitoring"],
    },
    {
        "term": "SOAR (Security Orchestration, Automation, and Response)",
        "definition": "Platform that automates incident response workflows (playbooks), orchestrates security tools, and manages cases. Reduces mean time to respond (MTTR). Integrates with SIEM, firewalls, EDR, ticketing systems. Automates repetitive SOC tasks.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-3", "3.2", "monitoring"],
    },
    {
        "term": "VPN (Virtual Private Network)",
        "definition": "Encrypted tunnel over public network for secure remote access. Types: site-to-site (connects networks), remote access (connects user to network). Protocols: IPsec (L3), SSL/TLS VPN (L4-7), WireGuard. Split tunnel vs full tunnel affects what traffic is protected.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-3", "3.2", "network-security"],
    },
    {
        "term": "NAC (Network Access Control)",
        "definition": "Controls device access to the network based on compliance. Checks: antivirus status, patch level, OS version, certificates. Non-compliant devices quarantined to remediation VLAN. Technologies: 802.1X, agent-based, agentless. Enforces endpoint security policies.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-3", "3.2", "network-security"],
    },
    {
        "term": "DMZ (Demilitarized Zone)",
        "definition": "Network segment between external (internet) and internal networks. Hosts public-facing servers (web, email, DNS) while protecting internal network. Typically uses two firewalls or dual-homed firewall. Limits exposure if public server is compromised.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-3", "3.2", "network-security"],
    },
    {
        "term": "Load Balancer",
        "definition": "Distributes traffic across multiple servers for availability and performance. Types: Layer 4 (TCP/UDP) and Layer 7 (HTTP/HTTPS with content-based routing). Can perform SSL offloading. Security: DDoS mitigation, session persistence, health checks.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-3", "3.2", "infrastructure"],
    },
    {
        "term": "Proxy Server",
        "definition": "Intermediary between clients and servers. Forward proxy: client-side, filters outbound traffic, caches content, hides client IP. Reverse proxy: server-side, load balances, caches, terminates SSL, hides backend infrastructure. Both provide logging and access control.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-3", "3.2", "network-security"],
    },
    {
        "term": "SDN (Software-Defined Networking)",
        "definition": "Separates network control plane from data plane, enabling centralized programmatic network management. Controller makes routing decisions, switches forward traffic. Benefits: automation, rapid provisioning, micro-segmentation. Security: single point of failure if controller compromised.",
        "difficulty": "advanced",
        "tags": ["sy0-701", "domain-3", "3.2", "network"],
    },
    {
        "term": "EDR (Endpoint Detection and Response)",
        "definition": "Advanced endpoint security that monitors, detects, and responds to threats on endpoints. Goes beyond antivirus: behavioral analysis, threat hunting, automated response, forensic data collection. Provides visibility into endpoint activity for incident investigation.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-3", "3.2", "endpoint"],
    },
    {
        "term": "XDR (Extended Detection and Response)",
        "definition": "Extends EDR across multiple security layers: endpoints, network, cloud, email, identity. Provides unified detection, investigation, and response. Correlates data across security domains for better threat visibility. Evolution of EDR + NDR + SIEM.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-3", "3.2", "monitoring"],
    },

    # 3.3 Secure communications
    {
        "term": "TLS 1.3",
        "definition": "Latest version of Transport Layer Security. Improvements over 1.2: 1-RTT handshake (faster), removed weak ciphers (RC4, SHA-1, CBC), mandatory PFS, 0-RTT resumption. Only supports AEAD cipher suites (AES-GCM, ChaCha20-Poly1305). Standard for HTTPS.",
        "difficulty": "advanced",
        "tags": ["sy0-701", "domain-3", "3.3", "cryptography", "protocols"],
    },
    {
        "term": "IPsec",
        "definition": "Suite of protocols for securing IP communications. AH (Authentication Header): integrity only. ESP (Encapsulating Security Payload): integrity + confidentiality. Modes: transport (payload only) and tunnel (entire packet). Used in site-to-site VPNs. IKE handles key exchange.",
        "difficulty": "advanced",
        "tags": ["sy0-701", "domain-3", "3.3", "protocols", "vpn"],
    },
    {
        "term": "802.1X",
        "definition": "Port-based network access control standard. Components: supplicant (client), authenticator (switch/AP), authentication server (RADIUS). EAP carries authentication data. Prevents unauthorized devices from accessing the network. Used for wired and wireless NAC.",
        "difficulty": "advanced",
        "tags": ["sy0-701", "domain-3", "3.3", "protocols", "network-security"],
    },
    {
        "term": "DNSSEC",
        "definition": "DNS Security Extensions that add authentication to DNS responses using digital signatures. Prevents DNS spoofing and cache poisoning. Uses chain of trust from root zone. Adds RRSIG, DNSKEY, DS, NSEC records. Does not encrypt DNS queries (that's DoH/DoT).",
        "difficulty": "advanced",
        "tags": ["sy0-701", "domain-3", "3.3", "protocols", "dns"],
    },

    # 3.4 Data protection
    {
        "term": "Data Loss Prevention (DLP)",
        "definition": "Technology that detects and prevents unauthorized data exfiltration. Types: network DLP (monitors traffic), endpoint DLP (monitors local actions), cloud DLP (monitors cloud services). Uses content inspection, pattern matching, classification labels. Blocks or alerts on policy violations.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-3", "3.4", "data-security"],
    },
    {
        "term": "Data Classification",
        "definition": "Categorizing data based on sensitivity and value. Government: Top Secret > Secret > Confidential > Unclassified. Commercial: Restricted > Confidential > Internal > Public. Drives encryption, access control, handling, and retention requirements.",
        "difficulty": "beginner",
        "tags": ["sy0-701", "domain-3", "3.4", "data-security"],
    },
    {
        "term": "Data at Rest vs In Transit vs In Use",
        "definition": "Three data states requiring different protection. At rest: stored data -- encrypt with AES, BitLocker, LUKS. In transit: moving data -- encrypt with TLS, IPsec, VPN. In use: data being processed in memory -- protect with secure enclaves, memory encryption, access controls.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-3", "3.4", "data-security"],
    },
    {
        "term": "Data Sovereignty",
        "definition": "Concept that data is subject to laws of the country where it is stored. Affects cloud deployments across regions. GDPR requires EU citizen data stay in EU or equivalent protection. Must consider data residency requirements when choosing cloud regions.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-3", "3.4", "compliance"],
    },

    # =========================================================================
    # DOMAIN 4: Security Operations (28%)
    # =========================================================================

    # 4.1 Security techniques
    {
        "term": "Vulnerability Scanning",
        "definition": "Automated testing to identify known vulnerabilities in systems. Tools: Nessus, Qualys, OpenVAS. Types: credentialed (with login -- deeper), non-credentialed (external view). Outputs CVE-referenced reports. Should be regular (weekly/monthly) and after changes.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-4", "4.1", "assessment"],
    },
    {
        "term": "Penetration Testing",
        "definition": "Authorized simulated attack to identify exploitable vulnerabilities. Phases: planning, reconnaissance, scanning, exploitation, post-exploitation, reporting. Types: black box (no knowledge), white box (full knowledge), gray box (partial). Rules of engagement define scope.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-4", "4.1", "assessment"],
    },
    {
        "term": "CVSS (Common Vulnerability Scoring System)",
        "definition": "Standardized framework for rating vulnerability severity (0-10). Base metrics: attack vector, complexity, privileges required, user interaction, scope, impact (CIA). Scores: None (0), Low (0.1-3.9), Medium (4.0-6.9), High (7.0-8.9), Critical (9.0-10.0).",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-4", "4.1", "vulnerability-management"],
    },
    {
        "term": "SCAP (Security Content Automation Protocol)",
        "definition": "Suite of standards for automated vulnerability management. Components: CVE (vulnerability naming), CVSS (scoring), CPE (platform naming), CCE (configuration naming), OVAL (vulnerability assessment language), XCCDF (security checklists). Enables automated compliance checking.",
        "difficulty": "advanced",
        "tags": ["sy0-701", "domain-4", "4.1", "standards"],
    },

    # 4.2 Security monitoring
    {
        "term": "Log Management",
        "definition": "Collection, aggregation, storage, and analysis of log data from systems and applications. Sources: OS logs, application logs, firewall logs, authentication logs, DNS logs. Retention requirements vary by compliance framework. Central logging prevents log tampering.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-4", "4.2", "monitoring"],
    },
    {
        "term": "NetFlow/sFlow/IPFIX",
        "definition": "Network traffic metadata collection protocols. Capture source/destination IPs, ports, protocol, byte count, timestamps. Do NOT capture packet content (unlike full packet capture). Used for traffic analysis, anomaly detection, capacity planning. Less storage than pcap.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-4", "4.2", "monitoring", "network"],
    },
    {
        "term": "SNMP (Simple Network Management Protocol)",
        "definition": "Protocol for monitoring and managing network devices. Components: manager (NMS), agent (device), MIB (data structure). Versions: v1/v2c (community strings, insecure), v3 (authentication + encryption). Traps: unsolicited alerts from agents. Use v3 with encryption.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-4", "4.2", "protocols", "monitoring"],
    },

    # 4.3 Incident response
    {
        "term": "Incident Response Phases",
        "definition": "NIST SP 800-61: 1) Preparation (tools, training, playbooks), 2) Detection and Analysis (identify and triage), 3) Containment, Eradication, and Recovery (isolate, remove threat, restore), 4) Post-Incident Activity (lessons learned, update procedures). Iterative, not always linear.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-4", "4.3", "incident-response"],
    },
    {
        "term": "Chain of Custody",
        "definition": "Documented trail showing evidence collection, transfer, and handling. Records who, what, when, where, how for each evidence interaction. Required for evidence admissibility in legal proceedings. Breaks in chain can invalidate evidence. Use evidence bags and hashing.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-4", "4.3", "forensics"],
    },
    {
        "term": "Order of Volatility",
        "definition": "Collect most volatile evidence first during forensic acquisition. Order: 1) CPU registers/cache, 2) RAM, 3) swap/page files, 4) disk, 5) remote logging, 6) physical config, 7) archival media. RAM contents are lost on power off. Disk persists but can be overwritten.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-4", "4.3", "forensics"],
    },
    {
        "term": "Forensic Imaging",
        "definition": "Creating bit-for-bit copy of storage media for investigation. Must preserve original evidence (write blockers). Tools: dd, FTK Imager, EnCase. Hash the original and copy (SHA-256) to verify integrity. Work only on the forensic copy, never the original.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-4", "4.3", "forensics"],
    },
    {
        "term": "Containment Strategies",
        "definition": "Actions to limit incident spread during response. Short-term: isolate affected systems (network disconnect, disable accounts). Long-term: apply temporary fixes while planning eradication. Segmentation containment limits lateral movement. Balance: contain threat vs maintain evidence.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-4", "4.3", "incident-response"],
    },
    {
        "term": "Playbook/Runbook",
        "definition": "Documented, step-by-step procedures for responding to specific incident types. Playbook: strategic response guide. Runbook: detailed technical procedures. Examples: ransomware playbook, data breach playbook, DDoS response. SOAR automates playbook execution.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-4", "4.3", "incident-response"],
    },

    # 4.4 Digital forensics
    {
        "term": "Legal Hold",
        "definition": "Directive to preserve all potentially relevant documents and data when litigation is anticipated. Overrides normal retention/deletion policies. Applies to emails, files, backups, logs. Failure to comply can result in spoliation sanctions.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-4", "4.4", "forensics", "legal"],
    },
    {
        "term": "e-Discovery",
        "definition": "Process of identifying, collecting, and producing electronically stored information (ESI) for legal proceedings. Phases: identification, preservation, collection, processing, review, production. Must maintain chain of custody and defensible process.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-4", "4.4", "forensics", "legal"],
    },

    # 4.5 Data sources for investigation
    {
        "term": "Packet Capture (pcap)",
        "definition": "Recording complete network packets for analysis. Tools: Wireshark, tcpdump. Captures full payload (unlike NetFlow). Used for forensics, malware analysis, protocol debugging. Storage-intensive. Decrypt TLS with server private key or session keys.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-4", "4.5", "forensics", "network"],
    },
    {
        "term": "Memory Forensics",
        "definition": "Analyzing volatile memory (RAM) dumps for artifacts. Can recover: running processes, network connections, encryption keys, malware in memory, command history. Tools: Volatility, Rekall. Critical for fileless malware detection. Must capture before power off.",
        "difficulty": "advanced",
        "tags": ["sy0-701", "domain-4", "4.5", "forensics"],
    },

    # 4.6 Identity and access management
    {
        "term": "MFA (Multi-Factor Authentication)",
        "definition": "Requiring two or more authentication factors: something you know (password), something you have (token, phone), something you are (biometric), somewhere you are (location), something you do (behavior). Dramatically reduces account compromise risk. FIDO2/WebAuthn is phishing-resistant.",
        "difficulty": "beginner",
        "tags": ["sy0-701", "domain-4", "4.6", "identity"],
    },
    {
        "term": "SSO (Single Sign-On)",
        "definition": "Authentication scheme allowing users to log in once and access multiple applications. Protocols: SAML (XML, enterprise), OAuth 2.0 (authorization, API), OIDC (authentication layer on OAuth). Reduces password fatigue but creates single point of failure.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-4", "4.6", "identity"],
    },
    {
        "term": "SAML (Security Assertion Markup Language)",
        "definition": "XML-based open standard for exchanging authentication/authorization data between identity provider (IdP) and service provider (SP). Used for enterprise SSO. Three roles: principal (user), IdP (authenticates), SP (provides resource). Browser-based redirects carry assertions.",
        "difficulty": "advanced",
        "tags": ["sy0-701", "domain-4", "4.6", "identity", "protocols"],
    },
    {
        "term": "OAuth 2.0 / OIDC",
        "definition": "OAuth 2.0: authorization framework for delegated access (grants tokens, not credentials). OIDC: authentication layer built on OAuth (adds ID token with user identity). Grant types: authorization code, client credentials, device code. Used by Google, GitHub, Azure AD.",
        "difficulty": "advanced",
        "tags": ["sy0-701", "domain-4", "4.6", "identity", "protocols"],
    },
    {
        "term": "RBAC (Role-Based Access Control)",
        "definition": "Access control model where permissions are assigned to roles, and users are assigned to roles. Simplifies administration for large organizations. Example: 'Doctor' role has access to patient records. Most common enterprise access model.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-4", "4.6", "access-control"],
    },
    {
        "term": "ABAC (Attribute-Based Access Control)",
        "definition": "Access control using attributes (user, resource, environment, action) evaluated by policy engine. More granular than RBAC. Example: allow if user.department=finance AND resource.classification=confidential AND time=business_hours. XACML is the standard policy language.",
        "difficulty": "advanced",
        "tags": ["sy0-701", "domain-4", "4.6", "access-control"],
    },
    {
        "term": "PAM (Privileged Access Management)",
        "definition": "Controls and monitors access to privileged accounts (admin, root, service accounts). Features: password vaulting, session recording, just-in-time access, credential rotation. Reduces risk of credential theft and insider threats. Tools: CyberArk, BeyondTrust.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-4", "4.6", "access-control"],
    },
    {
        "term": "Federation",
        "definition": "Trust relationship between organizations allowing users to authenticate with their home IdP and access resources in partner organizations. Standards: SAML, OIDC, WS-Federation. Enables cross-org SSO without sharing credentials.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-4", "4.6", "identity"],
    },

    # 4.7 Automation and orchestration
    {
        "term": "SCAP and Automated Compliance",
        "definition": "Using SCAP standards to automate security configuration checking and vulnerability assessment. Tools scan systems against CIS Benchmarks or DISA STIGs. OVAL defines vulnerability tests, XCCDF defines checklists. Enables continuous compliance monitoring.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-4", "4.7", "automation"],
    },

    # =========================================================================
    # DOMAIN 5: Security Program Management and Oversight (20%)
    # =========================================================================

    # 5.1 Governance
    {
        "term": "Security Frameworks",
        "definition": "Structured approaches to implementing security programs. NIST CSF (Identify, Protect, Detect, Respond, Recover), ISO 27001/27002 (ISMS), CIS Controls (prioritized actions), COBIT (IT governance). Choice depends on industry, regulatory requirements, and organizational maturity.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-5", "5.1", "governance"],
    },
    {
        "term": "NIST Cybersecurity Framework (CSF)",
        "definition": "Voluntary framework with 5 functions: Identify (asset management, risk assessment), Protect (access control, training), Detect (monitoring, anomalies), Respond (planning, communications), Recover (restoration, improvements). Tiers measure maturity. Most widely adopted US framework.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-5", "5.1", "governance", "frameworks"],
    },
    {
        "term": "ISO 27001/27002",
        "definition": "International standard for Information Security Management Systems (ISMS). 27001: requirements for establishing, implementing, maintaining ISMS (certifiable). 27002: code of practice with security controls guidance. Annex A has 93 controls across 4 themes.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-5", "5.1", "governance", "frameworks"],
    },
    {
        "term": "Security Policy Types",
        "definition": "AUP (Acceptable Use): what users can/cannot do. Information security policy: overall security program. Password policy: complexity/rotation requirements. Data handling: classification and protection rules. Incident response policy: how to handle incidents. Policies = mandatory rules.",
        "difficulty": "beginner",
        "tags": ["sy0-701", "domain-5", "5.1", "governance"],
    },
    {
        "term": "Standards vs Baselines vs Guidelines vs Procedures",
        "definition": "Standards: mandatory requirements (must use AES-256). Baselines: minimum security configurations (CIS benchmark settings). Guidelines: recommended practices (non-mandatory). Procedures: step-by-step instructions for tasks. Hierarchy: Policy > Standard > Baseline > Guideline > Procedure.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-5", "5.1", "governance"],
    },

    # 5.2 Risk management
    {
        "term": "Risk Assessment",
        "definition": "Process of identifying, analyzing, and evaluating risks. Steps: identify assets, identify threats and vulnerabilities, determine likelihood and impact, calculate risk, prioritize treatment. Qualitative (High/Medium/Low) vs Quantitative (dollar values). Risk = Threat x Vulnerability x Impact.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-5", "5.2", "risk"],
    },
    {
        "term": "Risk Treatment Options",
        "definition": "Four responses to identified risk: Accept (acknowledge and monitor), Mitigate (reduce likelihood/impact with controls), Transfer (shift to third party via insurance/contracts), Avoid (eliminate risk by stopping the activity). Choice depends on risk appetite and cost-benefit analysis.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-5", "5.2", "risk"],
    },
    {
        "term": "Quantitative Risk Analysis",
        "definition": "Assigning dollar values to risk. SLE (Single Loss Expectancy) = Asset Value x Exposure Factor. ARO (Annualized Rate of Occurrence) = expected frequency per year. ALE (Annualized Loss Expectancy) = SLE x ARO. Used to justify security spending.",
        "difficulty": "advanced",
        "tags": ["sy0-701", "domain-5", "5.2", "risk"],
    },
    {
        "term": "Risk Register",
        "definition": "Document listing all identified risks with their likelihood, impact, risk score, owner, treatment plan, and status. Central repository for risk tracking. Reviewed and updated regularly. Input to risk management decisions and audit.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-5", "5.2", "risk"],
    },
    {
        "term": "Risk Appetite vs Risk Tolerance",
        "definition": "Risk appetite: overall level of risk an organization is willing to accept to achieve objectives (strategic, set by board). Risk tolerance: acceptable variation from risk appetite for specific risks (tactical, set by management). Appetite is the target, tolerance is the acceptable range.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-5", "5.2", "risk"],
    },
    {
        "term": "Business Impact Analysis (BIA)",
        "definition": "Identifies critical business functions and the impact of disruption. Determines: RTO (Recovery Time Objective -- max acceptable downtime), RPO (Recovery Point Objective -- max acceptable data loss), MTTR/MTBF. Drives BC/DR planning priorities and resource allocation.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-5", "5.2", "business-continuity"],
    },
    {
        "term": "RTO vs RPO",
        "definition": "RTO (Recovery Time Objective): maximum acceptable time to restore service after disruption. RPO (Recovery Point Objective): maximum acceptable amount of data loss measured in time. RTO = how fast you recover. RPO = how much data you can afford to lose. Both drive backup/DR strategy.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-5", "5.2", "business-continuity"],
    },

    # 5.3 Third-party risk
    {
        "term": "Vendor Risk Assessment",
        "definition": "Evaluating security posture of third-party vendors before and during engagement. Methods: questionnaires, right-to-audit clauses, SOC 2 reports, penetration test results, compliance certifications. Ongoing monitoring required -- vendor risk changes over time.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-5", "5.3", "third-party"],
    },
    {
        "term": "SOC 2 Report",
        "definition": "Service Organization Control audit report evaluating controls related to Trust Services Criteria: Security, Availability, Processing Integrity, Confidentiality, Privacy. Type I: point-in-time design. Type II: effectiveness over period (6-12 months). Type II is more valuable. Standard vendor assurance tool.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-5", "5.3", "compliance", "third-party"],
    },
    {
        "term": "SLA (Service Level Agreement)",
        "definition": "Contract specifying minimum service levels: uptime percentage (99.9% = 8.76 hrs downtime/year), response times, support hours, penalties for non-compliance. Quantifiable metrics. Security SLAs should cover incident notification, patching timelines, encryption requirements.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-5", "5.3", "third-party"],
    },

    # 5.4 Compliance
    {
        "term": "GDPR (General Data Protection Regulation)",
        "definition": "EU regulation protecting personal data of EU residents. Key principles: lawful basis, data minimization, purpose limitation, right to erasure, breach notification (72 hours), DPO requirement, privacy by design. Fines up to 4% of global revenue or 20M euros.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-5", "5.4", "compliance", "privacy"],
    },
    {
        "term": "PCI DSS",
        "definition": "Payment Card Industry Data Security Standard. 12 requirements for handling cardholder data: firewalls, encryption, access control, monitoring, testing, policy. Levels based on transaction volume. Non-compliance = fines, loss of card processing ability. Requires network segmentation.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-5", "5.4", "compliance"],
    },
    {
        "term": "HIPAA",
        "definition": "Health Insurance Portability and Accountability Act. Protects PHI (Protected Health Information). Security Rule: technical, physical, administrative safeguards. Privacy Rule: patient rights over health data. Breach notification required. BAA (Business Associate Agreement) required for third parties.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-5", "5.4", "compliance", "healthcare"],
    },
    {
        "term": "Data Privacy Principles",
        "definition": "Core privacy concepts across regulations: purpose limitation (collect only for stated purpose), data minimization (collect only what's needed), consent (informed agreement), right to be forgotten (erasure), data portability, breach notification. Apply to GDPR, CCPA, HIPAA.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-5", "5.4", "privacy"],
    },

    # 5.5 Audits and assessments
    {
        "term": "Security Audit Types",
        "definition": "Internal audit: conducted by organization's own audit team. External audit: independent third party. Regulatory audit: required by law/regulation. Compliance audit: checks against specific standard (PCI, HIPAA). Each has different scope, objectivity, and reporting requirements.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-5", "5.5", "audit"],
    },

    # 5.6 Security awareness
    {
        "term": "Security Awareness Training",
        "definition": "Educating employees on security threats and proper behavior. Topics: phishing recognition, password hygiene, social engineering, data handling, incident reporting, physical security. Must be regular, role-based, and measurable. Simulated phishing tests measure effectiveness.",
        "difficulty": "beginner",
        "tags": ["sy0-701", "domain-5", "5.6", "awareness"],
    },
    {
        "term": "Insider Threat Indicators",
        "definition": "Signs of potential insider threats: unusual data access patterns, after-hours activity, large data downloads, disgruntlement, financial stress, foreign contacts, resignation followed by data collection. Technical controls: DLP, UEBA, access logging. Human controls: training, culture.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-5", "5.6", "threats"],
    },

    # Additional high-frequency exam concepts
    {
        "term": "Wireless Security Protocols",
        "definition": "WEP (broken, RC4), WPA (TKIP, deprecated), WPA2 (AES-CCMP, standard), WPA3 (SAE handshake, 192-bit, enhanced open). WPA3 replaces PSK with SAE (Simultaneous Authentication of Equals) -- resistant to offline dictionary attacks. Enterprise uses 802.1X/RADIUS.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-3", "3.3", "wireless"],
    },
    {
        "term": "Certificate Types",
        "definition": "DV (Domain Validation): proves domain ownership. OV (Organization Validation): verifies organization identity. EV (Extended Validation): thorough vetting, green bar. Wildcard: covers *.domain.com. SAN: covers multiple specific domains. Self-signed: not trusted by browsers.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-3", "3.3", "certificates"],
    },
    {
        "term": "Backup Types",
        "definition": "Full: complete copy of all data. Incremental: only data changed since last backup (any type). Differential: only data changed since last full backup. Full takes most time/space but simplest restore. Incremental fastest backup but longest restore chain. Differential is the middle ground.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-4", "4.3", "business-continuity"],
    },
    {
        "term": "Disaster Recovery Sites",
        "definition": "Hot site: fully equipped, data mirrored, ready in minutes/hours. Warm site: hardware ready but needs data restoration, ready in hours/days. Cold site: empty facility, needs everything, ready in days/weeks. Cost: hot > warm > cold. Choice driven by RTO requirements.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-5", "5.2", "business-continuity"],
    },
    {
        "term": "RAID Levels",
        "definition": "RAID 0: striping (performance, no redundancy). RAID 1: mirroring (full copy, 50% capacity loss). RAID 5: striping with parity (one drive failure tolerance, minimum 3 drives). RAID 6: double parity (two drive failures, minimum 4). RAID 10: mirrored stripes (performance + redundancy).",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-3", "3.4", "infrastructure"],
    },
    {
        "term": "DNS Attacks",
        "definition": "DNS poisoning: corrupting DNS cache with false records. DNS spoofing: impersonating DNS server. DNS amplification: DDoS using open DNS resolvers. DNS tunneling: exfiltrating data via DNS queries. Domain hijacking: taking over domain registration. Mitigations: DNSSEC, DoH, monitoring.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-2", "2.4", "network-attacks"],
    },
    {
        "term": "ARP Poisoning",
        "definition": "Sending falsified ARP messages to link attacker's MAC address with a legitimate IP address. Enables MITM attacks on local network. Attacker intercepts traffic between two hosts. Mitigations: static ARP entries, DAI (Dynamic ARP Inspection), network segmentation.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-2", "2.4", "network-attacks"],
    },
    {
        "term": "DDoS Attack Types",
        "definition": "Volumetric: overwhelm bandwidth (UDP flood, amplification). Protocol: exploit protocol weaknesses (SYN flood, Smurf). Application layer: target specific services (HTTP flood, Slowloris). Mitigation: CDN, rate limiting, blackholing, scrubbing centers, anycast distribution.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-2", "2.4", "network-attacks"],
    },
    {
        "term": "On-Path Attack (MITM)",
        "definition": "Attacker secretly relays and potentially alters communications between two parties who believe they are communicating directly. Methods: ARP spoofing, DNS spoofing, rogue WiFi, SSL stripping. Prevention: certificate pinning, HSTS, encrypted protocols, mutual authentication.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-2", "2.4", "network-attacks"],
    },
    {
        "term": "Credential Attacks",
        "definition": "Brute force: try every combination. Dictionary: try common passwords. Credential stuffing: use leaked credentials on other sites. Password spraying: try one password against many accounts. Rainbow table: precomputed hash lookup. Prevention: MFA, lockout, rate limiting, salted hashing.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-2", "2.4", "authentication-attacks"],
    },
    {
        "term": "Deauthentication Attack",
        "definition": "Sending forged deauthentication frames to disconnect wireless clients from an AP. Used to force reconnection for capturing WPA handshake (for offline cracking) or for denial of service. WPA3 protects management frames (802.11w) to prevent this.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-2", "2.4", "wireless-attacks"],
    },
    {
        "term": "Evil Twin Attack",
        "definition": "Setting up a rogue access point that mimics a legitimate one. Victims connect to the fake AP, allowing attacker to intercept traffic. Often paired with deauthentication to force reconnection. Mitigations: 802.1X, WIDS, VPN, user awareness, WPA3-Enterprise.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-2", "2.4", "wireless-attacks"],
    },
    {
        "term": "Secure Boot / TPM / HSM",
        "definition": "Secure Boot: UEFI feature ensuring only signed bootloaders execute, prevents bootkits. TPM (Trusted Platform Module): hardware chip for key storage, platform integrity, BitLocker. HSM (Hardware Security Module): dedicated crypto processor for key management, higher security than TPM.",
        "difficulty": "advanced",
        "tags": ["sy0-701", "domain-3", "3.2", "endpoint-security"],
    },
    {
        "term": "Site Survey and Heat Map",
        "definition": "Physical assessment of wireless coverage area. Maps signal strength, identifies dead zones, detects interference sources, determines optimal AP placement. Heat map visualizes coverage using color coding. Essential for secure wireless deployment -- prevents signal bleed outside intended area.",
        "difficulty": "beginner",
        "tags": ["sy0-701", "domain-3", "3.3", "wireless"],
    },
    {
        "term": "Data Sanitization Methods",
        "definition": "Clearing: overwriting with zeros (recoverable with forensics). Purging: overwriting multiple times or degaussing (not recoverable with normal tools). Destroying: physical destruction (shredding, incineration). Method depends on data sensitivity. Certificate of destruction for compliance.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-3", "3.4", "data-security"],
    },
    {
        "term": "Honeypot / Honeynet / Honeyfile",
        "definition": "Honeypot: decoy system designed to attract attackers and study their methods. Honeynet: network of honeypots simulating real infrastructure. Honeyfile: fake sensitive document that triggers alert when accessed. Deception technology -- detects attackers already inside the network.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-4", "4.1", "deception"],
    },
    {
        "term": "MITRE ATT&CK Framework",
        "definition": "Knowledge base of adversary tactics, techniques, and procedures (TTPs) based on real-world observations. 14 tactics (reconnaissance through impact). Used for threat modeling, detection engineering, red team planning, gap analysis. Industry standard for mapping attacker behavior.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-2", "2.1", "frameworks"],
    },
    {
        "term": "Cyber Kill Chain",
        "definition": "Lockheed Martin model of attack phases: 1) Reconnaissance, 2) Weaponization, 3) Delivery, 4) Exploitation, 5) Installation, 6) Command & Control, 7) Actions on Objectives. Breaking any link disrupts the attack. Used for defensive planning and incident analysis.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-2", "2.1", "frameworks"],
    },
    {
        "term": "Diamond Model of Intrusion Analysis",
        "definition": "Framework connecting four core features of an intrusion: Adversary, Infrastructure, Capability, and Victim. Every intrusion event has these four vertices. Used for threat intelligence analysis and attribution. Helps understand relationships between threat components.",
        "difficulty": "intermediate",
        "tags": ["sy0-701", "domain-2", "2.1", "frameworks"],
    },
]

# Load concepts into SynapseForge
loaded = 0
errors = 0
for c in CONCEPTS:
    try:
        concept = add_concept(
            term=c["term"],
            definition=c["definition"],
            category="security",
            difficulty=c["difficulty"],
            tags=c["tags"],
            source="CompTIA SY0-701",
            notes="",
        )
        loaded += 1
        print(f"  [{loaded:3d}] {concept.term}")
    except Exception as e:
        errors += 1
        print(f"  ERROR: {c['term']}: {e}")

print(f"\n=== SY0-701 LOCKDOWN LOADED ===")
print(f"Concepts loaded: {loaded}")
print(f"Errors: {errors}")
print(f"Domains covered: 1-5 (all)")
