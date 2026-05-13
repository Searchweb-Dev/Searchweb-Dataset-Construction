# ARCHITECTURE.md

# AI Website Evaluation Worker Architecture

## Overview

이 프로젝트는 URL을 입력받아 웹사이트를 분석하고,
해당 사이트가 유용한 AI 서비스인지 판별하는 **AI 사이트 분석 Worker** 시스템이다.

Spring Backend와 분리되어 독립적으로 동작하며,
다음 기능을 담당한다:

- FastAPI 기반 비동기 API (Spring Backend와 통신)
- Celery를 통한 비동기 분석 작업 처리
- **Gemini API url_context 툴**을 통한 URL 직접 분석
- Gemini를 통한 AI 사이트 판별 (판별, 분류, 점수화, 요약)
- 규칙기반 분류기를 통한 오프라인 판별 (CLASSIFIER_MODE=rule)
- 분석 결과 저장 (PostgreSQL)
- 분석 상태 관리 (Redis)

---

# High Level Architecture

```text
+---------------------------+
| Spring Backend            |
|---------------------------|
| API / Auth / DB           |
+----------+----------------+
           |
           | POST /analyze?url=...
           v
+---------------------------+
| FastAPI Worker API        |
|---------------------------|
| - Job 생성                 |
| - Job ID 즉시 반환         |
+----------+----------------+
           |
           | enqueue
           v
+---------------------------+
| Redis Queue (Celery)      |
|---------------------------|
| - 작업 큐                  |
| - Job 상태 저장소          |
+----------+----------------+
           |
           v
+---------------------------+
| Celery Worker Process     |
|---------------------------|
| ┌──────────────────────┐ |
| │ Gemini API           │ |
| │ (url_context 툴)     │ |
| │ - URL 직접 fetch     │ |
| │ - AI 사이트 판별     │ |
| └──────────────────────┘ |
| ┌──────────────────────┐ |
| │ Pydantic Validator   │ |
| │ (결과 정규화)        │ |
| └──────────────────────┘ |
+----------+----------------+
           |
           | 결과 저장
           v
+---------------------------+
| PostgreSQL Database       |
|---------------------------|
| - AnalysisJob            |
| - AISite                 |
| - AICategory             |
| - AITag                  |
+---------------------------+
```

---

# Responsibilities

## Spring Backend

Spring Backend는 다음 역할만 담당한다.

- 사용자 요청 처리
- 인증/인가
- Job 요청 전달
- Job 상태 조회
- 최종 결과 저장 및 제공

Worker 내부 구현에는 관여하지 않는다.

---

## Python Worker

Worker는 AI 분석 전용 서비스다.

주요 역할:

- Gemini url_context 툴로 URL fetch 및 분석
- LLM 분석 결과 구조화
- Job 상태 관리

---

# Communication Flow

자세한 API 명세는 [API_SPECIFICATION.md](./docs/API_SPECIFICATION.md) 참조

---

# Worker Internal Architecture

## Components

### API Layer

기술:
- FastAPI

역할:
- Request validation
- Job creation
- Job status API

---

## Queue Layer

기술:
- Redis
- Celery

역할:
- 비동기 Job 처리
- Retry
- Timeout 관리

세부 설정:
- 큐명: `analyze`
- 라우팅: Topic exchange (`analyze.#`)
- Serializer: JSON
- Worker prefetch: 1 (순차 처리)
- Max tasks per child: 1000 (메모리 누수 방지)

---

## Analysis Layer

`CLASSIFIER_MODE` 환경변수로 분석 방식을 선택한다 (기본값: `llm`).

**개요:**
- `CLASSIFIER_MODE=llm` → Gemini API로 웹사이트 분석 (비동기 Celery 작업)
- `CLASSIFIER_MODE=rule` → 규칙기반 로컬 분석 (동기 즉시 반환)

### LLM 분석기 (CLASSIFIER_MODE=llm)

**기술:**
- Google Gemini API
- url_context Tool

**역할:**

Gemini의 url_context 툴이 URL을 직접 fetch하여 콘텐츠를 읽고 분석한다.
별도의 브라우저 프로세스 없이 API 호출 한 번으로 처리된다.

