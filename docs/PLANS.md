# AI 사이트 판별 개발 계획

Worker 시스템에서 AI 웹사이트를 분석하고 판별하는 로직 개발 계획.

---

## 프로젝트 규모

- **API 엔드포인트**: 2개 (분석 요청, 상태 조회)
- **DB 테이블**: 4개 (ai_site, analysis_job, ai_category, ai_tag)
- **비동기 작업**: Celery (Gemini API 호출)
- **개발 기간**: 4-6주

---

## Phase 1: 데이터베이스 및 기본 설계 (1주)

### 1.1 ORM 모델 정의 ✓
- `src/db/models/ai_site.py` — AISite
- `src/db/models/analysis_job.py` — AnalysisJob
- `src/db/models/ai_category.py` — AICategory
- `src/db/models/ai_tag.py` — AITag

**검증:**
```bash
uv run python -c "from src.db.models import *; print('All models imported')"
```

### 1.2 DB 마이그레이션
- Alembic 초기 마이그레이션 생성
- PostgreSQL 테이블 생성

**검증:**
```bash
alembic upgrade head
# DB에 4개 테이블 확인
```

### 1.3 Pydantic 스키마 정의
- `src/schemas/job.py` — AnalysisJobRequest, AnalysisJobResponse
- `src/schemas/site.py` — AISiteResponse

---

## Phase 2: FastAPI + 기본 API (1주)

### 2.1 FastAPI 라우트 구현
- `POST /api/v1/analyze` — 분석 요청 (Job 생성)
- `GET /api/v1/jobs/{job_id}` — 상태 조회

### 2.2 의존성 및 인증
- `src/api/deps.py` — API Key 검증

### 2.3 에러 처리
- 잘못된 URL 형식 감지
- 작업 상태별 응답 정의

**테스트:**
```bash
uv run pytest tests/api/ -v
```

---

## Phase 3: Gemini + MCP 통합 (2주) ✓

### 3.1 LLM 프로바이더 팩토리 ✓
- `src/ai/prompts.py` — 프롬프트 상수 (SYSTEM_PROMPT, ANALYSIS_PROMPT)
- `src/ai/analyzer.py` — LLM 프로바이더 팩토리 (Gemini 기본 / Claude 선택)
- `src/ai/gemini_analyzer.py` — Gemini API 호출 로직
  * 분석 프롬프트 생성
  * JSON 모드 응답 파싱

### 3.2 분석 로직 ✓
- `src/ai/detector.py` — AI 판별 로직
  * 웹사이트 분석 및 저장
  * 카테고리/태그 저장
  * 검증 로직

**테스트:**
```bash
uv run pytest tests/ai/ -v
```

---

## Phase 4: Celery 비동기 처리 (1주) ✓

### 4.1 Celery 앱 초기화 ✓
- `src/workers/celery_app.py` — Celery 설정
  * Redis 브로커 설정
  * 작업 큐 구성
  * 재시도 정책 (3회, 지수 백오프)

### 4.2 비동기 작업 정의 ✓
- `src/workers/analyze_task.py` — 분석 작업
  * 웹사이트 분석
  * Job 상태 관리
  * 에러 처리 및 로깅

### 4.3 작업 상태 관리 ✓
- Job 상태 업데이트 (pending → processing → success/failed)
- 분석 시간 측정

**테스트:**
```bash
# Worker 실행
uv run celery -A src.workers.celery_app worker --loglevel=info

# 작업 모니터링
uv run celery -A src.workers.celery_app events
```

---

## Phase 5: url_context 전환 및 안정화 (1주) ✓

### 5.1 Gemini url_context 전환 ✓
- Playwright 렌더링 제거 → Gemini url_context 툴로 URL 직접 fetch 분석
- `src/ai/gemini_analyzer.py` — url_context 기반 분석 로직으로 전면 재작성
  * `response_mime_type`과 url_context 툴 충돌 해결 (JSON 프롬프트 명시 방식으로 전환)
  * `max_output_tokens` 제한 제거 및 잘린 JSON 복구 로직 추가
  * 마크다운 코드블록 포함 응답 파싱 강화
  * `response.text is None` 예외 처리 추가

### 5.2 안정성 버그픽스 ✓
- `fix(detector)`: `ai_category` unique constraint 위반 — autoflush 타이밍 문제 해결
- `fix(detector)`: 카테고리/태그 DELETE 후 flush 추가로 UniqueViolation 재발 방지
- `fix(analyze_task)`: 분석 실패 데이터 캐시 히트 시 재분석하도록 수정
- `fix(url)`: `www.` 제거 및 trailing slash 정규화로 중복 URL 통합
- `fix(db/celery)`: DB 세션 중복 제거 및 Celery topic exchange 라우팅 수정
- `fix(docker)`: api/worker 서비스에 data 디렉토리 볼륨 마운트 추가

