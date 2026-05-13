# AI Website Detection Worker

AI 웹사이트를 자동으로 분석하고 판별하는 비동기 워커 시스템입니다. Gemini API의 url_context 툴로 URL을 직접 분석하여 AI 특성을 판별한 후 데이터베이스에 저장합니다.

## 주요 기능

- **AI 웹사이트 자동 판별**: LLM(Gemini/Claude) 또는 규칙기반으로 웹사이트 분석
- **멀티 LLM 지원**: `LLM_PROVIDER` 환경변수로 Gemini (기본) / Claude 전환 가능
- **분류기 모드 선택**: `CLASSIFIER_MODE` 환경변수로 LLM 분석(기본) / 규칙기반 분석 전환 가능
- **비동기 처리**: Celery + Redis를 통한 확장 가능한 작업 처리
- **경량 Worker**: API 호출만으로 분석 완료
- **REST API**: FastAPI 기반의 간편한 통합
- **완전한 Docker 지원**: 로컬 개발부터 프로덕션 배포까지

## 시스템 아키텍처

**핵심 구성:**
- **FastAPI**: 비동기 REST API 서버 (포트 8000)
- **Celery Worker**: Gemini API 또는 Claude API를 이용한 비동기 분석
- **PostgreSQL**: 분석 결과 및 Job 상태 저장
- **Redis**: Celery 메시지 브로커

## 개발 단계

| Phase | 설명 | 상태 |
|-------|------|------|
| **Phase 1** | DB 모델, 마이그레이션, Pydantic 스키마 | ✅ 완료 |
| **Phase 2** | FastAPI 엔드포인트, 의존성, 에러 처리 | ✅ 완료 |
| **Phase 3** | Gemini API 통합 | ✅ 완료 |
| **Phase 4** | Celery 비동기 처리 | ✅ 완료 |
| **Phase 5** | 통합 테스트 & 최적화 (url_context 전환) | ✅ 완료 |
| **Phase 6** | 코드 품질 개선 및 리팩터링 | ✅ 완료 |
| **Phase 7** | 규칙기반 URL 분류기 통합 (CLASSIFIER_MODE) | ✅ 완료 |
| **Phase 8** | 규칙기반 분류 API 및 DB 저장 연동 | ✅ 완료 |

## 기술 스택

| 항목 | 기술 | 버전 |
|------|------|------|
| **언어** | Python | 3.13 |
| **웹 프레임워크** | FastAPI | 0.136+ |
| **ORM** | SQLAlchemy | 2.0+ |
| **데이터 검증** | Pydantic | 2.0+ |
| **데이터베이스** | PostgreSQL | 14+ |
| **캐시/큐** | Redis | 7+ |
| **비동기 작업** | Celery | 5.6+ |
| **AI API** | Gemini (기본) / Claude (선택) | gemini-2.5-flash-lite |
| **테스팅** | pytest | 7.0+ |
| **패키지 관리** | uv | - |

## 빠른 시작

### 필수 사항

- Python 3.13+ 또는 Docker & Docker Compose

### 개발 환경 설정

#### 1. 환경 변수 설정

```bash
cp .env.example .env
```

`.env` 파일 수정:
- `LLM_PROVIDER`: LLM 프로바이더 선택 (`gemini` 또는 `claude`, 기본값: `gemini`)
- `CLASSIFIER_MODE`: 분류기 모드 선택 (`llm` 또는 `rule`, 기본값: `llm`)
- `GEMINI_API_KEY`: Gemini API 키 ([무료 발급](https://aistudio.google.com/apikey))
- `ANTHROPIC_API_KEY`: Claude API 키 (`LLM_PROVIDER=claude` 시 필요)
- `API_KEY`: API 인증 키
- `DATABASE_URL`: PostgreSQL 연결 문자열 (개발: SQLite 자동)
- `REDIS_URL`: Redis 연결 문자열

#### 2. 개발 서버 실행

```bash
# 의존성 설치
uv sync

# API 서버 실행
uv run uvicorn src.main:app --reload

# 다른 터미널에서 Celery Worker 실행
uv run celery -A src.workers.celery_app worker --loglevel=info

# 다른 터미널에서 Celery Flower 실행 (모니터링)
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

### 비동기 분석 요청 (단건·다건)
```bash
curl -X POST http://localhost:8000/api/v1/analyze \
  -H "Content-Type: application/json" \
  -H "x-api-key: your-api-key" \
  -d '{"urls": ["https://example.com", "https://example2.com"]}'
```

응답: `[{"job_id": "uuid", "status": "pending", ...}, ...]`

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

### 규칙기반 동기 분류
```bash
curl -X POST http://localhost:8000/api/v1/rule/classify \
  -H "Content-Type: application/json" \
  -H "x-api-key: your-api-key" \
  -d '{"url": "https://example.com"}'
```

응답: `{"site_id": 42, "predicted_status": "ai", "final_status": "ai", "total_score": 85.5, ...}`

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
  - 모델: `gemini-2.5-flash-lite`
  - [Gemini API 비율 제한](https://ai.google.dev/gemini-api/docs/rate-limits?hl=ko) 참조
  - Free tier 활용 가능
- `LLM_PROVIDER=claude`: Claude API로 웹사이트 분석
  - 모델: `claude-sonnet-4-6`
  - 프롬프트 캐싱으로 토큰 절감
  - API 키 필수 (유료)

## 분류기 모드 선택

- `CLASSIFIER_MODE=llm` (기본): LLM API로 웹사이트 분석 (Gemini 또는 Claude)
  - 비동기 작업: `/api/v1/analyze`로 요청하면 Celery가 백그라운드에서 처리
- `CLASSIFIER_MODE=rule`: 규칙기반 파이프라인으로 오프라인 분석
  - 외부 API 비용 없음 — 대량 처리에 유리
  - requests + Playwright 폴백으로 페이지 수집
  - 8단계 파이프라인: 신호 추출 → AI 범위 분류 → 분류 체계 → 기준 평가 → 점수화
  - 동기 분류: `/api/v1/rule/classify`로 요청하면 즉시 규칙기반 분류 결과를 반환


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
- **Gemini**: `GEMINI_API_KEY` 환경변수 확인, 모델 기본값은 `gemini-2.5-flash-lite`
- **Claude**: `ANTHROPIC_API_KEY` 환경변수 확인, 모델은 `claude-sonnet-4-6`

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
│   │   ├── analyze_routes.py        # POST /analyze, POST /analyze/batch
│   │   ├── job_routes.py            # GET /jobs/{job_id}
│   │   ├── rule_routes.py           # POST /rule/classify
│   │   └── deps.py                  # API Key 인증 의존성
│   ├── ai/                  # LLM 분석기 (Gemini / Claude)
│   │   ├── prompts.py               # 프롬프트 상수 (SYSTEM_PROMPT, ANALYSIS_PROMPT)
│   │   ├── analyzer.py              # LLM 프로바이더 팩토리
│   │   ├── gemini_analyzer.py       # Gemini 분석기
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

**마지막 업데이트**: 2026-05-12 · **상태**: ✅ 배포 준비 완료