```
Worker → Gemini API (url_context 툴 활성화)
         ↓
Gemini가 자동으로:
  1. URL fetch 및 콘텐츠 추출
  2. AI 사이트 판별
  3. 카테고리 분류
  4. 점수 계산
  5. 요약 생성
```

**구현:**

```python
from google import genai
from google.genai import types

client = genai.Client(api_key=api_key)

response = client.models.generate_content(
    model="gemini-3.1-flash-lite",
    contents=f"다음 URL을 분석하세요: {url}",
    config=types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        tools=[types.Tool(url_context=types.UrlContext())],
        response_mime_type="application/json",
        max_output_tokens=2048,
    ),
)
```

**장점:**

- 로컬 브라우저(Chromium) 불필요 → Worker 이미지 경량화
- API 호출 1회로 fetch + 분석 완료 → 처리 속도 향상
- 병렬 요청 자유로움 (브라우저 프로세스 메모리 압박 없음)
- 인프라 복잡도 최소화

**Playwright 방식 보존:**

로컬 브라우저 렌더링이 필요한 경우(SPA 완전 렌더링, 스크린샷 시각 분석 등)를 위해
기존 Playwright 로직은 `src/ai/_playwright_renderer.py`에 보존되어 있다.
복원 방법은 해당 파일 상단 주석 참조.

---

### 규칙기반 분석기 (CLASSIFIER_MODE=rule)

**기술:**
- requests + Playwright 폴백 (PageFetcher)
- RuleAnalyzer: 8단계 파이프라인 기반 URL 분류
- 키워드 기반 신호 추출 및 규칙 평가

**역할:**

외부 API 호출 없이 로컬에서 웹사이트를 fetch하고 규칙기반으로 분석한다.

```
URL
 ↓
PageFetcher (requests → Playwright 폴백)
 ↓
8단계 파이프라인 (src/rule/pipeline.py)
  step1: 페이지 수집 (homepage + 후보 페이지 병렬 fetch)
  step2: 신호 추출 (DiscoverySignalMixin)
  step3: AI 범위 분류 (AiScopeClassifierMixin)
  step4: 분류 체계 결정 (TaxonomyClassifierMixin)
  step5: 기준 평가 (CriteriaEvaluatorMixin)
  step6: 점수화 및 상태 예측 (WeightedQualityEvaluator)
  step7: 상태 검토 및 확정 (StatusPolicyMixin)
  step8: 요약 생성
 ↓
EvaluationResult → 분석 dict (RuleAnalyzer._map_to_analysis_dict)
```

**주요 컴포넌트:**

- `src/rule/analyzer.py` — RuleAnalyzer 클래스
- `src/rule/pipeline.py` — 8단계 파이프라인 함수 및 run_quality_pipeline()
- `src/rule/config.py` — EvalConfig (파라미터 제어)
- `src/rule/fetchers/page_fetcher.py` — HTTP fetch + Playwright 폴백
- `src/rule/classifiers/` — 분류기 믹스인들
  * `ai_scope_classifier.py` — AI 사이트 여부 판정 (strong/weak 키워드 매칭)
  * `taxonomy_classifier.py` — 카테고리/태그 분류 (PRIMARY_CATEGORY_KEYWORDS 기반)
  * `criteria_evaluator.py` — 5가지 품질 기준 평가 (usable_now, clear_function_desc, has_docs_or_help, has_privacy_or_data_policy, has_pricing)
  * `discovery_signals.py` — 후보 URL 수집 및 신호 추출
  * `status_policy.py` — 상태 예측 및 리뷰 게이트

**장점:**

- API 비용 없음 → 대량 처리에 유리
- 오프라인 환경에서도 동작
- LLM API 의존성 없는 빠른 응답
- 투명한 규칙 기반 판정 (검증 및 커스터마이제이션 용이)

---

## Processing Pipeline

### LLM 분석 (단건: analyze_website)

