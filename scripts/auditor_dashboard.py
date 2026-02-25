#!/usr/bin/env python3
"""Live dashboard for monitoring the adversarial security auditor.

Usage:
    python scripts/auditor_dashboard.py [--port PORT]

Opens http://localhost:8411 in the default browser. The page auto-refreshes
every 3 seconds by polling /api/status for live session data from Pulse.
"""

import json
import re
import sqlite3
import sys
import webbrowser
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from threading import Timer

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "jaybrain.db"
CODEBASE_DIR = PROJECT_ROOT / "src" / "jaybrain"
AUDITOR_CWD_PATTERN = "jaybrain-auditor"

# Count total .py files the auditor should read
TOTAL_PY_FILES = len(list(CODEBASE_DIR.glob("*.py")))


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.row_factory = sqlite3.Row
    return conn


def _get_auditor_data() -> dict:
    """Query Pulse tables for the auditor session data."""
    conn = _get_conn()
    try:
        # Find auditor sessions (most recent first)
        rows = conn.execute(
            """SELECT * FROM claude_sessions
               WHERE cwd LIKE ?
               ORDER BY started_at DESC""",
            (f"%{AUDITOR_CWD_PATTERN}%",),
        ).fetchall()

        if not rows:
            return {"found": False, "message": "No auditor session found"}

        session = dict(rows[0])
        session_id = session["session_id"]

        # Calculate duration
        started = datetime.fromisoformat(session["started_at"])
        heartbeat = datetime.fromisoformat(session["last_heartbeat"])
        now = datetime.now(timezone.utc)

        if session["status"] == "active":
            duration_sec = (now - started).total_seconds()
        else:
            duration_sec = (heartbeat - started).total_seconds()

        duration_min = duration_sec / 60

        # Get all activity for this session
        activities = conn.execute(
            """SELECT * FROM session_activity_log
               WHERE session_id = ?
               ORDER BY timestamp ASC""",
            (session_id,),
        ).fetchall()

        activities = [dict(a) for a in activities]

        # Tool usage breakdown
        tool_counts = {}
        for a in activities:
            if a["tool_name"] and a["event_type"] in ("tool_use", "tool_failure"):
                tool_counts[a["tool_name"]] = tool_counts.get(a["tool_name"], 0) + 1

        # Extract files read (from Read tool calls)
        files_read = []
        seen_files = set()
        for a in activities:
            if a["tool_name"] == "Read" and a["tool_input_summary"]:
                match = re.search(r"file_path=(.+?)(?:,|$)", a["tool_input_summary"])
                if match:
                    fpath = match.group(1).strip()
                    # Only count jaybrain source files
                    if "jaybrain" in fpath.lower() and fpath.endswith(".py"):
                        basename = Path(fpath).name
                        if basename not in seen_files:
                            seen_files.add(basename)
                            files_read.append({
                                "file": basename,
                                "path": fpath,
                                "timestamp": a["timestamp"],
                            })

        # Extract grep patterns
        grep_patterns = []
        for a in activities:
            if a["tool_name"] == "Grep" and a["tool_input_summary"]:
                match = re.search(r"pattern=(.+?)(?:,|$)", a["tool_input_summary"])
                if match:
                    grep_patterns.append({
                        "pattern": match.group(1).strip(),
                        "timestamp": a["timestamp"],
                    })

        # Recent activity (last 30, reversed for newest first)
        recent = []
        for a in reversed(activities[-30:]):
            recent.append({
                "event_type": a["event_type"],
                "tool_name": a["tool_name"] or "",
                "summary": a["tool_input_summary"] or "",
                "timestamp": a["timestamp"],
            })

        # Past auditor sessions (for history)
        past_sessions = []
        for r in rows[1:5]:
            r = dict(r)
            s = datetime.fromisoformat(r["started_at"])
            h = datetime.fromisoformat(r["last_heartbeat"])
            past_sessions.append({
                "session_id": r["session_id"][:8],
                "started_at": r["started_at"],
                "duration_min": round((h - s).total_seconds() / 60, 1),
                "tool_count": r["tool_count"],
                "status": r["status"],
            })

        return {
            "found": True,
            "session_id": session_id,
            "session_id_short": session_id[:8],
            "status": session["status"],
            "started_at": session["started_at"],
            "last_heartbeat": session["last_heartbeat"],
            "duration_min": round(duration_min, 1),
            "duration_sec": round(duration_sec),
            "tool_count": session["tool_count"],
            "last_tool": session["last_tool"] or "",
            "last_tool_input": session["last_tool_input"] or "",
            "tool_counts": tool_counts,
            "files_read": files_read,
            "files_read_count": len(files_read),
            "total_py_files": TOTAL_PY_FILES,
            "progress_pct": round(len(files_read) / TOTAL_PY_FILES * 100) if TOTAL_PY_FILES else 0,
            "grep_patterns": grep_patterns,
            "recent_activity": recent,
            "past_sessions": past_sessions,
        }
    finally:
        conn.close()


DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Auditor Dashboard</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: #0d1117; color: #c9d1d9; font-family: 'Segoe UI', system-ui, sans-serif;
    padding: 20px; min-height: 100vh;
  }
  h1 { color: #58a6ff; margin-bottom: 4px; font-size: 1.6em; }
  h2 { color: #8b949e; font-size: 1.1em; margin-bottom: 12px; font-weight: 400; }
  h3 { color: #58a6ff; font-size: 0.95em; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 1px; }

  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 16px; }
  .grid-full { grid-column: 1 / -1; }

  .card {
    background: #161b22; border: 1px solid #30363d; border-radius: 8px;
    padding: 16px; position: relative;
  }

  .status-bar {
    display: flex; align-items: center; gap: 16px; flex-wrap: wrap;
    background: #161b22; border: 1px solid #30363d; border-radius: 8px;
    padding: 16px 20px; margin-top: 12px;
  }
  .status-dot {
    width: 12px; height: 12px; border-radius: 50%; display: inline-block;
  }
  .status-dot.active { background: #3fb950; box-shadow: 0 0 8px #3fb95080; animation: pulse-dot 2s infinite; }
  .status-dot.ended { background: #8b949e; }
  .status-dot.not-found { background: #f85149; }

  @keyframes pulse-dot {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.5; }
  }

  .stat { text-align: center; }
  .stat-value { font-size: 1.8em; font-weight: 700; color: #f0f6fc; }
  .stat-label { font-size: 0.75em; color: #8b949e; text-transform: uppercase; letter-spacing: 1px; }

  .progress-bar-bg {
    background: #21262d; border-radius: 6px; height: 28px; overflow: hidden;
    position: relative; margin: 8px 0;
  }
  .progress-bar-fill {
    background: linear-gradient(90deg, #1f6feb, #58a6ff); height: 100%;
    border-radius: 6px; transition: width 0.5s ease;
    display: flex; align-items: center; justify-content: center;
    font-weight: 600; font-size: 0.85em; color: #fff;
    min-width: 40px;
  }

  .tool-bar-container { display: flex; flex-direction: column; gap: 6px; }
  .tool-bar-row { display: flex; align-items: center; gap: 8px; }
  .tool-bar-label { width: 60px; text-align: right; font-size: 0.85em; color: #8b949e; }
  .tool-bar-track { flex: 1; background: #21262d; border-radius: 4px; height: 22px; overflow: hidden; }
  .tool-bar {
    height: 100%; border-radius: 4px; transition: width 0.5s ease;
    display: flex; align-items: center; padding-left: 8px;
    font-size: 0.8em; font-weight: 600; color: #fff;
  }
  .tool-bar.Read { background: #1f6feb; }
  .tool-bar.Grep { background: #da3633; }
  .tool-bar.Glob { background: #3fb950; }
  .tool-bar.Bash { background: #d29922; }
  .tool-bar.other { background: #8b949e; }

  .file-list { max-height: 320px; overflow-y: auto; }
  .file-item {
    display: flex; justify-content: space-between; align-items: center;
    padding: 4px 8px; border-bottom: 1px solid #21262d;
    font-size: 0.85em;
  }
  .file-item:last-child { border-bottom: none; }
  .file-name { color: #58a6ff; font-family: 'Cascadia Code', 'Consolas', monospace; }
  .file-time { color: #8b949e; font-size: 0.8em; }

  .activity-feed { max-height: 400px; overflow-y: auto; }
  .activity-item {
    display: flex; gap: 8px; padding: 5px 8px;
    border-bottom: 1px solid #21262d; font-size: 0.82em;
    align-items: flex-start;
  }
  .activity-item:last-child { border-bottom: none; }
  .activity-time { color: #8b949e; white-space: nowrap; min-width: 65px; font-family: monospace; }
  .activity-tool {
    background: #21262d; border-radius: 4px; padding: 1px 6px;
    font-family: monospace; font-weight: 600; min-width: 50px; text-align: center;
  }
  .activity-tool.Read { color: #58a6ff; }
  .activity-tool.Grep { color: #f85149; }
  .activity-tool.Glob { color: #3fb950; }
  .activity-tool.Bash { color: #d29922; }
  .activity-summary { color: #c9d1d9; word-break: break-all; flex: 1; }
  .activity-item.session_end .activity-tool { color: #f85149; background: #f8514920; }
  .activity-item.session_start .activity-tool { color: #3fb950; background: #3fb95020; }

  .grep-list { max-height: 200px; overflow-y: auto; }
  .grep-item {
    padding: 3px 8px; font-family: monospace; font-size: 0.82em;
    color: #f85149; border-bottom: 1px solid #21262d;
  }

  .not-found {
    text-align: center; padding: 60px 20px; color: #8b949e;
  }
  .not-found h2 { font-size: 1.3em; color: #c9d1d9; margin-bottom: 8px; }

  .refresh-indicator {
    position: fixed; top: 12px; right: 16px;
    font-size: 0.75em; color: #484f58;
  }

  .past-sessions { margin-top: 8px; }
  .past-session {
    display: flex; gap: 12px; font-size: 0.82em; padding: 3px 0;
    color: #8b949e;
  }

  ::-webkit-scrollbar { width: 6px; }
  ::-webkit-scrollbar-track { background: #161b22; }
  ::-webkit-scrollbar-thumb { background: #30363d; border-radius: 3px; }
</style>
</head>
<body>

<h1>Adversarial Security Auditor</h1>
<h2>Live Dashboard</h2>

<div id="dashboard">
  <div class="not-found"><h2>Connecting...</h2></div>
</div>

<div class="refresh-indicator" id="refresh-ind">Updated just now</div>

<script>
function fmtTime(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit', second:'2-digit'});
}

function fmtDuration(sec) {
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  if (m >= 60) {
    const h = Math.floor(m / 60);
    const rm = m % 60;
    return h + 'h ' + rm + 'm';
  }
  return m + 'm ' + s + 's';
}

function render(data) {
  const el = document.getElementById('dashboard');

  if (!data.found) {
    el.innerHTML = `
      <div class="not-found">
        <h2>No Auditor Session Found</h2>
        <p>Run <code>python scripts/run_auditor.py</code> to start an audit.</p>
        <p style="margin-top:8px;font-size:0.9em">Dashboard will auto-detect when a session starts.</p>
      </div>`;
    return;
  }

  const isActive = data.status === 'active';
  const dotClass = isActive ? 'active' : 'ended';
  const statusText = isActive ? 'RUNNING' : 'COMPLETED';
  const statusColor = isActive ? '#3fb950' : '#8b949e';

  // Tool usage bars
  const maxTool = Math.max(...Object.values(data.tool_counts || {}), 1);
  const toolOrder = ['Read', 'Grep', 'Glob', 'Bash'];
  const allTools = Object.keys(data.tool_counts || {});
  const orderedTools = toolOrder.filter(t => allTools.includes(t));
  allTools.forEach(t => { if (!orderedTools.includes(t)) orderedTools.push(t); });

  const toolBars = orderedTools.map(t => {
    const count = data.tool_counts[t];
    const pct = (count / maxTool * 100).toFixed(0);
    const cls = toolOrder.includes(t) ? t : 'other';
    return `<div class="tool-bar-row">
      <span class="tool-bar-label">${t}</span>
      <div class="tool-bar-track">
        <div class="tool-bar ${cls}" style="width:${pct}%">${count}</div>
      </div>
    </div>`;
  }).join('');

  // Files read list
  const fileItems = (data.files_read || []).map(f =>
    `<div class="file-item">
      <span class="file-name">${f.file}</span>
      <span class="file-time">${fmtTime(f.timestamp)}</span>
    </div>`
  ).join('');

  // Activity feed
  const activityItems = (data.recent_activity || []).map(a => {
    const cls = a.tool_name ? a.tool_name : a.event_type;
    const toolLabel = a.tool_name || a.event_type.replace('_', ' ');
    const summary = a.summary || '';
    return `<div class="activity-item ${a.event_type}">
      <span class="activity-time">${fmtTime(a.timestamp)}</span>
      <span class="activity-tool ${cls}">${toolLabel}</span>
      <span class="activity-summary">${summary}</span>
    </div>`;
  }).join('');

  // Grep patterns
  const grepItems = (data.grep_patterns || []).map(g =>
    `<div class="grep-item">${g.pattern}</div>`
  ).join('');

  // Past sessions
  const pastItems = (data.past_sessions || []).map(s =>
    `<div class="past-session">
      <span>${s.session_id}</span>
      <span>${fmtTime(s.started_at)}</span>
      <span>${s.duration_min}m</span>
      <span>${s.tool_count} tools</span>
      <span>${s.status}</span>
    </div>`
  ).join('');

  el.innerHTML = `
    <div class="status-bar">
      <div>
        <span class="status-dot ${dotClass}"></span>
        <strong style="color:${statusColor};margin-left:6px">${statusText}</strong>
      </div>
      <div class="stat">
        <div class="stat-value">${fmtDuration(data.duration_sec)}</div>
        <div class="stat-label">Duration</div>
      </div>
      <div class="stat">
        <div class="stat-value">${data.tool_count}</div>
        <div class="stat-label">Tool Calls</div>
      </div>
      <div class="stat">
        <div class="stat-value">${data.files_read_count} / ${data.total_py_files}</div>
        <div class="stat-label">Files Read</div>
      </div>
      <div class="stat">
        <div class="stat-value">${data.progress_pct}%</div>
        <div class="stat-label">Coverage</div>
      </div>
      <div style="margin-left:auto;color:#484f58;font-size:0.8em">
        Session ${data.session_id_short}
      </div>
    </div>

    <div class="grid">
      <div class="card">
        <h3>File Progress</h3>
        <div class="progress-bar-bg">
          <div class="progress-bar-fill" style="width:${data.progress_pct}%">
            ${data.files_read_count} / ${data.total_py_files}
          </div>
        </div>
        <div class="file-list">${fileItems || '<div style="color:#484f58;padding:12px;text-align:center">No files read yet</div>'}</div>
      </div>

      <div class="card">
        <h3>Tool Usage</h3>
        <div class="tool-bar-container">${toolBars || '<div style="color:#484f58;text-align:center">No tool calls yet</div>'}</div>

        ${grepItems ? `<h3 style="margin-top:16px">Security Patterns Searched</h3><div class="grep-list">${grepItems}</div>` : ''}
      </div>

      <div class="card grid-full">
        <h3>Activity Feed ${isActive ? '<span style="color:#3fb950;font-size:0.8em;margin-left:8px">LIVE</span>' : ''}</h3>
        <div class="activity-feed">${activityItems || '<div style="color:#484f58;text-align:center;padding:12px">No activity yet</div>'}</div>
      </div>

      ${pastItems ? `<div class="card grid-full"><h3>Previous Audit Sessions</h3><div class="past-sessions">${pastItems}</div></div>` : ''}
    </div>
  `;
}

let lastUpdate = Date.now();
async function poll() {
  try {
    const res = await fetch('/api/status');
    const data = await res.json();
    render(data);
    lastUpdate = Date.now();
    document.getElementById('refresh-ind').textContent = 'Updated just now';
  } catch (e) {
    document.getElementById('refresh-ind').textContent = 'Connection lost';
  }
}

// Update "Updated X seconds ago" text
setInterval(() => {
  const ago = Math.round((Date.now() - lastUpdate) / 1000);
  if (ago > 2) {
    document.getElementById('refresh-ind').textContent = 'Updated ' + ago + 's ago';
  }
}, 1000);

poll();
setInterval(poll, 3000);
</script>
</body>
</html>"""


class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/status":
            data = _get_auditor_data()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())
        elif self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(DASHBOARD_HTML.encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Suppress request logs to keep terminal clean
        pass


def main():
    port = 8411
    if "--port" in sys.argv:
        idx = sys.argv.index("--port")
        port = int(sys.argv[idx + 1])

    server = HTTPServer(("127.0.0.1", port), DashboardHandler)
    url = f"http://localhost:{port}"

    print(f"Auditor Dashboard running at {url}")
    print("Press Ctrl+C to stop")
    print()

    # Open browser after a brief delay
    Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
        server.server_close()


if __name__ == "__main__":
    main()
