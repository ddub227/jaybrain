# Initial Build - Foundation Through Hybrid Search (Phases 1-3)

| Field | Value |
|-------|-------|
| **Focus** | MCP server architecture, SQLite schema, Pydantic models, hybrid search, memory/tasks/sessions/knowledge |
| **Files Modified** | All files created from scratch - 13 source files, 5 test files, 3 config files |
| **Goal** | Working JayBrain MCP server with all 18 tools, hybrid vector+keyword search, persistent memory |

---

## Summary

- Built complete JayBrain MCP server from scratch in a single session (Phases 1-3)
- 18 MCP tools across 6 groups: Memory (3), Profile (2), Tasks (3), Sessions (3), Knowledge (3), System (3)
- SQLite database with FTS5 full-text search and sqlite-vec vector similarity search
- ONNX Runtime for fast embeddings (replacing sentence-transformers which took 113s to import)
- File-first memory pattern: Markdown files as source of truth, DB as rebuildable index
- 43 tests passing covering models, memory decay, hybrid search, DB ops, profiles, tasks, sessions

## Architecture Decisions

### ONNX Runtime over sentence-transformers
- **Context:** Need embedding generation for vector search, but MCP servers must start fast
- **Options Considered:** sentence-transformers (familiar, slow), ONNX Runtime (fast, lower-level), no vectors (keyword only)
- **Decision:** ONNX Runtime + tokenizers library for direct model inference
- **Trade-offs:** More manual code for tokenization/pooling, but 50x faster startup (2-3s vs 113s)

### SQLite + sqlite-vec over ChromaDB/FAISS/DuckDB
- **Context:** Need vector storage and keyword search in a single, portable solution
- **Options Considered:** ChromaDB (separate server), FAISS (no keyword search), DuckDB (heavyweight), SQLite + sqlite-vec
- **Decision:** SQLite with FTS5 for keyword search and sqlite-vec extension for vectors
- **Trade-offs:** All in one file, no server needed, but sqlite-vec is newer and less battle-tested

### File-First Memory Pattern (from OpenClaw)
- **Context:** Memories need to survive DB corruption and be human-inspectable
- **Options Considered:** DB-only, file-only, hybrid (file + DB)
- **Decision:** Markdown files in `data/memories/` as source of truth; DB is a fast index
- **Trade-offs:** Slight write overhead (dual write), but memories are grep-able and git-versionable

### FastMCP over Raw MCP SDK
- **Context:** Need to register 18 tools with the MCP protocol
- **Options Considered:** Raw mcp package, FastMCP decorator-based approach
- **Decision:** FastMCP for its clean `@mcp.tool()` decorator pattern
- **Trade-offs:** Extra dependency, but dramatically cleaner code

## Code Written

### `config.py` (~40 lines)
- **Purpose:** Central location for all paths, constants, and data directory setup
- **Key Design Choices:** All paths derived from `PROJECT_ROOT`, memory categories defined as constants
- **How It Works:** `ensure_data_dirs()` creates all needed directories idempotently

### `models.py` (~200 lines)
- **Purpose:** Pydantic data models for all entities (Memory, Task, Session, Knowledge, Profile, Stats)
- **Key Design Choices:** Enums for categories/statuses/priorities to prevent invalid values; separate Create/Update/Full models
- **How It Works:** Pydantic validates all inputs at model boundaries, catching errors before they hit the DB

### `db.py` (~250 lines)
- **Purpose:** SQLite schema initialization, CRUD operations, FTS5/vec setup
- **Key Design Choices:** FTS5 triggers keep keyword index in sync automatically; WAL mode for concurrent reads
- **How It Works:** `init_db()` runs full schema SQL idempotently (CREATE IF NOT EXISTS). CRUD helpers handle JSON serialization of tags/lists. Vector data serialized as raw float32 bytes.