```
Queue: analyze
  ↓
Celery Task: analyze_website(job_id, url)
  ├─ 1. Job 상태 업데이트: pending → processing (started_at 기록)
  ├─ 2. DB에서 기존 분석 결과 확인
  │  ├─ 캐시 히트 (is_ai_tool이 존재, analyzer != rule)
  │  │  └─ Job 상태: success, site_id 반환 (LLM 호출 안 함)
  │  └─ 캐시 미스 또는 rule 분류 결과 → 3번 진행
  ├─ 3. Gemini API 호출 (url_context 툴)
  │  ├─ Gemini가 URL 직접 fetch
  │  ├─ AI 서비스 여부 판별
  │  ├─ 카테고리 분류 (대/중/소)
  │  ├─ 점수 계산 (utility, trust, originality)
  │  └─ 한글 설명 생성
  ├─ 4. Pydantic으로 결과 검증 및 정규화
  ├─ 5. PostgreSQL DB에 저장 (AISite, AICategory, AITag)
  ├─ 6. Job 상태 업데이트: processing → success (completed_at 기록, site_id 저장)
  └─ 7. 결과 반환

Task 설정:
  - max_retries: 3
  - time_limit: 300s (hard)
  - soft_time_limit: 240s
  - Retry 간격: 60s × (시도차수) 지수 백오프
```

### LLM 배치 분석 (1회 LLM 호출로 다중 URL: analyze_website_batch)

```
Queue: analyze
  ↓
Celery Task: analyze_website_batch(job_ids[], urls[])
  ├─ 1. Job 상태 일괄 업데이트: pending → processing (started_at 기록)
  ├─ 2. LLM 분석 모드 분기
  │  ├─ 배치 분석 지원: analyzer.analyze_websites_batch(urls) 호출 (1회)
  │  └─ 개별 분석만 지원: [analyzer.analyze_website(url) for url in urls] (순차 호출)
  ├─ 3. 각 URL별 결과 검증 및 DB 저장
  │  ├─ 검증 실패 → 에러 기록, failed 카운트 증가
  │  └─ 검증 성공 → AISite/AICategory/AITag 저장, success 카운트 증가
  ├─ 4. 각 Job 상태 개별 업데이트 (success/failed)
  └─ 5. 요약 반환 {success, failed, total}

Task 설정:
  - max_retries: 3
  - time_limit: 600s (hard)
  - soft_time_limit: 540s
  - Retry 간격: 60s × (시도차수) 지수 백오프
```

### 병렬 배치 분석 (ThreadPoolExecutor: analyze_ai_tools_batch)

```
Background Task: analyze_ai_tools_batch(urls[], force_reanalyze)
  ├─ 1. 스킵 대상 사전 판별 (DB 스캔)
  │  ├─ 기존 분석이 성공 → 스킵
  │  └─ 기존 분석이 실패 또는 미분석 → pending 리스트에 추가
  ├─ 2. Job 레코드 일괄 생성 (pending URL당 1개)
  ├─ 3. ThreadPoolExecutor로 병렬 LLM 분석
  │  ├─ 워커 수: BATCH_CONCURRENCY (기본값: 5)
  │  ├─ 각 워커: 독립 DB 세션에서 _analyze_one(url, job_id) 실행
  │  └─ 완료: (url, job_id, result, error) 반환
  ├─ 4. 병렬 결과 수집
  │  ├─ 성공: success_map[job_id] = site_id
  │  └─ 실패: failure_map[job_id] = error
  ├─ 5. Job 상태 일괄 업데이트 (success/failed)
  ├─ 6. 전체 결과를 파일 하나에 저장 (write_batch)
  └─ 7. 요약 반환 {analyzed, skipped, failed, output_path}

Task 설정:
  - autoretry_for: () (자동 재시도 없음)
  - max_retries: 0 (수동 재시도만)
  - time_limit: 3600s (hard, 1시간)
  - soft_time_limit: 3300s (55분)

병렬 처리:
  - 최대 동시 워커: BATCH_CONCURRENCY (환경변수)
  - 각 워커: ThreadPoolExecutor 풀에서 독립 스레드 실행
  - DB 쓰기: 각 워커의 독립 DB 세션에서 처리
  - 결과 파일: 병렬 완료 후 단일 세션으로 한 번만 쓰기
```

