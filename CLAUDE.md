# CLAUDE.md

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.


## 1. Harness Engineering Orchestrator Instructions

Read:
- `harness/AGENTS.md`
- `harness/docs/harness_workflow.md`

### 1.1. Task Scale Decision (mandatory before any src/ change)

- Small(Bug fix, util addition, single-module edit): Generator → Evaluator → commit
- Large(New module, pipeline design, multi-module change): Planner → Generator → Evaluator → commit
  + Create `docs/exec_plans/<task>/SPEC.md` (large tasks only)

### 1.2. Invariants
- Generator and Evaluator MUST be called as separate sub-agents (isolation is the point).
- All `src/` changes MUST run inside a worktree — never edit the main worktree directly.
- Agents communicate via files only — no direct invocation between agents.
- Skip SPEC.md and SELF_CHECK.md for small tasks; pass the user request directly to Generator.


## 2. Project Rules

### 2.1. Environment Variables
- NEVER read or modify `.env`
- Modify `.env.example` only

### 2.2. Cleanup
- Remove temporary and debug files before finishing
- NEVER create: `temp_*`, `*_new`, `*_old`, `*_backup`

### 2.3. Execution
- Local: **Always use `uv run python`** — never call `python3` or `python` directly
- Docker: `pip + requirements.txt`
- After modifying `alembic/` migration files, a full image rebuild is required before re-applying:
  ```bash
  docker compose down -v
  docker compose build --no-cache api
  docker compose up -d postgres redis
  docker compose run --rm api alembic upgrade head
  ```

### 2.4. Code
- Use type hints
- Use `logging`, never `print()`
- Add Korean docstrings to Python functions and classes
- Never use Chinese characters: write "분석" (U+BD84 U+C11D), not "분析" (U+BD84 U+6790) or "分析"

### 2.5. Commits
- Commit only after tests pass
- Keep commits atomic — commit per file or per logical change
- Write commit messages in Korean

### 2.6. Naming
- Use `snake_case` for files, folders, and functions
- Use `PascalCase` for classes
- Wrap file paths in backticks

### 2.7. Efficiency
- Do not reread files already read
- Run tool calls in parallel when possible
- Do not repeat user-provided information

### 2.8. Code Search
- Use Serena plugin first
- Use bash `grep` only as a fallback
