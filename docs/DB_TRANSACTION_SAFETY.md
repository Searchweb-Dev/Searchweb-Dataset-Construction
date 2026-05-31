# DB 트랜잭션 안전성 — mark_site_status 독립 세션 설계

## 배경

`mark_site_status`는 분석이 실패한 URL의 `ai_site.status`를 기록하는 함수다.
수정 전에는 호출자(`analyze_url`, `_analyze_one`)가 소유한 세션을 그대로 인자로 받아
그 위에서 `commit()`을 수행했다.

```python
# 수정 전 시그니처
def mark_site_status(db: Session, url: str, status: str) -> None:
    ...
    db.commit()   # ← 호출자 세션을 직접 커밋
```

이 구조는 PostgreSQL 환경에서 묵시적 장애를 일으킨다.

---

## 문제 상황

### PostgreSQL 트랜잭션 상태 머신

PostgreSQL은 트랜잭션에 다음 세 가지 상태를 유지한다.

| 상태 | 설명 |
|---|---|
| `idle` | 트랜잭션 없음 |
| `in transaction` | 트랜잭션 진행 중 |
| `in failed transaction` | 오류 발생 — 이후 모든 쿼리 차단 |

`in failed transaction` 상태에서는 `COMMIT` / `ROLLBACK` 외 어떤 쿼리도
`ERROR: current transaction is aborted` 를 반환하며 실행되지 않는다.

### 실패 흐름

```
analyze_url (Celery task)
│
├─ db = SessionLocal()           # 세션 생성, 트랜잭션 시작
│
├─ detector.detect_and_save()    # LLM 분석 + AISite 저장 시도
│    └─ 내부에서 예외 발생 → db.rollback()
│         ※ rollback() 이후 세션은 다시 'idle' 상태로 복귀하지만,
│           SQLAlchemy의 autobegin 동작으로 다음 query 전에
│           새 트랜잭션이 자동 시작됨.
│           그러나 DB 드라이버(psycopg2 등)가 아직 이전 오류 상태를
│           내부적으로 유지하는 경우 다음 쿼리가 실패할 수 있음.
│
├─ db.rollback()                 # 호출자가 명시적 rollback
├─ db.expire_all()               # 세션 캐시 무효화
│
└─ mark_site_status(db, url, status)   # ← 동일 세션 재사용
     ├─ db.query(AISite)...      # 트랜잭션 상태에 따라 실패 가능
     └─ db.commit()              # 실패 시 status 기록 누락
```

### 발생 조건

- DB: PostgreSQL (SQLite는 트랜잭션 상태 머신이 단순해 이 문제가 없음)
- 드라이버: psycopg2, asyncpg 등 PEP 249 호환 드라이버
- `detect_and_save` 내부에서 예외가 발생해 `db.rollback()`이 불린 직후
  `mark_site_status`가 같은 세션을 재사용할 때

### 증상

- `mark_site_status`가 조용히 실패 → `ai_site.status` 갱신 누락
- 에러 로그에 `InFailedSqlTransaction` 또는 `current transaction is aborted` 출력
- 해당 URL이 `unreachable` / `blocked`로 기록되지 않아 TTL 스킵이 동작하지 않음
  → 이후 배치에서 동일 URL을 반복 분석해 API 할당량 낭비

---

## 해결책: 독립 세션

`mark_site_status`가 항상 새로운 `SessionLocal()`을 내부에서 열도록 변경했다.

```python
# 수정 후 시그니처
def mark_site_status(url: str, status: str) -> None:
    db = SessionLocal()          # ← 독립 세션
    try:
        ...
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
```

호출부에서 `db` 인자가 제거됐다.

```python
# analyze_url, _analyze_one 공통
db.rollback()
mark_site_status(url, policy.site_status)   # db 인자 없음
db.expire_all()
```

### 독립 세션의 보장

1. **오염 없음** — 호출자 세션의 트랜잭션 상태와 완전히 분리된다.
2. **원자성** — `mark_site_status` 내부의 쿼리와 커밋이 하나의 새 트랜잭션으로 처리된다.
3. **예외 전파** — 독립 세션에서 오류가 나도 `rollback` 후 예외를 그대로 올린다.

---

## 주의: db.expire_all() 호출 순서

호출자 세션에서 `mark_site_status` 이후에도 동일 세션(`db`)을 이용해
`AnalysisJob` 상태를 갱신하는 코드가 있다.

```python
db.rollback()
mark_site_status(url, policy.site_status)   # 독립 세션 — 안전
db.expire_all()                              # 호출자 세션 캐시 무효화
job = db.query(AnalysisJob)...              # 새 트랜잭션으로 조회
```

`expire_all()`은 `mark_site_status` 이후에 호출해야 한다.
`expire_all()`을 먼저 호출하면 `mark_site_status` 내부와 무관하지만,
이후 `db.query(AnalysisJob)` 시 세션이 autobegin으로 새 트랜잭션을 시작하는 것을
명확히 보장하기 위해 순서를 고정한다.

---

## 관련 파일

| 파일 | 역할 |
|---|---|
| `src/workers/job_status.py` | `mark_site_status` 구현 (독립 세션) |
| `src/workers/analyze_task.py` | 단건(`analyze_url`) 및 배치(`_analyze_one`) 호출부 |
| `src/db/session.py` | `SessionLocal` 팩토리 |