### 규칙기반 분석 (CLASSIFIER_MODE=rule)

```
HTTP Request: POST /api/v1/rule/classify?url=...
  ↓
RuleAnalyzer.analyze_website(url)
  ├─ 1. PageFetcher로 URL fetch (requests → Playwright 폴백)
  ├─ 2. 8단계 파이프라인 실행
  │  ├─ step1: 페이지 수집 (homepage + 후보 페이지 병렬)
  │  ├─ step2: 신호 추출 (링크, 텍스트 분석)
  │  ├─ step3: AI 범위 분류 (strong/weak 키워드 매칭)
  │  ├─ step4: 분류 체계 (PRIMARY_CATEGORY_KEYWORDS)
  │  ├─ step5: 기준 평가 (5가지 품질 기준)
  │  ├─ step6: 점수화 및 상태 예측 (가중치 기반)
  │  ├─ step7: 상태 검토 및 리뷰 게이트
  │  └─ step8: 요약 생성
  ├─ 3. EvaluationResult → 분석 dict 변환
  └─ 4. 즉시 결과 반환 (DB 저장 옵션)
```

---

# Recommended Tech Stack

| Layer | Technology | 설명 |
|---|---|---|
| API | FastAPI | 비동기 API 서버 |
| Queue | Celery | 비동기 작업 큐 |
| Broker | Redis | 작업 큐 브로커 |
| LLM | Gemini API (url_context) | URL 직접 fetch + AI 사이트 분석 |
| Validation | Pydantic | 결과 검증 및 정규화 |
| Database | PostgreSQL | 결과 저장 |
| ORM | SQLAlchemy | 데이터베이스 접근 |
| Container | Docker | 배포 |

---

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────┐
│                    Spring Backend                             │
│                  (사용자 요청 처리)                            │
└────────────────────┬─────────────────────────────────────────┘
                     │ POST /analyze?url=...
                     ▼
┌──────────────────────────────────────────────────────────────┐
│                   FastAPI Worker                              │
│         ┌─────────────────────────────────────┐              │
│         │  API Layer                          │              │
│         │  - Request validation               │              │
│         │  - Job creation                     │              │
│         └─────────────────────────────────────┘              │
└────────────────────┬─────────────────────────────────────────┘
                     │ enqueue
                     ▼
┌──────────────────────────────────────────────────────────────┐
│                  Redis Queue (Celery)                         │
│            (비동기 작업 큐 및 상태 저장소)                      │
└────────────────────┬─────────────────────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────────────────────┐
│              Celery Worker Process                            │
│  ┌──────────────────────────────────────────────────────┐   │
│  │   Gemini API (url_context 툴)                        │   │
│  │  - URL 직접 fetch                                    │   │
│  │  - AI 사이트 판별                                    │   │
│  │  - 카테고리 분류                                     │   │
│  │  - 점수 계산                                         │   │
│  │  - 요약 생성                                         │   │
│  └──────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │   Result Normalizer (Pydantic)                       │   │
│  │  - JSON 검증                                         │   │
│  │  - Schema 정규화                                     │   │
│  └──────────────────────────────────────────────────────┘   │
└────────────────────┬─────────────────────────────────────────┘
                     │ 결과 저장
                     ▼
