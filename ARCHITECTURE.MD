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
- Gemini/Claude를 통한 AI 사이트 판별 (판별, 분류, 점수화, 요약)
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

---

## Analysis Layer

`CLASSIFIER_MODE` 환경변수로 분석 방식을 선택한다 (기본값: `llm`).

### LLM 분석기 (CLASSIFIER_MODE=llm)

**기술:**
- Google Gemini API / Anthropic Claude API
- url_context Tool (Gemini 전용)

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
    model="gemini-2.5-flash-lite",
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
- 8단계 파이프라인 (신호 추출 → AI 범위 분류 → 분류 체계 → 기준 평가 → 점수화)

**역할:**

외부 API 호출 없이 로컬에서 웹사이트를 fetch하고 규칙기반으로 분석한다.

```
URL
 ↓
PageFetcher (requests → Playwright 폴백)
 ↓
8단계 파이프라인
  step1: 페이지 수집
  step2: 신호 추출
  step3: AI 범위 분류
  step4: 분류 체계 결정
  step5: 기준 평가
  step6: 점수화 및 상태 예측
  step7: 상태 검토 및 확정
  step8: 요약 생성
 ↓
EvaluationResult → 분석 dict
```

**장점:**

- API 비용 없음 → 대량 처리에 유리
- 오프라인 환경에서도 동작
- LLM API 의존성 없는 빠른 응답

---

## Processing Pipeline

```
Queue
  ↓
Celery Task: analyze_website(job_id, url)
  ├─ 1. DB에서 기존 분석 확인 (캐시)
  │  ├─ 있음 → 결과 반환 (API 호출 안 함)
  │  └─ 없음 → 2번 진행
  ├─ 2. Gemini API 호출 (url_context 툴)
  │  ├─ Gemini가 URL 직접 fetch
  │  ├─ AI 서비스 여부 판별
  │  ├─ 카테고리 분류 (대/중/소)
  │  ├─ 점수 계산 (utility, trust, originality)
  │  └─ 한글 설명 생성
  ├─ 3. Pydantic으로 결과 검증 및 정규화
  ├─ 4. PostgreSQL DB에 저장
  └─ 5. Job 상태 업데이트 (success)
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
│   │   ├── routes.py                # FastAPI 라우트
│   │   └── deps.py                  # 의존성 (DB 세션, 인증)
│   ├── ai/
│   │   ├── __init__.py
│   │   ├── analyzer.py              # LLM 프로바이더 팩토리
│   │   ├── gemini_analyzer.py       # Gemini url_context 분석기
│   │   ├── detector.py              # AI 판별 및 DB 저장 로직
│   │   ├── mcp_tools.py             # (stub) 렌더링 도구 진입점
│   │   └── _playwright_renderer.py  # Playwright 렌더링 보존 (비활성)
│   ├── rule/                            # 규칙기반 분류기 (CLASSIFIER_MODE=rule)
│   │   ├── analyzer.py                  # RuleAnalyzer (8단계 파이프라인)
│   │   ├── pipeline.py                  # run_quality_pipeline
│   │   ├── config.py                    # EvalConfig
│   │   ├── models.py                    # EvaluationResult, CriterionResult
│   │   ├── keywords.py                  # 키워드 상수
│   │   ├── utils.py                     # 헬퍼 함수
│   │   ├── fetchers/
│   │   │   └── page_fetcher.py          # HTTP fetch + Playwright 폴백
│   │   └── classifiers/
│   │       ├── ai_scope_classifier.py
│   │       ├── criteria_evaluator.py
│   │       ├── discovery_signals.py
│   │       ├── status_policy.py
│   │       └── taxonomy_classifier.py
│   ├── workers/
│   │   ├── __init__.py
│   │   ├── celery_app.py            # Celery 앱 초기화
│   │   └── analyze_task.py          # 분석 태스크
│   ├── db/
│   │   ├── __init__.py
│   │   ├── session.py               # SQLAlchemy 세션
│   │   └── models/
│   │       ├── ai_site.py
│   │       ├── ai_category.py
│   │       ├── ai_tag.py
│   │       └── analysis_job.py
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── job.py
│   │   └── site.py
│   └── core/
│       ├── __init__.py
│       ├── config.py                # 환경 변수 설정
│       ├── url.py                   # URL 유틸리티
│       └── result_writer.py         # 결과 파일 저장
├── tests/
│   ├── e2e/
│   ├── performance/
│   ├── unit/
│   └── rule/
├── alembic/                         # DB 마이그레이션
├── docs/                            # 문서
├── data/                            # 분석 대상 및 결과 파일
├── .env.example
├── ARCHITECTURE.MD
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

| Step | Timeout | 담당자 |
|---|---|---|
| Gemini url_context fetch | 내부 처리 | Gemini API |
| Gemini 분석 요청 | 60s | Gemini API |
| 결과 정규화 | 10s | Pydantic |
| **전체 Celery Task** | **120s** | Celery |

---

# Failure Handling

실패도 정상 상태로 처리한다.

```json
{
  "job_id": "uuid",
  "status": "failed",
  "reason": "timeout"
}
```

가능한 실패 유형:

- timeout
- url_context fetch 실패 (접근 불가 URL)
- invalid domain
- LLM 응답 파싱 오류
- DB 저장 오류

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

모든 분석 작업은 Celery Queue를 통해 수행한다.

동기 처리 금지.

```
API (즉시 Job ID 반환)
  ↓
Celery Queue (비동기 처리)
  ↓
DB (결과 저장)
```

---

## 3. API-First Analysis

LLM 분석은 Gemini url_context 툴을 통해 수행한다.

로컬 브라우저 없이 API 호출만으로:
- URL fetch (Gemini가 수행)
- 콘텐츠 분석 (Gemini가 수행)
- 판별 및 분류 (Gemini가 수행)

Worker는 결과 정규화 및 저장만 수행.

---

## 4. Structured Output Validation

Gemini 응답을 Pydantic으로 검증한다.

반드시:
- JSON schema 검증
- 타입 검증
- 필드 완성도 확인

를 수행한다.

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

# MVP Scope

초기 MVP 목표:

입력:
- URL 1개

출력:
- AI 사이트 여부
- 카테고리
- usefulness score
- summary

복잡한 랭킹/추천 시스템은 MVP 범위에서 제외한다.

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
