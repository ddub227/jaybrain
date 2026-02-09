# JayBrain Development Journal Index

## Project Overview

| Field | Value |
|-------|-------|
| **Project** | JayBrain - Personal AI Memory MCP Server |
| **Started** | 2026-02-08 |
| **Stack** | Python, FastMCP, SQLite + sqlite-vec, ONNX Runtime |
| **Repo** | `C:\Users\Joshua\jaybrain` |

## Session Log

| Date | Title | Phase | Key Outcome |
|------|-------|-------|-------------|
| 2026-02-08 | Initial Build - Foundation Through Hybrid Search | Phase 1-3 | Full MCP server with 18 tools, hybrid search, memory/tasks/sessions/knowledge |

## Milestones

- [x] Phase 1: Core memory (remember/recall/forget/stats)
- [x] Phase 2: Profile + sessions + tasks
- [x] Phase 3: Hybrid search + knowledge base
- [ ] Phase 4: Tests + polish
- [ ] Phase 5: DuckDB analytics layer
- [ ] Phase 6: Silent context flush detection
- [ ] Phase 7: Multi-project memory namespaces
- [ ] Phase 8: Memory consolidation and summarization

## Architecture Decisions Log

| Decision | Date | Rationale |
|----------|------|-----------|
| ONNX Runtime over sentence-transformers | 2026-02-08 | sentence-transformers takes 113s to import; ONNX loads in <3s |
| SQLite + sqlite-vec over ChromaDB/FAISS | 2026-02-08 | Single file, no server, built-in FTS5 for keyword search |
| File-first memory pattern | 2026-02-08 | Markdown files as source of truth; DB is a rebuildable index |
| FastMCP over raw MCP SDK | 2026-02-08 | Cleaner decorator API, built-in transport handling |