┌──────────────────────────────────────────────────────────────┐
│              PostgreSQL Database                              │
│  - AnalysisJob (작업 추적)                                   │
│  - AISite (분석 결과)                                        │
│  - AICategory / AITag (분류 및 태그)                         │
└──────────────────────────────────────────────────────────────┘
```

---

# Directory Structure

```text
sw-test/
├── src/
│   ├── __init__.py
│   ├── main.py                      # FastAPI 진입점
│   ├── api/
│   │   ├── __init__.py
│   │   ├── analyze_routes.py        # POST /analyze, /analyze/batch/* 라우트
│   │   ├── job_routes.py            # GET /jobs/{job_id} 라우트
│   │   ├── rule_routes.py           # POST /rule/classify 라우트
│   │   └── deps.py                  # API Key 인증 의존성
│   ├── ai/
│   │   ├── __init__.py
│   │   ├── prompts.py               # 프롬프트 상수 (SYSTEM_PROMPT, ANALYSIS_PROMPT)
│   │   ├── analyzer.py              # LLM 프로바이더 팩토리
│   │   ├── gemini_analyzer.py       # Gemini url_context 분석기
│   │   ├── detector.py              # AI 판별 및 DB 저장 로직
│   │   ├── mcp_tools.py             # (stub) 렌더링 도구 진입점
│   │   └── _playwright_renderer.py  # Playwright 렌더링 보존 (비활성)
│   ├── rule/                            # 규칙기반 분류기 (CLASSIFIER_MODE=rule)
│   │   ├── __init__.py
│   │   ├── analyzer.py                  # RuleAnalyzer 클래스 (analyze_website 메서드)
│   │   ├── pipeline.py                  # 8단계 파이프라인 함수 및 run_quality_pipeline()
│   │   ├── config.py                    # EvalConfig (파라미터 제어)
│   │   ├── models.py                    # EvaluationResult, CriterionResult, FetchResult, Evidence
│   │   ├── keywords.py                  # 키워드 상수 (AI_SITE_*, DOCS_*, POLICY_* 등)
│   │   ├── utils.py                     # URL/텍스트 처리 헬퍼 함수
│   │   ├── fetchers/
│   │   │   ├── __init__.py
│   │   │   └── page_fetcher.py          # PageFetcher (requests + Playwright 폴백)
│   │   └── classifiers/
│   │       ├── __init__.py
│   │       ├── ai_scope_classifier.py   # AiScopeClassifierMixin (AI 사이트 판정)
│   │       ├── taxonomy_classifier.py   # TaxonomyClassifierMixin (카테고리/태그 분류)
│   │       ├── criteria_evaluator.py    # CriteriaEvaluatorMixin + WeightedQualityEvaluator
│   │       ├── discovery_signals.py     # DiscoverySignalMixin (후보 URL 수집)
│   │       └── status_policy.py         # StatusPolicyMixin (상태 예측 및 리뷰 게이트)
│   ├── workers/
│   │   ├── __init__.py
│   │   ├── celery_app.py            # Celery 앱 초기화 (큐, 라우팅, 설정)
│   │   └── analyze_task.py          # 3개 분석 태스크
│   │       ├── analyze_website(job_id, url) — 단건 분석
│   │       ├── analyze_website_batch(job_ids[], urls[]) — 배치 분석
│   │       └── analyze_ai_tools_batch(urls[], force_reanalyze) — 병렬 분석
│   ├── db/
│   │   ├── __init__.py
│   │   ├── session.py               # SQLAlchemy 세션
│   │   └── models/
│   │       ├── base.py              # 모델 베이스 클래스
│   │       ├── ai_site.py
│   │       ├── ai_category.py
│   │       ├── ai_tag.py
│   │       └── analysis_job.py
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── job.py                   # 분석 작업 스키마
│   │   ├── site.py                  # AI 사이트 응답 스키마
│   │   └── rule.py                  # 규칙기반 분류 스키마
│   └── core/
│       ├── __init__.py
│       ├── config.py                # 환경 변수 설정
│       ├── enums.py                 # JobStatus 열거형
│       ├── exceptions.py             # 도메인 예외
│       ├── url.py                   # URL 정규화 및 판별
│       ├── util.py                  # 공통 유틸리티
│       ├── batch_file.py            # 배치 파일 URL 추출
│       └── result_writer.py         # 결과 JSON 파일 저장
├── tests/
│   ├── e2e/
│   ├── performance/
│   ├── unit/
│   └── rule/
├── alembic/                         # DB 마이그레이션
├── docs/                            # 문서
├── data/                            # 분석 대상 및 결과 파일
├── .env.example
├── ARCHITECTURE.md
├── README.md
├── CLAUDE.md
├── requirements.txt
├── docker-compose.yml
├── Dockerfile                       # API 서버 이미지
└── Dockerfile.worker                # Celery Worker 이미지
```

---

# Data Model

자세한 데이터베이스 스키마는 [DATA_MODEL.md](./docs/DATA_MODEL.md) 참조

---

# Timeout Strategy

## Task별 Timeout 설정

| Task | Hard Limit | Soft Limit | 용도 |
|---|---|---|---|
| `analyze_website` | 300s | 240s | 단건 분석 |
| `analyze_website_batch` | 600s | 540s | 배치 분석 (1회 LLM 호출) |
| `analyze_ai_tools_batch` | 3600s | 3300s | 병렬 배치 분석 (ThreadPoolExecutor) |

## Soft/Hard Limit 설명

- **Soft Limit**: Celery worker가 작업에 SIGTERM을 보낼 때간 (작업 정리 기회 제공)
- **Hard Limit**: 강제 종료까지의 최대 시간

## Gemini API Timeout

| 단계 | Timeout | 담당자 |
|---|---|---|
| url_context fetch | 내부 처리 | Gemini API |
| 분석 요청 전송 및 응답 | 기본값 (네트워크 레이턴시) | Gemini API |

## Retry 정책

| Task | Max Retries | Interval | 누적 대기 |
|---|---|---|---|
| `analyze_website` | 3회 | 60s × N (지수) | 60 + 120 + 180 = 360s |
| `analyze_website_batch` | 3회 | 60s × N (지수) | 60 + 120 + 180 = 360s |
| `analyze_ai_tools_batch` | 0회 | N/A | N/A |

---

# Failure Handling

실패도 정상 상태로 처리한다. 재시도 정책에 따라 자동 재시도되며, 최대 재시도 횟수 초과 시 최종 실패 상태로 기록된다.

## 실패 상태 응답

```json
{
  "job_id": "uuid",
  "status": "failed",
  "error_message": "상세 오류 메시지"
}
```

## 실패 유형

| 유형 | 재시도 | 처리 |
|---|---|---|
| Gemini API 오류 (429, 503 제외) | 3회 | 자동 재시도, 최종 실패 |
| Gemini API 503 (서버 오류) | 0회 | 즉시 실패 처리 |
| Gemini API 429 (Rate limit) | 0회 | 즉시 실패 처리 |
| url_context fetch 실패 (접근 불가 URL) | 0회 | 즉시 실패 처리 |
| Invalid domain | 0회 | 즉시 실패 처리 |
| LLM 응답 파싱 오류 | 3회 | 자동 재시도 |
| DB 저장 오류 | 3회 | 자동 재시도 |
| Timeout (soft_time_limit) | 1회 | Soft limit 초과 시 정리 후 재시도 |
| Timeout (hard_time_limit) | X | Hard limit 초과 시 즉시 강제 종료 |

## Retry Backoff

- **Interval**: `60s × (재시도차수)` 지수 백오프
  * 1차 재시도: 60s
  * 2차 재시도: 120s
  * 3차 재시도: 180s
  * 누적 대기: 360s (6분)

## 상태 전이

```
pending
  ↓