### `memory.py` (~200 lines)
- **Purpose:** High-level memory operations: remember, recall (hybrid search), forget, reinforce
- **Key Design Choices:** Decay computed at query time (not stored), FTS5 queries sanitized to prevent syntax errors
- **How It Works:** `remember()` generates embedding, writes markdown file, inserts into DB atomically. `recall()` runs parallel vector + keyword paths, merges with 70/30 weighting, applies decay.

### `search.py` (~200 lines)
- **Purpose:** Hybrid search engine combining vector similarity and BM25 keyword scoring
- **Key Design Choices:** Lazy-loaded ONNX model (first call ~2-3s, subsequent <100ms); mean pooling with L2 normalization
- **How It Works:** `embed_text()` tokenizes, pads, runs ONNX inference, mean-pools, normalizes. `hybrid_search()` normalizes both score types to 0-1 range, combines with configurable weights.

### `server.py` (~450 lines)
- **Purpose:** MCP server entry point with all 18 tool definitions
- **Key Design Choices:** Lazy imports inside tool functions to avoid circular dependencies; all tool returns are JSON strings; all logging to stderr
- **How It Works:** FastMCP decorators register functions as MCP tools. Each tool wraps a module function with JSON serialization and error handling.

### `profile.py`, `sessions.py`, `tasks.py`, `knowledge.py`
- **Purpose:** Domain-specific CRUD operations for each feature area
- **Key Design Choices:** Each module manages its own connection lifecycle; sessions write handoff markdown files for human readability

## Concepts Learned

### MCP (Model Context Protocol)
- **What it is:** A protocol that lets LLM applications (like Claude Code) call external tools over stdio
- **Why it matters:** JayBrain runs as an MCP server that Claude Code calls, giving it persistent memory
- **Example:** Claude Code sends `{"method": "tools/call", "params": {"name": "remember", ...}}` over stdin, JayBrain processes it and returns JSON on stdout

### sqlite-vec
- **What it is:** A SQLite extension that adds vector similarity search (KNN) to SQLite
- **Why it matters:** Enables semantic search without a separate vector database
- **Example:** `SELECT id, distance FROM memories_vec WHERE embedding MATCH ? ORDER BY distance LIMIT 10`

### FTS5 + BM25
- **What it is:** SQLite's built-in full-text search with BM25 ranking
- **Why it matters:** Catches exact keyword matches that vector search might miss
- **Example:** A search for "Python" finds memories mentioning Python even if the vector similarity to the query is low

### Memory Decay
- **What it is:** Time-based relevance reduction for memories, inspired by human memory
- **Why it matters:** Old, unused memories naturally fade; frequently accessed ones stay strong
- **Example:** A 6-month-old memory with 0 accesses has ~0.5 decay; the same memory with 5 accesses has ~0.75 decay

## Dependencies & Tools

| Tool/Package | Purpose | Why Chosen |
|---|---|---|
| FastMCP 2.14 | MCP server framework | Clean decorator API, handles stdio transport |
| Pydantic 2.11 | Data validation | Type-safe models, automatic serialization |
| ONNX Runtime 1.24 | Embedding inference | 50x faster than sentence-transformers |
| tokenizers 0.21 | Text tokenization | Rust-based, loads in <1 second |
| sqlite-vec 0.1.6 | Vector search in SQLite | Single-file solution, no external DB |
| PyYAML 6.0 | Profile YAML handling | Human-editable config format |
| NumPy 1.26 | Array ops for embeddings | Mean pooling, normalization |

## Next Steps

- [ ] Test full end-to-end flow in Claude Code (register MCP, verify all 18 tools work)
- [ ] Download and test ONNX embedding model (first-run download flow)
- [ ] Phase 4: Error handling hardening, edge cases
- [ ] Phase 5: DuckDB analytics layer (optional)
- [ ] Merge into homelab ecosystem if JayBrain proves useful

## Key Takeaway

> **Insight:** The best architecture is the one that doesn't exist - by building JayBrain as an MCP server extending Claude Code, we get a full AI assistant by writing only ~2,400 lines of memory/persistence code instead of building an entire LLM application from scratch.
