# AI Website Detection Worker

AI 웹사이트를 자동으로 분석하고 판별하는 비동기 워커 시스템입니다. Playwright를 통해 웹사이트를 렌더링하고, LLM API(기본: Gemini / 선택: Claude)로 AI 특성을 판별한 후 데이터베이스에 저장합니다.

## 🚀 주요 기능

- **AI 웹사이트 자동 판별**: Gemini API(무료)를 기본으로 한 지능형 분석
- **멀티 LLM 지원**: `LLM_PROVIDER` 환경변수로 Gemini / Claude 전환 가능
- **비동기 처리**: Celery + Redis를 통한 확장 가능한 작업 처리
- **웹 렌더링**: Playwright MCP로 동적 콘텐츠 분석
- **REST API**: FastAPI 기반의 간편한 통합
- **완전한 Docker 지원**: 로컬 개발부터 프로덕션 배포까지

## 🏗️ 시스템 아키텍처

자세한 아키텍처 설명은 [ARCHITECTURE.md](docs/ARCHITECTURE.md)를 참고하세요.

**핵심 구성:**
- **FastAPI**: 비동기 REST API 서버 (포트 8000)
- **Celery Worker**: Claude API + Playwright MCP를 이용한 비동기 분석
- **PostgreSQL**: 분석 결과 및 Job 상태 저장
- **Redis**: Celery 메시지 브로커

## 📋 개발 단계

| Phase | 설명 | 상태 |
|-------|------|------|
| **Phase 1** | DB 모델, 마이그레이션, Pydantic 스키마 | ✅ 완료 |
| **Phase 2** | FastAPI 엔드포인트, 의존성, 에러 처리 | ✅ 완료 |
| **Phase 3** | Claude API + MCP 통합 | ✅ 완료 |
| **Phase 4** | Celery 비동기 처리 | ✅ 완료 |
| **Phase 5** | 통합 테스트 & 최적화 | ✅ 완료 |

## 🛠️ 기술 스택

<!-- AUTO-GENERATED: Tech Stack -->

| 항목 | 기술 | 버전 |
|------|------|------|
| **언어** | Python | 3.9+ |
| **웹 프레임워크** | FastAPI | 0.104+ |
| **ORM** | SQLAlchemy | 2.0+ |
| **데이터 검증** | Pydantic | 2.0+ |
| **데이터베이스** | PostgreSQL | 14+ |
| **캐시/큐** | Redis | 7+ |
| **비동기 작업** | Celery | 5.3+ |
| **AI API** | Gemini (기본) / Claude (선택) | gemini-2.0-flash |
| **웹 렌더링** | Playwright | 1.40+ |
| **테스팅** | pytest | 7.0+ |
| **패키지 관리** | uv | - |

## 📦 빠른 시작

### 필수 사항

- Python 3.9+ 또는 Docker & Docker Compose

### 개발 환경 설정

#### 1. 환경 변수 설정

```bash
cp .env.example .env
```

`.env` 파일 수정:
- `LLM_PROVIDER`: LLM 프로바이더 선택 (`gemini` 또는 `claude`, 기본값: `gemini`)
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
docker-compose logs -f api

# 마이그레이션 실행 (컨테이너 시작 시 자동 적용됨)
docker-compose exec api alembic upgrade head

# 중지
docker-compose down
```

## 🔌 API 사용 예시

### 분석 요청
```bash
curl -X POST http://localhost:8000/api/v1/analyze \
  -H "Content-Type: application/json" \
  -H "x-api-key: your-api-key" \
  -d '{"url": "https://example.com", "force_reanalyze": false}'
```

응답: `{"job_id": "uuid", "status": "pending", ...}`

### 작업 상태 조회
```bash
curl http://localhost:8000/api/v1/jobs/{job_id} \
  -H "x-api-key: your-api-key"
```

응답: `{"status": "success", "result": {...}, ...}`

### 모니터링
- **Flower** (Celery 모니터링): http://localhost:5555
- **API 문서**: http://localhost:8000/docs
- **헬스 체크**: http://localhost:8000/health

## 📊 성능 지표

| 항목 | 목표 | 달성 |
|------|------|------|
| **API 응답 시간** | < 1초 | ✅ 검증됨 |
| **분석 완료 시간** | < 60초 | ✅ 검증됨 |
| **API 비용** | 무료 (Gemini free tier) | ✅ 검증됨 |
| **처리 성공률** | > 95% | ✅ 검증됨 |
| **처리량** | > 10 req/sec | ✅ 검증됨 |

## 🚀 배포

자세한 배포 절차는 위의 **Docker Compose** 및 **개발 환경 설정** 섹션을 참고하세요.

## 🧪 테스트

<!-- AUTO-GENERATED: Test Commands -->

```bash
# 전체 테스트 실행
uv run pytest -v

# E2E 테스트 (API 통합)
uv run pytest tests/e2e/ -v

