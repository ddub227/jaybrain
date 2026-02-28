"""GramCracker -- Telegram bot with Claude AI and JayBrain context.

Gives JJ a persistent Telegram interface to JayBrain's memory, tasks,
and Pulse session awareness. Runs as a standalone process alongside
Claude Code sessions.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Optional

import requests

from .config import (
    ANTHROPIC_API_KEY,
    GRAMCRACKER_CLAUDE_MODEL,
    TELEGRAM_API_BASE,
    TELEGRAM_AUTHORIZED_USER,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_HISTORY_LIMIT,
    TELEGRAM_MAX_MESSAGE_LEN,
    TELEGRAM_MAX_RESPONSE_TOKENS,
    TELEGRAM_POLL_TIMEOUT,
    TELEGRAM_RATE_LIMIT_MAX,
    TELEGRAM_RATE_LIMIT_WINDOW,
)
from .db import (
    get_connection,
    get_telegram_bot_state,
    get_telegram_history,
    get_telegram_message_count,
    clear_telegram_history,
    init_db,
    insert_telegram_message,
    now_iso,
    upsert_telegram_bot_state,
)

logger = logging.getLogger("gramcracker")


# ---------------------------------------------------------------------------
# Telegram API wrapper (raw HTTP, no SDK)
# ---------------------------------------------------------------------------

class TelegramAPI:
    """Thin wrapper around the Telegram Bot HTTP API."""

    def __init__(self, token: str) -> None:
        self._base = f"{TELEGRAM_API_BASE}{token}"
        self._session = requests.Session()

    def _call(self, method: str, retries: int = 3, **kwargs) -> dict:
        """POST to a Telegram API method with automatic retry on transient errors."""
        last_err = None
        for attempt in range(retries):
            try:
                resp = self._session.post(
                    f"{self._base}/{method}",
                    json=kwargs,
                    timeout=TELEGRAM_POLL_TIMEOUT + 10,
                )
                resp.raise_for_status()
                data = resp.json()
                if not data.get("ok"):
                    raise RuntimeError(f"Telegram API error: {data.get('description', data)}")
                return data.get("result", {})
            except (requests.ConnectionError, requests.Timeout) as e:
                last_err = e
                if attempt < retries - 1:
                    wait = 2 ** attempt
                    logger.debug("Telegram API %s retry %d after %ss: %s", method, attempt + 1, wait, e)
                    time.sleep(wait)
                    # Reset the session to get a fresh connection
                    self._session.close()
                    self._session = requests.Session()
        raise last_err

    def get_updates(self, offset: int = 0, timeout: int = TELEGRAM_POLL_TIMEOUT) -> list[dict]:
        """Long-poll for new messages."""
        return self._call(
            "getUpdates",
            offset=offset,
            timeout=timeout,
            allowed_updates=["message"],
        )

    def send_message(self, chat_id: int, text: str) -> dict:
        """Send a text message. Telegram caps at 4096 chars per message."""
        return self._call(
            "sendMessage",
            chat_id=chat_id,
            text=text,
            parse_mode="Markdown",
        )

    def send_message_plain(self, chat_id: int, text: str) -> dict:
        """Send a text message without parse_mode (fallback for Markdown errors)."""
        return self._call(
            "sendMessage",
            chat_id=chat_id,
            text=text,
        )

    def send_chat_action(self, chat_id: int, action: str = "typing") -> dict:
        """Show typing indicator."""
        return self._call("sendChatAction", chat_id=chat_id, action=action)

    def get_me(self) -> dict:
        """Get bot info (useful for verification)."""
        return self._call("getMe")


# ---------------------------------------------------------------------------
# Rate limiter (sliding window)
# ---------------------------------------------------------------------------

class RateLimiter:
    """Sliding-window rate limiter for outbound messages."""

    def __init__(
        self,
        max_calls: int = TELEGRAM_RATE_LIMIT_MAX,
        window_seconds: int = TELEGRAM_RATE_LIMIT_WINDOW,
    ) -> None:
        self._max = max_calls
        self._window = window_seconds
        self._timestamps: list[float] = []
        self._lock = threading.Lock()

    def _prune(self) -> None:
        cutoff = time.time() - self._window
        self._timestamps = [t for t in self._timestamps if t > cutoff]

    def allow(self) -> bool:
        with self._lock:
            self._prune()
            return len(self._timestamps) < self._max

    def record(self) -> None:
        with self._lock:
            self._timestamps.append(time.time())

    def wait_if_needed(self) -> None:
        """Block until a slot opens."""
        while not self.allow():
            time.sleep(0.5)
        self.record()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars per token)."""
    return max(1, len(text) // 4)


def _split_message(text: str, max_len: int = TELEGRAM_MAX_MESSAGE_LEN) -> list[str]:
    """Split a long message into Telegram-safe chunks.

    Prefers splitting at paragraph > newline > sentence > hard break.
    """
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break

        # Try paragraph break
        cut = text.rfind("\n\n", 0, max_len)
        if cut > max_len // 4:
            chunks.append(text[:cut])
            text = text[cut + 2:]
            continue

        # Try newline
        cut = text.rfind("\n", 0, max_len)
        if cut > max_len // 4:
            chunks.append(text[:cut])
            text = text[cut + 1:]
            continue

        # Try sentence end
        for sep in (". ", "! ", "? "):
            cut = text.rfind(sep, 0, max_len)
            if cut > max_len // 4:
                chunks.append(text[: cut + 1])
                text = text[cut + 2:]
                break
        else:
            # Hard break at max_len
            chunks.append(text[:max_len])
            text = text[max_len:]

    return chunks


def _build_system_prompt() -> str:
    """Build the Claude system prompt with live JayBrain context."""
    parts = [
        "You are GramCracker, JJ's personal AI assistant on Telegram, "
        "powered by JayBrain's memory system. You have access to JJ's "
        "profile, tasks, memories, active Claude Code sessions, and "
        "SynapseForge learning tools.",
        "",
        "Be concise -- Telegram messages should be short and scannable. "
        "Use markdown sparingly (bold, code). No emojis unless JJ uses them first.",
        "",
        "## SynapseForge Quiz Mode",
        "NEVER guess or fabricate subject IDs or concept IDs. ONLY use IDs returned by tool calls.",
        "NEVER invent questions from your training data -- only quiz on concepts returned by forge_study().",
        "When recording reviews with forge_review(), use the EXACT concept_id from forge_study() results.",
        "",
        "Quiz rules:",
        "- 1 question per message, multiple choice A-D, always include E. I don't know and F. Question previous question",
        "- NEVER show the term name, objective number, or category before the question",
        "- All answer options must be UNIFORM in style (all named terms OR all descriptions, never mix)",
        "- All distractors must be plausible and from the same domain -- no obviously irrelevant options",
        "- JJ answers with [letter][confidence 1-5] (e.g. B4). If confidence is missing, ask for it before proceeding",
        "",
        "CRITICAL -- When JJ answers a question, you MUST do these steps IN ORDER:",
        "Step 1: IMMEDIATELY call forge_review() with the concept_id, outcome, confidence, was_correct, and bloom_level. This is NON-NEGOTIABLE. Do this BEFORE writing any text response.",
        "Step 2: Call forge_study() to get the next concept from the queue.",
        "Step 3: ONLY AFTER both tool calls, write your response with this EXACT structure:",
        "  a. Correct/Wrong verdict (one line)",
        "  b. WHY the correct answer is right (2-3 sentences with analogy or memorable explanation)",
        "  c. WHY EACH wrong option (A-D) is wrong (1 sentence each, name what it actually describes)",
        "  d. The next question (built from the concept returned by forge_study in Step 2)",
        "NEVER skip the explanation sections. NEVER skip forge_review(). If you respond without calling forge_review(), the answer is LOST.",
        "",
        "- Randomize correct answer position across A-D, never same letter 3x in a row",
        "- Number every question (Q1, Q2, Q3...)",
        "- Silent tracking -- never mention scoring changes or internal mechanics",
        "- F = pin current question, handle side conversation, resume pinned question",
        "- Mastery levels: Spark (0-20%) > Ember (20-40%) > Flame (40-60%) > Blaze (60-80%) > Inferno (80-100%) > Forged (95%+)",
        "",
    ]

    conn = get_connection()
    try:
        # Profile
        try:
            from .profile import get_profile
            profile = get_profile()
            parts.append(f"## JJ's Profile\n{_format_dict(profile)}")
        except Exception:
            pass

        # Active tasks
        try:
            from .tasks import get_tasks
            active = get_tasks(status="todo") + get_tasks(status="in_progress")
            if active:
                task_lines = []
                for t in active[:10]:
                    task_lines.append(f"- [{t.status.value}] {t.title} (p:{t.priority.value})")
                parts.append("## Active Tasks\n" + "\n".join(task_lines))
        except Exception:
            pass

        # Recent decisions
        try:
            from .memory import recall as _recall
            decisions = _recall("decisions", category="decision", limit=5)
            if decisions:
                dec_lines = [f"- {r.memory.content[:120]}" for r in decisions]
                parts.append("## Recent Decisions\n" + "\n".join(dec_lines))
        except Exception:
            pass

        # SynapseForge subjects (so bot doesn't have to guess IDs)
        try:
            from .forge import get_subjects
            subjects = get_subjects()
            if subjects:
                subj_lines = []
                for s in subjects:
                    subj_lines.append(
                        f"- {s['name']} (id: {s['id']}, concepts: {s.get('concept_count', '?')})"
                    )
                parts.append(
                    "## SynapseForge Subjects (use these EXACT IDs)\n" + "\n".join(subj_lines)
                )
        except Exception:
            pass

        # Active Claude Code sessions (Pulse)
        try:
            from .pulse import get_active_sessions
            sessions = get_active_sessions(stale_minutes=120)
            active_sessions = sessions.get("sessions", [])
            if active_sessions:
                sess_lines = []
                for s in active_sessions[:5]:
                    sess_lines.append(
                        f"- {s.get('session_id', '?')[:8]}... "
                        f"in {s.get('cwd', '?')} "
                        f"(last: {s.get('last_tool', '?')}, "
                        f"{s.get('minutes_ago', '?')}m ago)"
                    )
                parts.append("## Active Claude Code Sessions\n" + "\n".join(sess_lines))
        except Exception:
            pass
    finally:
        conn.close()

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    parts.append(f"\nCurrent time: {now}")

    return "\n\n".join(parts)


def _format_dict(d: dict, indent: int = 0) -> str:
    """Simple dict-to-text formatter for system prompt."""
    lines = []
    prefix = "  " * indent
    for k, v in d.items():
        if isinstance(v, dict):
            lines.append(f"{prefix}{k}:")
            lines.append(_format_dict(v, indent + 1))
        elif isinstance(v, list):
            lines.append(f"{prefix}{k}: {', '.join(str(i) for i in v[:10])}")
        else:
            lines.append(f"{prefix}{k}: {v}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# GramCracker bot
# ---------------------------------------------------------------------------

class GramCracker:
    """Main Telegram bot: polls for messages, responds via Claude API."""

    def __init__(self) -> None:
        if not TELEGRAM_BOT_TOKEN:
            raise RuntimeError("TELEGRAM_BOT_TOKEN not set")
        if not ANTHROPIC_API_KEY:
            raise RuntimeError("ANTHROPIC_API_KEY not set")

        self.api = TelegramAPI(TELEGRAM_BOT_TOKEN)
        self.rate_limiter = RateLimiter()
        self._running = False
        self._chat_id: Optional[int] = None

        # Load Anthropic client
        import anthropic
        self.claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        # Load poll offset from DB
        conn = get_connection()
        try:
            state = get_telegram_bot_state(conn)
            self._offset = state["poll_offset"] if state else 0
        finally:
            conn.close()

        # Verify bot token
        me = self.api.get_me()
        logger.info("Bot authenticated as @%s (id=%s)", me.get("username"), me.get("id"))

    def run(self) -> None:
        """Main polling loop with signal handling."""
        self._running = True
        pid = os.getpid()

        # Register signal handlers for graceful shutdown
        def _shutdown(signum, frame):
            logger.info("Received signal %s, shutting down...", signum)
            self._running = False

        signal.signal(signal.SIGINT, _shutdown)
        signal.signal(signal.SIGTERM, _shutdown)

        # Record startup in DB
        conn = get_connection()
        try:
            upsert_telegram_bot_state(
                conn,
                pid=pid,
                started_at=now_iso(),
                last_heartbeat=now_iso(),
                last_error="",
            )
        finally:
            conn.close()

        logger.info("GramCracker polling loop started (pid=%d)", pid)

        # Send startup message
        try:
            self._send_startup_message()
        except Exception as e:
            logger.warning("Failed to send startup message: %s", e)

        while self._running:
            try:
                self._poll_once()
                # Heartbeat
                conn = get_connection()
                try:
                    upsert_telegram_bot_state(conn, last_heartbeat=now_iso())
                finally:
                    conn.close()
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error("Poll error: %s", e, exc_info=True)
                conn = get_connection()
                try:
                    upsert_telegram_bot_state(conn, last_error=str(e)[:500])
                finally:
                    conn.close()
                time.sleep(5)  # back off on errors

        # Clean shutdown
        conn = get_connection()
        try:
            upsert_telegram_bot_state(conn, pid=0, last_error="")
        finally:
            conn.close()
        logger.info("GramCracker shut down cleanly")

    def _send_startup_message(self) -> None:
        """Send a brief online notification to JJ."""
        chat_id = TELEGRAM_AUTHORIZED_USER
        self.api.send_message_plain(
            chat_id,
            "GramCracker online. Send /help for commands.",
        )

    def _poll_once(self) -> None:
        """Execute one long-poll cycle."""
        updates = self.api.get_updates(offset=self._offset, timeout=TELEGRAM_POLL_TIMEOUT)
        for update in updates:
            update_id = update.get("update_id", 0)
            self._offset = update_id + 1
            self._persist_offset()

            msg = update.get("message")
            if not msg:
                continue

            self._handle_message(msg)

    def _handle_message(self, msg: dict) -> None:
        """Process a single incoming Telegram message."""
        user = msg.get("from", {})
        user_id = user.get("id", 0)
        chat_id = msg.get("chat", {}).get("id", 0)
        text = msg.get("text", "").strip()

        if not text:
            return

        # Auth check
        if user_id != TELEGRAM_AUTHORIZED_USER:
            logger.warning("Unauthorized user %s attempted access", user_id)
            self.api.send_message_plain(chat_id, "Unauthorized.")
            return

        self._chat_id = chat_id
        telegram_msg_id = msg.get("message_id")

        # Store incoming message
        conn = get_connection()
        try:
            insert_telegram_message(
                conn, "user", text,
                token_count=_estimate_tokens(text),
                telegram_message_id=telegram_msg_id,
            )
            upsert_telegram_bot_state(
                conn,
                messages_in=get_telegram_message_count(conn, role="user"),
            )
        finally:
            conn.close()

        # Check for bot commands
        if text.startswith("/"):
            response = self._handle_command(text)
        else:
            # Show typing indicator
            try:
                self.api.send_chat_action(chat_id)
            except Exception:
                pass
            response = self._get_claude_response(text)

        # Send response
        self._send(response)

    def _handle_command(self, text: str) -> str:
        """Process bot commands. Returns response text."""
        cmd = text.split()[0].lower().rstrip("@gramcracker_bot")

        if cmd == "/help":
            return (
                "*GramCracker Commands*\n\n"
                "/status -- Bot uptime, message counts, model\n"
                "/sessions -- Active Claude Code sessions\n"
                "/tasks -- Active JayBrain tasks\n"
                "/clear -- Reset conversation history\n"
                "/help -- This message"
            )

        if cmd == "/status":
            return self._cmd_status()

        if cmd == "/sessions":
            return self._cmd_sessions()

        if cmd == "/tasks":
            return self._cmd_tasks()

        if cmd == "/clear":
            return self._cmd_clear()

        return f"Unknown command: {cmd}\nSend /help for available commands."

    def _cmd_status(self) -> str:
        conn = get_connection()
        try:
            state = get_telegram_bot_state(conn)
            if not state:
                return "No bot state found."

            started = state["started_at"] or "unknown"
            uptime = ""
            if state["started_at"]:
                try:
                    start_dt = datetime.fromisoformat(state["started_at"])
                    delta = datetime.now(timezone.utc) - start_dt
                    hours = int(delta.total_seconds() // 3600)
                    mins = int((delta.total_seconds() % 3600) // 60)
                    uptime = f"{hours}h {mins}m"
                except (ValueError, TypeError):
                    uptime = "?"

            return (
                f"*GramCracker Status*\n\n"
                f"Uptime: {uptime}\n"
                f"Messages in: {state['messages_in']}\n"
                f"Messages out: {state['messages_out']}\n"
                f"Model: {GRAMCRACKER_CLAUDE_MODEL}\n"
                f"Started: {started[:19]}"
            )
        finally:
            conn.close()

    def _cmd_sessions(self) -> str:
        try:
            from .pulse import get_active_sessions
            result = get_active_sessions(stale_minutes=120)
            sessions = result.get("sessions", [])
            if not sessions:
                return "No active Claude Code sessions."

            lines = ["*Active Claude Code Sessions*\n"]
            for s in sessions[:8]:
                sid = s.get("session_id", "?")[:8]
                cwd = s.get("cwd", "?")
                tool = s.get("last_tool", "?")
                mins = s.get("minutes_ago", "?")
                lines.append(f"- `{sid}` in {cwd}\n  last: {tool} ({mins}m ago)")
            return "\n".join(lines)
        except Exception as e:
            return f"Error fetching sessions: {e}"

    def _cmd_tasks(self) -> str:
        try:
            from .tasks import get_tasks
            active = get_tasks(status="todo") + get_tasks(status="in_progress")
            if not active:
                return "No active tasks."

            lines = ["*Active Tasks*\n"]
            for t in active[:15]:
                status = "WIP" if t.status.value == "in_progress" else "TODO"
                lines.append(f"- [{status}] {t.title}")
            return "\n".join(lines)
        except Exception as e:
            return f"Error fetching tasks: {e}"

    def _cmd_clear(self) -> str:
        conn = get_connection()
        try:
            count = clear_telegram_history(conn)
            return f"Cleared {count} messages from conversation history."
        finally:
            conn.close()

    def _get_claude_response(self, text: str) -> str:
        """Build conversation context, call Claude API with tool use, execute tools."""
        system_prompt = _build_system_prompt()

        # Load conversation history
        conn = get_connection()
        try:
            history_rows = get_telegram_history(conn, limit=TELEGRAM_HISTORY_LIMIT)
        finally:
            conn.close()

        # Build messages array
        messages = []
        for row in history_rows:
            role = row["role"]
            if role in ("user", "assistant"):
                messages.append({"role": role, "content": row["content"]})

        # Ensure the conversation ends with the current user message
        if not messages or messages[-1].get("content") != text:
            messages.append({"role": "user", "content": text})

        # Ensure messages alternate properly (Claude API requirement)
        messages = _fix_message_alternation(messages)

        try:
            reply = self._run_tool_loop(system_prompt, messages)
        except Exception as e:
            logger.error("Claude API error: %s", e)
            reply = f"Claude API error: {e}"

        # Store the assistant response
        conn = get_connection()
        try:
            insert_telegram_message(
                conn, "assistant", reply,
                token_count=_estimate_tokens(reply),
            )
            upsert_telegram_bot_state(
                conn,
                messages_out=get_telegram_message_count(conn, role="assistant"),
            )
        finally:
            conn.close()

        return reply

    def _run_tool_loop(self, system_prompt: str, messages: list[dict], max_rounds: int = 5) -> str:
        """Call Claude with tools, execute any tool calls, loop until text response."""
        tools = _get_tool_definitions()

        for _ in range(max_rounds):
            # Show typing indicator each round
            if self._chat_id:
                try:
                    self.api.send_chat_action(self._chat_id)
                except Exception:
                    pass

            response = self.claude.messages.create(
                model=GRAMCRACKER_CLAUDE_MODEL,
                max_tokens=TELEGRAM_MAX_RESPONSE_TOKENS,
                system=system_prompt,
                messages=messages,
                tools=tools,
            )

            # Check if response contains tool use
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            text_blocks = [b for b in response.content if b.type == "text"]

            if not tool_uses:
                # Pure text response -- we're done
                return text_blocks[0].text if text_blocks else ""

            # Execute tool calls and build tool results
            # First, add the assistant response to messages
            messages.append({"role": "assistant", "content": response.content})

            tool_results = []
            for tool_use in tool_uses:
                result = _execute_tool(tool_use.name, tool_use.input)
                logger.info("Tool %s(%s) -> %s", tool_use.name, tool_use.input, result[:200])
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": result,
                })

            messages.append({"role": "user", "content": tool_results})

        # If we hit max rounds, extract whatever text we got
        return text_blocks[0].text if text_blocks else "I ran out of tool-use rounds. Try a simpler request."

    def _send(self, text: str) -> None:
        """Split, rate-limit, and send a message to the current chat."""
        if not self._chat_id:
            logger.warning("No chat_id set, cannot send")
            return

        chunks = _split_message(text)
        for chunk in chunks:
            self.rate_limiter.wait_if_needed()
            try:
                self.api.send_message(self._chat_id, chunk)
            except Exception:
                # Markdown parse error fallback
                try:
                    self.api.send_message_plain(self._chat_id, chunk)
                except Exception as e:
                    logger.error("Failed to send message: %s", e)

    def _persist_offset(self) -> None:
        """Save the current poll offset to DB."""
        conn = get_connection()
        try:
            upsert_telegram_bot_state(conn, poll_offset=self._offset)
        finally:
            conn.close()


def _fix_message_alternation(messages: list[dict]) -> list[dict]:
    """Ensure messages strictly alternate user/assistant.

    Claude API requires strict alternation. If we have consecutive
    messages of the same role, merge them. Only merges plain string content;
    tool-use messages (with list content) are left intact.
    """
    if not messages:
        return messages

    fixed: list[dict] = [messages[0]]
    for msg in messages[1:]:
        prev = fixed[-1]
        if msg["role"] == prev["role"] and isinstance(msg["content"], str) and isinstance(prev["content"], str):
            prev["content"] += "\n\n" + msg["content"]
        else:
            fixed.append(msg)

    # Ensure first message is from user
    if fixed and fixed[0]["role"] != "user":
        fixed = fixed[1:]

    return fixed


# ---------------------------------------------------------------------------
# Tool definitions for Claude tool use (JayBrain write access)
# ---------------------------------------------------------------------------

def _get_tool_definitions() -> list[dict]:
    """Return tool schemas for the Claude API tool-use parameter."""
    return [
        {
            "name": "remember",
            "description": "Store a memory in JayBrain. Categories: episodic, semantic, procedural, decision, preference. Importance: 0.0-1.0.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "The memory content"},
                    "category": {"type": "string", "enum": ["episodic", "semantic", "procedural", "decision", "preference"], "default": "semantic"},
                    "tags": {"type": "array", "items": {"type": "string"}, "default": []},
                    "importance": {"type": "number", "default": 0.5},
                },
                "required": ["content"],
            },
        },
        {
            "name": "recall",
            "description": "Search JayBrain memories using hybrid vector + keyword search.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "category": {"type": "string", "description": "Filter by category"},
                    "limit": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
        },
        {
            "name": "task_create",
            "description": "Create a new JayBrain task. Priority: low, medium, high, critical.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string", "default": ""},
                    "priority": {"type": "string", "enum": ["low", "medium", "high", "critical"], "default": "medium"},
                    "project": {"type": "string", "default": ""},
                    "tags": {"type": "array", "items": {"type": "string"}, "default": []},
                },
                "required": ["title"],
            },
        },
        {
            "name": "task_update",
            "description": "Update a task's status or fields. Status: todo, in_progress, blocked, done, cancelled.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "status": {"type": "string", "enum": ["todo", "in_progress", "blocked", "done", "cancelled"]},
                    "title": {"type": "string"},
                    "priority": {"type": "string"},
                },
                "required": ["task_id"],
            },
        },
        {
            "name": "task_list",
            "description": "List JayBrain tasks. Filter by status, project, or priority.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "description": "Filter: todo, in_progress, blocked, done, cancelled"},
                    "project": {"type": "string"},
                    "limit": {"type": "integer", "default": 20},
                },
            },
        },
        {
            "name": "knowledge_search",
            "description": "Search the JayBrain knowledge base.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
        },
        {
            "name": "pulse_active",
            "description": "List active Claude Code sessions with their last tool, CWD, and idle time.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "stale_minutes": {"type": "integer", "default": 120},
                },
            },
        },
        {
            "name": "profile_get",
            "description": "Read JJ's full user profile (name, preferences, projects, tools, notes).",
            "input_schema": {
                "type": "object",
                "properties": {},
            },
        },
        {
            "name": "forge_study",
            "description": "Get a prioritized study queue. Without subject_id: due > new > struggling. With subject_id: interleaved queue weighted by exam_weight * (1 - mastery).",
            "input_schema": {
                "type": "object",
                "properties": {
                    "subject_id": {"type": "string", "description": "Exam subject ID for weighted queue"},
                    "category": {"type": "string", "description": "Filter by category"},
                    "limit": {"type": "integer", "default": 10},
                },
            },
        },
        {
            "name": "forge_review",
            "description": "Record a review outcome. Outcome: understood, reviewed, struggled, skipped. Confidence: 1-5. Pass was_correct for confidence-weighted scoring.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "concept_id": {"type": "string"},
                    "outcome": {"type": "string", "enum": ["understood", "reviewed", "struggled", "skipped"]},
                    "confidence": {"type": "integer", "default": 3},
                    "was_correct": {"type": "boolean", "description": "True/false for v2 scoring"},
                    "error_type": {"type": "string", "default": ""},
                    "bloom_level": {"type": "string", "enum": ["remember", "understand", "apply", "analyze"], "default": ""},
                    "notes": {"type": "string", "default": ""},
                },
                "required": ["concept_id", "outcome"],
            },
        },
        {
            "name": "forge_explain",
            "description": "Get full concept details with review history.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "concept_id": {"type": "string"},
                },
                "required": ["concept_id"],
            },
        },
        {
            "name": "forge_readiness",
            "description": "Get exam readiness score with domain breakdown, coverage, calibration, and recommendations.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "subject_id": {"type": "string"},
                },
                "required": ["subject_id"],
            },
        },
        {
            "name": "forge_search",
            "description": "Search forge concepts using hybrid vector + keyword search.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "category": {"type": "string"},
                    "difficulty": {"type": "string", "enum": ["beginner", "intermediate", "advanced"]},
                    "limit": {"type": "integer", "default": 10},
                },
                "required": ["query"],
            },
        },
        {
            "name": "forge_subject_list",
            "description": "List all learning subjects with concept and objective counts.",
            "input_schema": {
                "type": "object",
                "properties": {},
            },
        },
    ]


