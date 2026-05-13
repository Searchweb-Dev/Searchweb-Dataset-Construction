# AI Website Detection Worker

AI 웹사이트를 자동으로 분석하고 판별하는 비동기 워커 시스템입니다. Gemini API의 url_context 툴로 URL을 직접 분석하여 AI 특성을 판별한 후 데이터베이스에 저장합니다.

## 주요 기능

- **AI 웹사이트 자동 판별**: LLM(Gemini) 또는 규칙기반으로 웹사이트 분석
  - LLM 분석: `/api/v1/analyze` (비동기, Celery 처리)
  - 규칙기반: `/api/v1/rule/classify` (동기, 즉시 반환)
- **분류기 모드 선택**: `CLASSIFIER_MODE` 환경변수로 LLM 분석(기본) / 규칙기반 분석 전환
- **카테고리 및 태그**: 자동 분류 및 DB 저장 (3단계 카테고리 + 3개 태그)
- **점수 시스템**: utility, trust, originality 점수 (1~10 범위)
- **규칙기반 평가 (CLASSIFIER_MODE=rule)**:
  - 5가지 품질 기준 평가 (usable_now, clear_function_desc, docs, policy, pricing)
  - 가중치 기반 0~100 점수화
  - 상태 판정: curated/incubating/rejected
  - 외부 API 비용 없음
- **비동기 처리**: Celery + Redis를 통한 확장 가능한 작업 처리
- **배치 분석**: 파일 업로드 또는 서버 경로로 대량 URL 분석 (병렬 처리)
- **REST API**: FastAPI 기반의 간편한 통합
- **완전한 Docker 지원**: 로컬 개발부터 프로덕션 배포까지

## 시스템 아키텍처

**핵심 구성:**
- **FastAPI**: 비동기 REST API 서버 (포트 8000)
- **Celery Worker**: Gemini API를 이용한 비동기 분석
- **PostgreSQL**: 분석 결과 및 Job 상태 저장
- **Redis**: Celery 메시지 브로커

## 개발 단계

| Phase | 설명 | 상태 |
|-------|------|------|
| **Phase 1** | DB 모델, 마이그레이션, Pydantic 스키마 | ✅ 완료 |
| **Phase 2** | FastAPI 엔드포인트, 의존성, 에러 처리 | ✅ 완료 |
| **Phase 3** | Gemini API 통합 (url_context 툴) | ✅ 완료 |
| **Phase 4** | Celery 비동기 처리 | ✅ 완료 |
| **Phase 5** | 통합 테스트 & 최적화 (url_context 전환) | ✅ 완료 |
| **Phase 6** | 코드 품질 개선 및 리팩터링 | ✅ 완료 |
| **Phase 7** | 규칙기반 분류기 통합 (src/rule/) | ✅ 완료 |
| **Phase 8** | 규칙기반 분류 API 및 DB 저장 연동 | ✅ 완료 |

## 기술 스택

| 항목 | 기술 | 버전 |
|------|------|------|
| **언어** | Python | 3.13+ |
| **웹 프레임워크** | FastAPI | 0.136+ |
| **ORM** | SQLAlchemy | 2.0+ |
| **데이터 검증** | Pydantic | 2.0+ |
| **데이터베이스** | PostgreSQL | 14+ |
| **캐시/큐** | Redis | 7+ |
| **비동기 작업** | Celery | 5.6+ |
| **AI API** | Gemini | gemini-3.1-flash-lite |
| **테스팅** | pytest | 7.0+ |
| **패키지 관리** | uv | - |
| **마이그레이션** | Alembic | - |

## 빠른 시작

### 필수 사항

- Python 3.13+ 또는 Docker & Docker Compose

### 개발 환경 설정

#### 1. 환경 변수 설정

```bash
cp .env.example .env
```

