# 분류기 모드 및 작업 유형

`CLASSIFIER_MODE` 환경변수로 분석 방식을 선택한다 (기본값: `llm`).

---

## CLASSIFIER_MODE=llm (기본)

Gemini url_context 툴로 웹사이트를 분석한다.

### 1. 단건 분석: `analyze_url`

- **엔드포인트**: `POST /api/v1/analyze`
- **처리**: Celery 큐 `analyze` → `analyze_url` 태스크
- **특징**:
  - DB 캐시 확인 (LLM 분석 결과 있으면 호출 스킵, rule 결과는 재분석)
  - 접근 불가 TTL 이내 URL 즉시 실패 처리 (7일)
  - time_limit: 300s, soft_time_limit: 240s
  - max_retries: 3회 (지수 백오프, 60s × N)

### 2. 배치 분석: `analyze_urls_batch`

- **엔드포인트**: `POST /api/v1/analyze/batch/upload`, `POST /api/v1/analyze/batch/file`
- **처리**: Celery 큐 `analyze` → `analyze_urls_batch` 태스크
- **특징**:
  - ThreadPoolExecutor로 병렬 단건 LLM 분석 (동시 워커: `BATCH_CONCURRENCY`, 기본 5)
  - 각 워커: 독립 DB 세션
  - time_limit: 600s, soft_time_limit: 540s
  - max_retries: 3회

### 3. 백그라운드 병렬 분석: `analyze_urls_bulk`

- **처리**: 백그라운드 작업 (API 엔드포인트 없음, Python 내부 호출)
- **파라미터**: `urls`, `force_reanalyze`, `source_path` (출력 파일명 기준)
- **특징**:
  - ThreadPoolExecutor 병렬 단건 처리 (동시 워커: `BATCH_CONCURRENCY`, 기본 5)
  - 스킵 조건: 기존 LLM 분석 결과 존재 (캐시 히트), 접근 불가 TTL 이내
  - 재분석 조건: `failure`/`blocked` 상태, `rule` 분류 결과
  - 성공/실패 항목 모두 결과 파일에 기록 (`source_path` 기준 타임스탬프 파일)
  - time_limit: 3600s (1시간), max_retries: 0

---

## CLASSIFIER_MODE=rule

규칙기반 8단계 파이프라인으로 오프라인 분석한다 (`src/rule/` 패키지).

### 규칙기반 분류: `rule_classify`

- **엔드포인트**: `POST /api/v1/rule/classify`
- **처리**: 동기 분석 (API 응답에 결과 즉시 포함)
- **기술**: 키워드 매칭 + 휴리스틱 기반 신호 추출
- **특징**:
  - 외부 API 비용 없음
  - 오프라인 환경에서 동작 가능
  - requests + Playwright 폴백으로 페이지 수집
  - 5가지 품질 기준 평가 (usable_now, clear_function_desc, docs, policy, pricing)
  - 가중치 기반 점수화 (0~100)
  - 상태 판정: curated / incubating / rejected
  - **신뢰도 기반 캐시 스킵**:
    - `analyzer != "rule"` (LLM 결과) → 항상 캐시 반환
    - `hard_pass=true` + `review_required=false` + `total_score >= 60.0` → 캐시 반환
    - 그 외 → 파이프라인 재실행 후 DB 갱신

> **주의**: 단건 `POST /api/v1/analyze` 엔드포인트는 `CLASSIFIER_MODE` 값과 무관하게 항상 LLM으로 분석한다.

---

## 에러 처리 정책

`src/core/error_policy.py`의 `ApiErrorKind`로 에러를 분류하고, 종류별로 재시도 여부와 DB 상태를 결정한다.

| ApiErrorKind | HTTP/gRPC | retryable | site_status |
|---|---|---|---|
| UNREACHABLE | 400/INVALID_ARGUMENT | ✗ | unreachable |
| PRECONDITION_FAILED | 400/FAILED_PRECONDITION | ✗ | blocked |
| NOT_FOUND | 404/NOT_FOUND | ✗ | unreachable |
| AUTH_ERROR | 401/UNAUTHENTICATED | ✗ | blocked |
| PERMISSION_DENIED | 403/PERMISSION_DENIED | ✗ | blocked |
| RATE_LIMITED | 429/RESOURCE_EXHAUSTED | ✓ | — |
| TIMEOUT | 504/DEADLINE_EXCEEDED | ✓ | — |
| SERVER_UNAVAILABLE | 503/UNAVAILABLE | ✓ | — |
| SERVER_INTERNAL | 500/INTERNAL | ✓ | — |
| UNKNOWN | — | ✓ | failure |

### 접근 불가 TTL

`status = 'unreachable'`인 URL은 `unreachable_since`로부터 **7일** 이내 재분석 요청을 즉시 실패로 처리한다. TTL 경과 후 재분석 대상으로 자동 전환된다.

---

## 관련 문서

- [ARCHITECTURE.md](../ARCHITECTURE.md) — 전체 시스템 아키텍처
- [API_SPECIFICATION.md](API_SPECIFICATION.md) — API 명세
- [DATA_MODEL.md](DATA_MODEL.md) — 데이터베이스 스키마