### 5.3 배포 준비 ✓
- `Dockerfile`: API 서버 이미지
- `Dockerfile.worker`: Celery Worker 이미지
- `docker-compose.yml`: 전체 스택 구성 (PostgreSQL, Redis, Flower 포함)
- `DEPLOYMENT.md`: 배포 및 운영 가이드

### 5.4 엔드투엔드 테스트 ✓
- `tests/e2e/test_analysis_flow.py` — API 통합 테스트 (9개)
  * 분석 요청 성공/실패
  * API Key 검증
  * Job 상태 조회
  * 강제 재분석
- 성능 벤치마크 (8개 테스트)
  * API 응답 시간 < 1초 ✓
  * 상태 조회 < 200ms ✓
  * 처리량 > 10 req/sec ✓

---

## Phase 6: 코드 품질 개선 및 리팩터링 ✓

### 6.1 프롬프트 통합 ✓
- `docs/PROMPTS.md` 제거 — `src/ai/prompts.py`로 단일화
- `CLAUDE_ANALYSIS_PROMPT` 제거 — `ANALYSIS_PROMPT` 하나로 통일 (LLM 프로바이더별 분리 불필요)
- 프롬프트 상수: `SYSTEM_PROMPT`, `ANALYSIS_PROMPT`
- categories 1개, tags 최대 3개로 출력 제한 강화

### 6.2 DB 모델 정리 ✓
- `src/db/models/ai_site.py` — `summary_ko` 필드 제거 (미사용 컬럼)
- `src/schemas/site.py` — `AISiteResponse`에서 `summary_ko` 제거
- Alembic 마이그레이션 추가: `a1b2c3d4e5f6_remove_summary_ko_from_ai_site`

### 6.3 Claude 프로바이더 최적화 ✓
- Claude 분석 시 `page_content` 전송 제거 — url만으로 분석 (불필요한 토큰 절감)
- `src/ai/analyzer.py` — Claude 호출 인터페이스 단순화

### 6.4 배치 처리 성능 최적화 ✓
- `perf(batch)`: 배치 분석 병렬화 구현
- DB 쿼리 최적화 (불필요한 조회 제거)

### 6.5 코드 리뷰 지적 사항 수정 ✓
- `fix(worker)`: 코드 리뷰 지적 사항 일괄 수정

---

## 개발 순서

1. **DB 스키마 정의** (Phase 1)
2. **API 엔드포인트** (Phase 2)
3. **Gemini + LLM 통합** (Phase 3)
4. **Celery 비동기 처리** (Phase 4)
5. **url_context 전환 및 안정화** (Phase 5)
6. **코드 품질 개선 및 리팩터링** (Phase 6)

---

## 기술 스택

| 항목 | 기술 | 버전 |
|------|------|------|
| 웹 프레임워크 | FastAPI | 0.136+ |
| ORM | SQLAlchemy | 2.0+ |
| 데이터 검증 | Pydantic | 2.0+ |
| 데이터베이스 | PostgreSQL | 14+ |
| 캐시/큐 | Redis | 7+ |
| 비동기 작업 | Celery | 5.6+ |
| AI API (기본) | Gemini | gemini-2.5-flash-lite |
| AI API (선택) | Claude | claude-sonnet-4-6 |

---

## 성공 기준

- ✓ API 응답 시간 < 1초 (Job 생성)
- ✓ 분석 완료 시간 < 60초
- ✓ Gemini free tier 활용으로 API 비용 절감
- ✓ 재시도 포함 성공률 > 95%
- ✓ 모든 E2E 테스트 통과

## 구현 현황 (2026-05-11)

### 완료된 것 ✓
- Phase 1: DB 모델, 마이그레이션, Pydantic 스키마 ✓
- Phase 2: FastAPI API 엔드포인트 ✓
- Phase 3: Gemini API + LLM 통합 ✓
- Phase 4: Celery 비동기 처리 ✓
- Phase 5: url_context 전환 및 안정화 ✓
- Phase 6: 코드 품질 개선 및 리팩터링 ✓

### 테스트 결과
- **E2E 테스트**: 9개 모두 통과 ✓
- **단위 테스트**: 22개 모두 통과 ✓
- **성능 테스트**: 8개 모두 통과 ✓
- **총 테스트**: 29개 통과, 0개 실패 ✓

### 배포 가능 상태
- Docker Compose 설정 완료
- 환경 설정 문서 작성 (DEPLOYMENT.md)
- Gemini free tier 활용으로 API 비용 절감
- API 응답 시간 < 1초 검증 ✓
- 처리량 > 10 req/sec 검증 ✓