`.env` 파일 수정:
- `LLM_PROVIDER`: LLM 프로바이더 선택 (현재 `gemini`만 구현, 기본값: `gemini`)
- `LLM_PROVIDER`: LLM 프로바이더 (필수, 현재: `gemini`만 구현)
- `CLASSIFIER_MODE`: 분류기 모드 선택 (`llm` 또는 `rule`, 기본값: `llm`)
- `GEMINI_API_KEY`: Gemini API 키 (필수, [무료 발급](https://aistudio.google.com/apikey))
- `GEMINI_MODEL`: Gemini 모델명 (기본값: `gemini-3.1-flash-lite`)
- `API_KEY`: API 인증 키 (필수)
- `DATABASE_URL`: PostgreSQL 연결 문자열 (개발: SQLite 자동)
- `REDIS_URL`: Redis 연결 문자열 (기본값: `redis://localhost:6379/0`)
- `LOG_LEVEL`: 로그 레벨 (`DEBUG|INFO|WARNING|ERROR`, 기본값: `INFO`)
- `BATCH_CONCURRENCY`: 배치 분석 병렬 동시 실행 수 (기본값: `5`)
- `ALLOWED_ORIGINS`: CORS 허용 오리진 (기본값: `http://localhost:3000,http://localhost:8000`)

#### 2. 개발 서버 실행

```bash
# 의존성 설치
uv sync

# API 서버 실행 (포트 8000)
uv run uvicorn src.main:app --reload

# 다른 터미널에서 Celery Worker 실행
# - 큐: analyze (라우팅 키: analyze.#)
# - Worker prefetch: 1 (순차 처리)
uv run celery -A src.workers.celery_app worker --loglevel=info

# 다른 터미널에서 Celery Flower 실행 (모니터링, 포트 5555)
uv run celery -A src.workers.celery_app flower
```

### Docker Compose (권장)

```bash
# 모든 서비스 시작 (PostgreSQL, Redis, API, Worker, Flower)
docker-compose up -d

# 로그 확인
docker-compose logs -f worker

# 마이그레이션 실행 (컨테이너 시작 시 자동 적용됨)
docker-compose exec api alembic upgrade head

# 중지
docker-compose down
```

## API 사용 예시

### 비동기 분석 요청 (단건 또는 배치, 최대 5개 URL)

단건 분석:
```bash
curl -X POST http://localhost:8000/api/v1/analyze \
  -H "Content-Type: application/json" \
  -H "x-api-key: your-api-key" \
  -d '{"urls": ["https://chatgpt.com"]}'
```

응답:
```json
[
  {
    "job_id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "pending",
    "url": "https://chatgpt.com"
  }
]
```

분석 요청 후 `/api/v1/jobs/{job_id}`로 상태를 주기적으로 확인할 수 있습니다:
- `pending` — 큐에 대기 중
- `processing` — 현재 분석 중
- `success` — 분석 완료 (result 포함)
- `failed` — 분석 실패

### 비동기 일괄 분석 — 파일 업로드
```bash
curl -X POST http://localhost:8000/api/v1/analyze/batch/upload \
  -H "x-api-key: your-api-key" \
  -F "file=@urls.json"
```

### 비동기 일괄 분석 — 서버 경로
```bash
curl -X POST http://localhost:8000/api/v1/analyze/batch/file \
  -H "Content-Type: application/json" \
  -H "x-api-key: your-api-key" \
  -d '{"file_path": "data/ai-tools.json"}'
```

응답: `{"total": 150, "accepted": 150, "message": "150건 분석을 백그라운드에서 시작했습니다..."}`

### 작업 상태 조회
```bash
curl http://localhost:8000/api/v1/jobs/{job_id} \
  -H "x-api-key: your-api-key"
```

응답: `{"status": "success", "result": {...}, ...}`

### 규칙기반 동기 분류 (CLASSIFIER_MODE=rule만 사용)
```bash
curl -X POST http://localhost:8000/api/v1/rule/classify \
  -H "Content-Type: application/json" \
  -H "x-api-key: your-api-key" \
  -d '{"url": "https://example.com"}'
```

응답 예시:
```json
{
  "is_ai_tool": true,
  "title": "ChatGPT",
  "description": "AI 기반 대화형 어시스턴트",
  "confidence": 0.95,
  "categories": [
    {
      "level_1": "text",
      "level_2": "text-generation",
      "level_3": "",
      "is_primary": true
    }
  ],
  "tags": ["writing", "research"],
  "scores": {
    "utility": 9,
    "trust": 8,
    "originality": 5
  },
  "analyzer": "rule"
}
```

**주의**: 이 엔드포인트는 `CLASSIFIER_MODE=rule`로 설정했을 때만 사용 가능합니다.

### 모니터링
- **Flower** (Celery 모니터링): http://localhost:5555
- **API 문서**: http://localhost:8000/docs
- **헬스 체크**: http://localhost:8000/health

## 성능 지표

| 항목 | 목표 | 달성 |
|------|------|------|
| **API 응답 시간** | < 1초 | ✅ 검증됨 |
| **분석 완료 시간** | < 60초 | ✅ 검증됨 |
| **API 비용** | 무료 (Gemini free tier) | ✅ 검증됨 |
| **처리 성공률** | > 95% | ✅ 검증됨 |

## 테스트

```bash
# 전체 테스트 실행
uv run pytest -v

# E2E 테스트 (API 통합)
uv run pytest tests/e2e/ -v

# 단위 테스트
uv run pytest tests/unit/ -v

# 커버리지 리포트 생성
uv run pytest --cov=src --cov-report=html
```

## 데이터베이스 마이그레이션

```bash
# 새 마이그레이션 생성
uv run alembic revision --autogenerate -m "설명"

# 마이그레이션 적용
uv run alembic upgrade head
```

## LLM 프로바이더 선택

- `LLM_PROVIDER=gemini` (기본): Gemini API로 웹사이트 분석
  - 모델: `gemini-3.1-flash-lite`
  - [Gemini API 비율 제한](https://ai.google.dev/gemini-api/docs/rate-limits?hl=ko) 참조
  - Free tier 활용 가능

## 분류기 모드 및 작업 유형

### CLASSIFIER_MODE=llm (기본)

LLM API로 웹사이트 분석 (현재: Gemini url_context 툴)

#### 1. 단건 분석: analyze_website
- **엔드포인트**: `POST /api/v1/analyze`
- **처리**: Celery 큐 `analyze` → `analyze_website` 태스크
- **특징**:
  - DB 캐시 확인 (기존 분석 결과 있으면 LLM 호출 스킵)
  - Gemini API url_context 툴로 URL 직접 분석
  - time_limit: 300s, soft_time_limit: 240s
  - max_retries: 3회 (지수 백오프)

#### 2. 배치 분석 (1회 LLM 호출): analyze_website_batch
- **엔드포인트**: `POST /api/v1/analyze/batch/upload` 또는 `POST /api/v1/analyze/batch/file`
- **처리**: Celery 큐 `analyze` → `analyze_website_batch` 태스크
- **특징**:
  - 최대 5개 URL을 1회의 LLM 호출로 처리
  - 분석 모드: 분석기가 배치 지원 시 1회 호출, 아니면 순차 호출
  - time_limit: 600s, soft_time_limit: 540s
  - max_retries: 3회

#### 3. 병렬 배치 분석: analyze_ai_tools_batch
- **처리**: 백그라운드 작업 (API 엔드포인트 없음, Python 내부 호출)
- **특징**:
  - ThreadPoolExecutor로 병렬 LLM 분석 (동시 워커: BATCH_CONCURRENCY = 5)
  - 각 워커: 독립 DB 세션, 순차 LLM 호출
  - 최종 결과: 파일 하나에 저장
  - time_limit: 3600s (1시간)
  - max_retries: 0 (수동 재시도만)

**높은 정확도**: AI 특성 판별, 카테고리 분류
**API 비용**: Gemini free tier 사용 가능
**점수**: utility, trust, originality 생성

### CLASSIFIER_MODE=rule

규칙기반 8단계 파이프라인으로 오프라인 분석 (`src/rule/` 패키지)

#### 규칙기반 분류: rule_classify
- **엔드포인트**: `POST /api/v1/rule/classify`
- **처리**: 동기 분석 (API 응답에 결과 포함)
- **기술**: 키워드 매칭 + 휴리스틱 기반 신호 추출
- **특징**:
  - 외부 API 비용 없음 → 대량 처리에 유리
  - 오프라인 환경에서 동작 가능
  - requests + Playwright 폴백으로 페이지 수집
  - 5가지 품질 기준 평가 (usable_now, clear_function_desc, docs, policy, pricing)
  - 가중치 기반 점수화 (0~100)
  - 투명한 규칙 기반 판정 (상태: curated/incubating/rejected)

**주의**: CLASSIFIER_MODE의 값은 `llm` (기본) 또는 `rule` 중 하나여야 합니다. 단건 `/api/v1/analyze` 엔드포인트는 CLASSIFIER_MODE의 값과 무관하게 항상 LLM으로 분석합니다.


## 보안 설정

### 프로덕션 환경
1. `.env` 파일에서 기본 비밀번호 변경
2. `API_KEY` 복잡한 값으로 설정
3. `GEMINI_API_KEY` / `ANTHROPIC_API_KEY` 환경 변수에서만 관리
4. PostgreSQL 사용자 비밀번호 변경
5. CORS 설정 조정

## 트러블슈팅

### Redis 연결 오류
```bash
docker-compose restart redis
```

### 데이터베이스 마이그레이션 오류
```bash
docker-compose exec api alembic upgrade head
```

### LLM 분석 실패
- **Gemini**: `GEMINI_API_KEY` 환경변수 확인, 모델 기본값은 `gemini-3.1-flash-lite`
## 참고 자료

- [Gemini API 문서](https://ai.google.dev/gemini-api/docs)
- [FastAPI 배포](https://fastapi.tiangolo.com/deployment/)
- [Celery 프로덕션](https://docs.celeryproject.io/en/stable/getting-started/brokers/)

## 프로젝트 구조

```
sw-test/
├── src/                     # 프로덕션 코드
│   ├── main.py              # FastAPI 진입점
│   ├── api/                 # REST API 엔드포인트
│   │   ├── analyze_routes.py        # POST /analyze, /analyze/batch/*
│   │   ├── job_routes.py            # GET /jobs/{job_id}
│   │   ├── rule_routes.py           # POST /rule/classify
│   │   └── deps.py                  # API Key 인증 의존성
│   ├── ai/                  # LLM 분석기 (Gemini)
│   │   ├── prompts.py               # 프롬프트 상수
│   │   ├── analyzer.py              # LLM 프로바이더 팩토리
│   │   ├── gemini_analyzer.py       # Gemini url_context 분석기
│   │   └── detector.py              # AI 판별 및 DB 저장
│   ├── rule/                # 규칙기반 분류기 (CLASSIFIER_MODE=rule)
│   ├── workers/             # Celery 비동기 작업
│   ├── db/                  # SQLAlchemy ORM 모델
│   ├── schemas/             # Pydantic 검증 스키마
│   └── core/                # 환경 설정 및 유틸리티
├── tests/                   # 테스트 스위트
├── alembic/                 # DB 마이그레이션
├── docs/                    # 문서
├── data/                    # 분석 대상(ai-tools.json) 및 결과 파일
├── docker-compose.yml       # 로컬 개발 스택
├── Dockerfile               # API 서버 이미지
└── Dockerfile.worker        # Celery Worker 이미지
```

## 상세 문서

- [**PLANS.md**](docs/PLANS.md) - 개발 계획 및 진행 상황
- [**API_SPECIFICATION.md**](docs/API_SPECIFICATION.md) - API 명세
- [**DATA_MODEL.md**](docs/DATA_MODEL.md) - 데이터베이스 스키마

## 모니터링

- **Flower**: http://localhost:5555 (Celery 작업 모니터링)
- **API 문서**: http://localhost:8000/docs (Swagger UI)
- **헬스 체크**: http://localhost:8000/health

---

**마지막 업데이트**: 2026-05-14 · **상태**: ✅ Phase 8 완료, 배포 준비 완료