processing (started_at 기록)
  ├─ 성공 → success (completed_at, site_id 기록)
  ├─ 임시 실패 → pending (재시도 대기)
  └─ 최종 실패 → failed (completed_at, error_message 기록)
```

## 캐시 실패 처리

DB의 기존 분석이 실패 상태(`title`과 `description`이 모두 sentinel 값)인 경우:
- 재분석 실행 (캐시 무효화)
- 최대 재시도 초과 시 최종 실패로 기록

---

# Design Principles

## 1. Worker is Stateless

Worker는 상태를 내부 메모리에 저장하지 않는다.

모든 상태는:
- Redis (작업 큐, Job 상태)
- PostgreSQL DB (분석 결과)

를 통해 관리한다.

---

## 2. Queue First Architecture

모든 LLM 분석 작업은 Celery Queue를 통해 수행한다. 동기 처리는 규칙기반 분석(`/api/v1/rule/classify`)에만 허용한다.

```
API (즉시 Job ID 반환)
  ↓
Celery Queue (비동기 처리)
  ├─ analyze: Topic exchange (routing key: analyze.#)
  │  ├─ Task: analyze_website (단건)
  │  ├─ Task: analyze_website_batch (배치)
  │  └─ Task: analyze_ai_tools_batch (병렬 배치)
  ↓
DB (결과 저장)
```

**큐 설정**:
- 큐명: `analyze`
- Exchange: Topic (type: topic)
- Worker prefetch: 1 (순차 처리, 동시 작업 1개 제한)
- Serializer: JSON
- Task routes: `src.workers.analyze_task.*` → `analyze.default`

---

## 3. API-First Analysis

LLM 분석은 Gemini url_context 툴을 통해 수행한다. 로컬 브라우저 없이 API 호출만으로:
- URL fetch (Gemini가 수행)
- 콘텐츠 분석 (Gemini가 수행)
- 판별 및 분류 (Gemini가 수행)

Worker는 결과 정규화 및 저장만 수행한다.

**분석기 선택**:
- LLM 분석: `get_llm_analyzer()` 팩토리 함수로 환경설정(`LLM_PROVIDER`) 기반 분석기 선택
  * `LLM_PROVIDER=gemini` (기본): GeminiAnalyzer (url_context 툴 사용)
  * `LLM_PROVIDER=claude` (선택): ClaudeAnalyzer
- 규칙기반 분석: `/api/v1/rule/classify` 엔드포인트 전용, RuleAnalyzer 사용

---

## 4. Structured Output Validation

LLM 응답을 Pydantic으로 검증한다. 반드시:
- JSON schema 검증
- 타입 검증
- 필드 완성도 확인

를 수행한다.

**검증 프로세스**:
1. LLM 응답 파싱 (JSON 추출, 마크다운 코드블록 제거)
2. Pydantic 스키마 검증 (dataclass 또는 BaseModel)
3. 필수 필드 확인 (is_ai_tool, title, description, confidence, categories, tags, scores)
4. 타입/범위 검증 (score 1-10, confidence 0-1.0 등)
5. DB 저장 (검증 실패 시 AnalysisError 발생, 자동 재시도)

---

# Future Expansion

향후 확장 가능 기능:

- Playwright 렌더링 복원 (SPA 대응 필요 시 `_playwright_renderer.py` 활용)
- Multi-page crawling
- AI site ranking
- Embedding search
- Similar service detection
- Screenshot OCR
- Multi-modal analysis
- Product Hunt integration

---

# Result Storage Strategy

## 선택: Worker Direct DB Save

Worker가 분석 결과를 **DB에 직접 저장**하는 방식을 채택한다.

**이유:**
- 가장 간단한 구현
- 데이터 일관성 보장 (DB 단일 출처)
- Transaction 지원

**흐름:**
```
API: POST /analyze?url=...
    ↓
FastAPI 엔드포인트 (Request validation)
    ↓
Job ID 생성 & DB 저장 (status: "queued")
    ↓
Celery Task enqueue
    ↓
Celery Worker Processing (비동기)
    ├─ Gemini API 호출 (url_context 툴)
    │  ├─ URL fetch
    │  ├─ AI 판별 + 분류
    │  ├─ 점수 계산
    │  └─ 요약 생성
    └─ 결과 검증 (Pydantic)
    ↓
결과 DB에 직접 저장 (AISite table)
    ↓
Job 상태 업데이트 (status: "success")
```

---

## Performance Optimization Roadmap

**자세한 내용은 [Performance Roadmap](./PERFORMANCE_ROADMAP.md) 참고**

### 요약

| 단점 | Phase 1 | Phase 2 | Phase 3 | Phase 4 |
|------|--------|--------|--------|---------|
| **응답 느림** | - | ✅ (10배↑) | ✅ (즉시) | ✅ (즉시) |
| **DB 병목** | ✅ (인덱스) | ✅ (캐시) | ✅ (쓰기 분산) | ✅ (읽기 분산) |
| **쓰기 느림** | - | - | ✅ (5~10배↑) | ✅ (5~10배↑) |
| **구현 난도** | ⭐ | ⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ |
| **비용** | 낮음 | 낮음 | 중간 | 높음 |