def _execute_tool(name: str, inputs: dict) -> str:
    """Execute a JayBrain tool and return the result as a string."""
    import json as _json

    try:
        if name == "remember":
            from .memory import remember as _remember
            mem = _remember(
                inputs["content"],
                inputs.get("category", "semantic"),
                inputs.get("tags", []),
                inputs.get("importance", 0.5),
            )
            return _json.dumps({"status": "stored", "memory_id": mem.id, "category": mem.category.value})

        if name == "recall":
            from .memory import recall as _recall
            results = _recall(
                inputs["query"],
                inputs.get("category"),
                None,
                inputs.get("limit", 5),
            )
            memories = [
                {"content": r.memory.content, "category": r.memory.category.value,
                 "score": round(r.score, 3), "created_at": r.memory.created_at.isoformat()[:10]}
                for r in results
            ]
            return _json.dumps({"count": len(memories), "memories": memories})

        if name == "task_create":
            from .tasks import create_task
            task = create_task(
                inputs["title"],
                inputs.get("description", ""),
                inputs.get("priority", "medium"),
                inputs.get("project", ""),
                inputs.get("tags"),
                None,
            )
            return _json.dumps({"status": "created", "task_id": task.id, "title": task.title})

        if name == "task_update":
            from .tasks import modify_task
            fields = {}
            for key in ("status", "title", "priority"):
                if key in inputs and inputs[key] is not None:
                    fields[key] = inputs[key]
            task = modify_task(inputs["task_id"], **fields)
            if task:
                return _json.dumps({"status": "updated", "task_id": task.id, "title": task.title, "task_status": task.status.value})
            return _json.dumps({"status": "not_found"})

        if name == "task_list":
            from .tasks import get_tasks
            tasks = get_tasks(
                inputs.get("status"),
                inputs.get("project"),
                inputs.get("priority"),
                inputs.get("limit", 20),
            )
            items = [{"id": t.id, "title": t.title, "status": t.status.value, "priority": t.priority.value, "project": t.project} for t in tasks]
            return _json.dumps({"count": len(items), "tasks": items})

        if name == "knowledge_search":
            from .knowledge import search_knowledge_entries
            results = search_knowledge_entries(inputs["query"], None, inputs.get("limit", 5))
            entries = [{"title": r.knowledge.title, "content": r.knowledge.content[:300], "score": round(r.score, 3)} for r in results]
            return _json.dumps({"count": len(entries), "results": entries})

        if name == "pulse_active":
            from .pulse import get_active_sessions
            result = get_active_sessions(inputs.get("stale_minutes", 120))
            return _json.dumps(result)

        if name == "profile_get":
            from .profile import get_profile
            return _json.dumps(get_profile())

        if name == "forge_study":
            from .forge import get_study_queue
            result = get_study_queue(
                inputs.get("category"),
                inputs.get("limit", 10),
                inputs.get("subject_id"),
            )
            return _json.dumps(result, default=str)

        if name == "forge_review":
            from .forge import record_review
            concept = record_review(
                inputs["concept_id"],
                inputs["outcome"],
                inputs.get("confidence", 3),
                inputs.get("time_spent_seconds", 0),
                inputs.get("notes", ""),
                inputs.get("was_correct"),
                inputs.get("error_type", ""),
                inputs.get("bloom_level", ""),
            )
            return _json.dumps({
                "status": "reviewed",
                "concept_id": concept.id,
                "term": concept.term,
                "mastery_level": concept.mastery_level,
                "mastery_name": concept.mastery_name,
                "review_count": concept.review_count,
                "next_review": concept.next_review.isoformat() if concept.next_review else None,
            })

        if name == "forge_explain":
            from .forge import get_concept_detail
            result = get_concept_detail(inputs["concept_id"])
            if result:
                return _json.dumps(result, default=str)
            return _json.dumps({"error": "Concept not found"})

        if name == "forge_readiness":
            from .forge import calculate_readiness
            result = calculate_readiness(inputs["subject_id"])
            return _json.dumps(result, default=str)

        if name == "forge_search":
            from .forge import search_concepts
            results = search_concepts(
                inputs["query"],
                inputs.get("category"),
                inputs.get("difficulty"),
                inputs.get("limit", 10),
            )
            return _json.dumps(results, default=str)

        if name == "forge_subject_list":
            from .forge import get_subjects
            result = get_subjects()
            return _json.dumps(result, default=str)

        return _json.dumps({"error": f"Unknown tool: {name}"})

    except Exception as e:
        logger.error("Tool %s execution error: %s", name, e, exc_info=True)
        return _json.dumps({"error": str(e)})


