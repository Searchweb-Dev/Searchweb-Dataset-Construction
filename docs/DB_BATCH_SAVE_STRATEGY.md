# 배치 분석 DB 저장 전략

## 결론

**URL마다 즉시 커밋하는 현행 방식을 유지한다.**

---

## 배경

`analyze_urls_bulk`는 `ThreadPoolExecutor`로 URL을 병렬 분석한다.
각 워커(`_analyze_one`)는 독립 세션을 열고, LLM 분석 완료 즉시 DB에 저장한 뒤 세션을 닫는다.

```
_analyze_one(url)
  └─ AIDetector.detect_and_save(url)
       ├─ analyzer.analyze_website(url)   # LLM 호출 (수 초~수십 초)
       ├─ _save_site()
       ├─ _save_categories_and_tags()
       └─ db.commit()                     # URL 1개마다 즉시 커밋
```

URL 100개, concurrency=5 기준 세션 수:

| 단계 | 세션 수 |
|---|---|
| `prepare_bulk_urls` (Job 생성) | 1 |
| `_mark_jobs_processing` | 1 |
| `_analyze_one` × N | N (동시 점유는 최대 5) |
| `mark_site_status` (실패 시) | 실패 건수만큼 |
| `update_job_statuses` | 1 |

총 세션 생성 횟수는 URL 수에 비례하지만, **동시에 DB를 점유하는 세션은 concurrency(기본 5)개**뿐이다.

---

## 대안 검토

### A. 완전 일괄 저장 (배치 완료 후 commit 1회)

```
_analyze_one → 결과를 메모리에 적재
배치 완료 후 → 전체 결과를 단일 트랜잭션으로 저장
```

| 항목 | 평가 |
|---|---|
| commit 횟수 | 1회 |
| 세션 수 | 3~4개 고정 |
| 배치 중단 시 | **분석 완료분 전체 유실** — 메모리에만 존재하므로 worker 재시작/타임아웃 시 사라짐 |
| 트랜잭션 길이 | 저장 시 길어짐 (lock 유지 시간 증가) |

### B. 청크 저장 (N개마다 commit)

```
_analyze_one → 결과를 메모리에 적재
N개 누적 시 → 부분 저장
```

중단 시 유실 범위를 N개로 줄일 수 있으나, 코드 복잡도가 높아진다.
동기화 오버헤드(락, 공유 버퍼 관리)도 발생한다.

### C. 현행 유지 (즉시 저장)

```
_analyze_one → detect_and_save → db.commit()
```

| 항목 | 평가 |
|---|---|
| commit 횟수 | URL 수만큼 |
| 세션 수 | URL 수만큼 (동시 점유는 concurrency개) |
| 배치 중단 시 | 완료분 DB에 보존 |
| 트랜잭션 길이 | 짧음 |
| 코드 복잡도 | 단순 |

---

## 현행 유지 근거

### DB 부하는 실질적으로 작다

각 `_analyze_one`의 총 실행 시간 중 LLM API 호출이 대부분을 차지한다.

```
_analyze_one 실행 시간 분포 (concurrency=5 기준)
  LLM 호출:   ████████████████████  수 초~수십 초
  DB 저장:    ▏                     수 ms
```

동시에 DB에 접근하는 세션은 최대 5개이고, pool_size=10으로 충분히 여유 있다.
commit이 URL마다 발생하더라도 LLM 대기 시간 사이에 분산되어 DB에 집중 부하가 걸리지 않는다.

### 배치 중단 시 완료분이 보존된다

worker 재시작, soft_time_limit 초과, 예외 등으로 배치가 중단되어도
이미 `db.commit()`이 완료된 URL의 `AISite`, `AICategory`, `AITag`는 DB에 남는다.
다음 배치 실행 시 `prepare_bulk_urls`의 스킵 로직이 이를 감지해 재분석을 건너뛴다.

### 연결 풀 안전 기준

concurrency를 늘릴 경우 pool_size와의 비율을 지켜야 한다.

```
# 안전 기준
pool_size >= BATCH_CONCURRENCY + 여유분(3~5)

# 현재 설정 (적절)
pool_size=10, BATCH_CONCURRENCY=5

# 위험 예시
pool_size=10, BATCH_CONCURRENCY=15  → 풀 소진 → pool_timeout(30초) 후 예외
```

concurrency를 15 이상으로 올릴 경우 `pool_size`와 `max_overflow`를 함께 조정해야 한다.

---

## 개선 검토 시점

현행 방식의 한계가 드러나는 조건은 다음과 같다. 이 조건에 해당할 때 청크 저장(B안) 재검토를 권장한다.

- `BATCH_CONCURRENCY` ≥ 20
- 단일 배치 URL 수 ≥ 500
- LLM 응답 시간이 단축되어 DB 저장이 병목이 되는 경우

---

## 관련 파일

| 파일 | 역할 |
|---|---|
| `src/workers/analyze_task.py` | `_analyze_one`, `analyze_urls_bulk` |
| `src/db/site_service.py` | `AIDetector.detect_and_save` (즉시 커밋) |
| `src/workers/bulk_preflight.py` | `prepare_bulk_urls` (스킵 판별) |
| `src/db/session.py` | 커넥션 풀 설정 (`pool_size`, `max_overflow`) |