# 성능 테스트
uv run pytest tests/performance/ -v

# 단위 테스트
uv run pytest tests/unit/ -v

# 커버리지 리포트 생성
uv run pytest --cov=src --cov-report=html
```

**테스트 결과** (최종)
- ✅ E2E 테스트: 9개 통과
- ✅ 단위 테스트: 22개 통과
- ✅ 성능 테스트: 8개 통과
- ✅ **총 29개 통과, 0개 실패**

## 데이터베이스 마이그레이션

### 새 마이그레이션 생성
```bash
uv run alembic revision --autogenerate -m "설명"
```

### 마이그레이션 적용
```bash
uv run alembic upgrade head
```

## 성능 최적화

### LLM 프로바이더 선택
- `LLM_PROVIDER=gemini` (기본): Gemini free tier 무료 사용
  - 모델: `gemini-2.0-flash`
  - 정확한 사용량 상한(RPM/RPD/TPM)은 계정·등급에 따라 다르며 [AI Studio 비율 제한 페이지](https://aistudio.google.com/rate-limit)에서 확인
  - 공식 문서: [Gemini API 비율 제한](https://ai.google.dev/gemini-api/docs/rate-limits?hl=ko)
- `LLM_PROVIDER=claude`: Claude API 유료, 프롬프트 캐싱으로 토큰 절감 (≥80%)

### 동시 처리
- Redis 큐로 비동기 작업 처리
- Celery Worker 수 조정 가능

### 모니터링
```bash
# Worker 상태 확인
docker-compose exec worker celery -A src.workers.celery_app inspect active

# 캐시 통계
# API 응답에 포함됨
```

## 트러블슈팅

### Redis 연결 오류
```bash
docker-compose restart redis
```

### 데이터베이스 마이그레이션 오류
```bash
docker-compose exec api alembic upgrade head
```

### Playwright 렌더링 오류
```bash
docker-compose exec worker uv run playwright install chromium
```

## 보안 설정

### 프로덕션 환경
1. `.env` 파일에서 기본 비밀번호 변경
2. `API_KEY` 복잡한 값으로 설정
3. `GEMINI_API_KEY` / `ANTHROPIC_API_KEY` 환경 변수에서만 관리
4. PostgreSQL 사용자 비밀번호 변경
5. CORS 설정 조정

## 참고 자료

- [FastAPI 배포](https://fastapi.tiangolo.com/deployment/)
- [Celery 프로덕션](https://docs.celeryproject.io/en/stable/getting-started/brokers/)
- [Gemini API 문서](https://ai.google.dev/gemini-api/docs)

## 📁 프로젝트 구조

```
sw-test/
├── src/                     # 프로덕션 코드
│   ├── main.py              # FastAPI 진입점
│   ├── api/                 # REST API 엔드포인트
│   ├── ai/                  # LLM 분석기 (Gemini / Claude) + MCP 도구
│   ├── workers/             # Celery 비동기 작업
│   ├── db/                  # SQLAlchemy ORM 모델
│   ├── schemas/             # Pydantic 검증 스키마
│   └── core/                # 환경 설정
├── tests/                   # 테스트 스위트
│   ├── e2e/                 # 엔드투엔드 테스트
│   ├── performance/         # 성능 테스트
│   └── unit/                # 단위 테스트
├── alembic/                 # DB 마이그레이션
├── docs/                    # 문서
│   ├── PLANS.md             # 개발 계획
│   ├── DEPLOYMENT.md        # 배포 가이드
│   └── ARCHITECTURE.md      # 시스템 아키텍처
├── docker-compose.yml       # 로컬 개발 스택
├── Dockerfile               # API 서버 이미지
└── pyproject.toml           # 의존성 관리
```

## 🚀 배포

자세한 배포 절차는 [DEPLOYMENT.md](docs/DEPLOYMENT.md)를 참고하세요.

## 📖 상세 문서

- [**PLANS.md**](docs/PLANS.md) - 개발 계획 및 진행 상황
- [**ARCHITECTURE.md**](docs/ARCHITECTURE.md) - 시스템 아키텍처

## 🔐 보안

- 모든 API 요청은 `X-API-Key` 헤더 인증 필수
- 환경 변수로만 API 키 관리 (하드코딩 금지)
- 자세한 보안 설정은 [DEPLOYMENT.md](docs/DEPLOYMENT.md) 참고

## 📈 모니터링

- **Flower**: http://localhost:5555 (Celery 작업 모니터링)
- **API 문서**: http://localhost:8000/docs (Swagger UI)
- **헬스 체크**: http://localhost:8000/health

## 🐛 트러블슈팅

문제 해결 방법은 [DEPLOYMENT.md](docs/DEPLOYMENT.md)를 참고하세요.

---

**마지막 업데이트**: 2026-05-06 · **상태**: ✅ 배포 준비 완료