# ---------------------------------------------------------------------------
# Standalone send (for MCP tool -- works even if bot is stopped)
# ---------------------------------------------------------------------------

def _log_telegram_send(
    caller: str, chat_id: str, text: str,
    chunks_sent: int, status: str, error: str = "",
) -> None:
    """Log a Telegram send to the telegram_send_log table."""
    try:
        from .db import get_connection, now_iso
        conn = get_connection()
        preview = text[:100] if text else ""
        conn.execute(
            """INSERT INTO telegram_send_log
            (timestamp, caller, chat_id, message_preview, chunks_sent, status, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (now_iso(), caller, str(chat_id), preview, chunks_sent, status, error),
        )
        conn.commit()
    except Exception:
        pass  # Logging failure must never break message delivery


def send_telegram_message(text: str, caller: str = "mcp_tool") -> dict:
    """Send a message to JJ via Telegram. Used by the MCP tool and daemon.

    Args:
        text: Message text to send.
        caller: Identifier for who is calling (for audit logging).
    """
    if not TELEGRAM_BOT_TOKEN:
        return {"error": "TELEGRAM_BOT_TOKEN not set"}

    api = TelegramAPI(TELEGRAM_BOT_TOKEN)
    chat_id = TELEGRAM_AUTHORIZED_USER
    chunks = _split_message(text)
    sent = 0

    for chunk in chunks:
        try:
            api.send_message(chat_id, chunk)
            sent += 1
        except Exception:
            try:
                api.send_message_plain(chat_id, chunk)
                sent += 1
            except Exception as e:
                _log_telegram_send(caller, chat_id, text, sent, "error", str(e))
                return {"error": str(e), "chunks_sent": sent}

    _log_telegram_send(caller, chat_id, text, sent, "sent")
    return {"status": "sent", "chunks": sent, "total_length": len(text)}


def get_bot_status() -> dict:
    """Get bot status for the MCP tool."""
    conn = get_connection()
    try:
        state = get_telegram_bot_state(conn)
        if not state:
            return {"running": False, "error": "No bot state in DB"}

        pid = state["pid"]
        running = False
        if pid:
            try:
                os.kill(pid, 0)  # signal 0 = check if process exists
                running = True
            except (OSError, ProcessLookupError):
                running = False

        uptime = 0.0
        if running and state["started_at"]:
            try:
                start_dt = datetime.fromisoformat(state["started_at"])
                uptime = (datetime.now(timezone.utc) - start_dt).total_seconds()
            except (ValueError, TypeError):
                pass

        return {
            "running": running,
            "pid": pid,
            "uptime_seconds": round(uptime, 1),
            "messages_in": state["messages_in"],
            "messages_out": state["messages_out"],
            "last_heartbeat": state["last_heartbeat"],
            "last_error": state["last_error"] or None,
            "model": GRAMCRACKER_CLAUDE_MODEL,
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """CLI entry point: init DB, create bot, run."""
    from .config import init as config_init
    config_init()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    logger.info("Initializing database...")
    init_db()

    logger.info("Starting GramCracker...")
    bot = GramCracker()
    bot.run()


if __name__ == "__main__":
    main()
