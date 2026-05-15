# AI Website Detection Worker

AI 웹사이트를 자동으로 분석하고 판별하는 비동기 워커 시스템이다. Gemini API의 url_context 툴로 URL을 직접 분석하여 AI 특성을 판별한 후 데이터베이스에 저장한다.

## 주요 기능

- **AI 웹사이트 자동 판별**: LLM(Gemini) 또는 규칙기반으로 웹사이트 분석
- **분류기 모드 선택**: `CLASSIFIER_MODE` 환경변수로 LLM / 규칙기반 전환
- **카테고리 및 태그**: 자동 분류 및 DB 저장 (3단계 카테고리 + 태그)
- **점수 시스템**: utility, trust, originality, total_score
- **에러 유형 세분화**: `ApiErrorKind` 기반 10가지 에러 분류 및 정책
- **접근 불가 TTL**: 7일 이내 재분석 스킵 자동 처리
- **비동기 처리**: Celery + Redis 기반 확장 가능한 작업 처리
- **배치 분석**: 파일 업로드 또는 서버 경로로 대량 URL 병렬 분석

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

### 환경 변수 설정

```bash
cp .env.example .env
```

`.env` 파일에서 설정할 항목:

| 변수 | 설명 | 기본값 |
|------|------|--------|
| `GEMINI_API_KEY` | Gemini API 키 (필수) | — |
| `API_KEY` | API 인증 키 (필수) | — |
| `GEMINI_MODEL` | Gemini 모델명 | `gemini-3.1-flash-lite` |
| `LLM_PROVIDER` | LLM 프로바이더 | `gemini` |
| `CLASSIFIER_MODE` | 분류기 모드 (`llm` / `rule`) | `llm` |
| `DATABASE_URL` | PostgreSQL 연결 문자열 | SQLite (개발용) |
| `REDIS_URL` | Redis 연결 문자열 | `redis://localhost:6379/0` |
| `BATCH_CONCURRENCY` | 배치 병렬 워커 수 | `5` |
| `LOG_LEVEL` | 로그 레벨 | `INFO` |

### Docker Compose (권장)

```bash
docker-compose up -d
docker-compose logs -f worker
docker-compose down
```

### 로컬 실행

```bash
uv sync
uv run uvicorn src.main:app --reload
uv run celery -A src.workers.celery_app worker --loglevel=info
```

## API 사용 예시

### 단건/배치 분석 요청

```bash
curl -X POST http://localhost:8000/api/v1/analyze \
  -H "Content-Type: application/json" \
  -H "x-api-key: your-api-key" \
  -d '{"urls": ["https://chatgpt.com"]}'
```

응답 후 `/api/v1/jobs/{job_id}`로 상태 확인: `pending` → `processing` → `success` / `failed`

### 파일 업로드 배치 분석

```bash
curl -X POST http://localhost:8000/api/v1/analyze/batch/upload \
  -H "x-api-key: your-api-key" \
  -F "file=@urls.json"
```

### 서버 경로 배치 분석

```bash
curl -X POST http://localhost:8000/api/v1/analyze/batch/file \
  -H "Content-Type: application/json" \
  -H "x-api-key: your-api-key" \
  -d '{"file_path": "data/ai-tools.json"}'
```

### 규칙기반 동기 분류

```bash
curl -X POST http://localhost:8000/api/v1/rule/classify \
  -H "Content-Type: application/json" \
  -H "x-api-key: your-api-key" \
  -d '{"url": "https://example.com"}'
```

## 테스트

```bash
uv run pytest -v
uv run pytest --cov=src --cov-report=html
```

## 데이터베이스 마이그레이션

```bash
uv run alembic revision --autogenerate -m "설명"
uv run alembic upgrade head
```

## 트러블슈팅

| 증상 | 해결 |
|------|------|
| Redis 연결 오류 | `docker-compose restart redis` |
| 마이그레이션 오류 | `docker-compose exec api alembic upgrade head` |
| LLM 분석 실패 | `GEMINI_API_KEY` 환경변수 확인 |

## 프로젝트 구조

```
sw-test/
├── src/
│   ├── api/         # REST API 엔드포인트
│   ├── ai/          # LLM 분석기 (Gemini)
│   ├── rule/        # 규칙기반 분류기
│   ├── workers/     # Celery 태스크
│   ├── db/          # SQLAlchemy ORM 모델
│   ├── schemas/     # Pydantic 스키마
│   └── core/        # 환경 설정 및 유틸리티
├── tests/
├── alembic/
├── docs/
└── data/
```

## 상세 문서

- [ARCHITECTURE.md](ARCHITECTURE.md) — 시스템 아키텍처
- [docs/CLASSIFIER_MODES.md](docs/CLASSIFIER_MODES.md) — 분류기 모드 및 에러 정책
- [docs/API_SPECIFICATION.md](docs/API_SPECIFICATION.md) — API 명세
- [docs/DATA_MODEL.md](docs/DATA_MODEL.md) — 데이터베이스 스키마

## 모니터링

- **Flower**: http://localhost:5555
- **API 문서**: http://localhost:8000/docs
- **헬스 체크**: http://localhost:8000/health
