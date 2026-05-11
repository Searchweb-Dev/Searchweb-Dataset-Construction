# CLAUDE.md

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

## 하네스 엔지니어링 오케스트레이터 지시서

3-Agent 하네스 구조(Planner → Generator → Evaluator)
백엔드/데이터 처리 프로젝트를 설계·구현·검수한다

에이전트 목록은 `harness/AGENTS.md` 를 참고하라.
`harness/docs/harness_workflow.md`의 실행 흐름을 **필수**로 진행한다.

### 코드 작업 전 필수 절차

- **기능 개발, 버그 수정, 리팩터링 등 src/ 코드를 변경하는 모든 작업에 적용된다.**
- 코드 작업 전 태스크 규모를 먼저 판단한다: **소규모**(버그 수정·유틸 추가·단일 모듈 수정) vs **중대형**(신규 모듈·파이프라인·다중 모듈 연동)
- **중대형만**: Planner를 호출하여 `docs/exec_plans/<type>_<task_name>/SPEC.md`를 생성한다. 호출 시 사용자 요청과 핵심 의도(방향·완료 기준)를 함께 전달
- 테스트 통과 및 Evaluator 합격 후 커밋

---

## 프로젝트 규칙

### 실행 규칙
- 로컬 개발: uv 가상환경에서 실행.
- 도커: pip + requirements.txt 사용 (uv는 로컬 전용).

### 환경변수 규칙
- `.env` **접근 금지**, **절대 직접 수정 금지**
- 환경변수 추가·변경 -> `.env.example`만 수정.

### 절약 규칙
- **이미 읽은 파일은 다시 확인하지 않는다.**
- 가능한 도구 호출은 동시에 실행한다.
- 20줄 이상의 불필요한 출력은 서브에이전트에 위임한다.
- **사용자가 이미 설명한 내용을 다시 반복하지 않는다.**

### 네이밍 규칙
- 파일명·폴더명은 모두 snake_case 사용
- 함수명: snake_case / 클래스명: PascalCase
- 파일 경로는 항상 백틱으로 감싸라: `harness/agents/planner.md`                        
- LLM 지시문에서는 "파일을 읽어라" 동사와 함께 작성

### 코드 규칙
- 한 함수는 하나의 역할만 수행
- 타입 힌트 필수
- 파일 형식에 맞는 방식으로 한글 설명 작성:
  + Python (`.py`): 클래스·함수에 `"""한글 docstring"""`
  + Dockerfile: 파일 상단 및 주요 블록에 `# 한글 주석`
  + Docker Compose (`.yml`): 서비스·섹션 위에 `# 한글 주석`
  + 환경변수 (`.env`, `.env.example`): 항목 위에 `# 한글 주석`
  + 설정 파일 (`.toml`, `.ini`, `.cfg`): `# 한글 주석`
- 로그&로깅에는 `logging` 사용, `print()` 사용 금지
- 불필요한 `---` 사용 자제

### 커밋 규칙
~~ - 커밋 전에 나한테 커밋 의사를 물어보고 진행해. ~~
- 코드 수정 및 변경 후 테스트까지 통과하면 커밋해.
- Conventional Commits 형식 사용: `feat(scope): 설명`
  + 타입: `feat`, `fix`, `refactor`, `docs`, `test`, `chore` 등
- scope는 변경 대상 모듈명 사용: `feat(planner): 기능 추가`
- 한 커밋에 하나의 변경만 (atomic commit)
  + 변경 내용이 다르면 파일별로 작성
- 커밋 메시지는 한국어로 일관되게 작성

### 정리 규칙
- 임시 파일은 작업 완료 즉시 삭제
- `temp_`, `_new`, `_old`, `_backup` 이름의 파일을 만들지 않는다
- 작업 중 생성한 디버그용 코드는 PR 전에 삭제

### 코드 내 검색 규칙
- 심볼 검색(함수·클래스·변수 정의·참조 찾기)은 반드시 serena plugin을 사용한다.
- `find_symbol`, `find_declaration`, `find_referencing_symbols`, `find_implementations` 등 serena 도구를 우선한다.
- 단순 텍스트 패턴 매칭은 `search_for_pattern` (serena)을 사용하고, bash grep은 serena로 해결이 안 될 때만 fallback으로 사용한다.
