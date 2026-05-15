# Celery 필요성 & Playwright 렌더링 방식 비교

## Part 1: Celery 필요성 판단

### 1.1 Celery는 왜 필요한가?

Celery는 **비동기 작업 큐**다. 현재 아키텍처에서:

```
API 요청 → Job ID 즉시 반환 → 백그라운드 처리
```

이 패턴에서 필요하다.

---

### 1.2 Celery 필요 vs 불필요

#### **Celery가 필요한 경우**

```
✅ 비동기 처리 + Job 상태 추적 필요
✅ 여러 워커에서 병렬 처리
✅ Retry & Timeout 관리 필요
✅ 작업 스케줄링 필요
✅ 분석 시간이 5초 이상
```

**현재 프로젝트:**
- ✅ 비동기 처리 필요 (API 즉시 반환)
- ✅ 병렬 처리 필요 (여러 URL 동시 분석)
- ✅ Job 상태 추적 필요
- ✅ Timeout & Retry 필요
- ✅ 분석 시간: Playwright (30s) + LLM (10s) = 40s

**결론: Celery 필수**

---

#### **Celery 불필요한 경우**

```
❌ 동기 처리만 필요
❌ 단일 워커로 충분
❌ 작업이 <1초
❌ 상태 추적 불필요
```

예시: FastAPI만 사용하는 간단한 CRUD API

---

### 1.3 Celery 대체 방안

#### **대안 1: 동기 FastAPI (Celery 제거)**

```python
@app.post("/analyze")
async def analyze(url: str):
    """동기 처리 - Playwright + LLM"""
    
    # 렌더링 (30초)
    content = playwright.render(url)
    
    # LLM 분석 (10초)
    result = llm.analyze(content)
    
    # 클라이언트가 40초 대기
    return result
```

**문제점:**
- 클라이언트가 40초 대기 (타임아웃 위험)
- 동시 요청 시 순차 처리 (처리량 낮음)
- 한 URL 실패하면 전체 요청 실패

❌ **비추천**

---

#### **대안 2: FastAPI + 동기 백그라운드 (Celery 제거)**

```python
from fastapi import BackgroundTasks

@app.post("/analyze")
async def analyze(url: str, background_tasks: BackgroundTasks):
    """FastAPI 백그라운드 작업"""
    
    job_id = create_job(url)
    background_tasks.add_task(process_analysis, job_id, url)
    
    return {"job_id": job_id, "status": "queued"}

def process_analysis(job_id: str, url: str):
    content = playwright.render(url)
    result = llm.analyze(content)
    save_result(job_id, result)
```

**장점:**
- 간단한 구조
- Celery 의존성 제거
- 별도 Queue 불필요

**단점:**
- 프로세스 재시작 시 작업 손실 (Redis 없음)
- Retry 메커니즘 없음
- 워커 스케일 불가 (단일 프로세스)
- Job 상태 추적 불가

❌ **소규모 MVP에만 권장**

---

#### **대안 3: APScheduler (정기 실행 필요 시)**

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler()

@scheduler.scheduled_job('cron', hour=0)
def daily_analysis():
    """매일 0시에 특정 URL 분석"""
    urls = get_priority_urls()
    for url in urls:
        process_analysis(url)
```

**용도:**
- 정기적 업데이트
- 스케줄링 필요할 때만

**이것만으로는 부족**: 실시간 사용자 요청 처리 불가

---

### 1.4 최종 결론: Celery 필수

| 항목 | Celery | BackgroundTasks | 동기 |
|------|--------|----------------|------|
| **비동기 처리** | ✅ | ✅ | ❌ |
| **Job 상태 추적** | ✅ | ❌ | ❌ |
| **Retry & Timeout** | ✅ | ❌ | ❌ |
| **워커 스케일** | ✅ | ❌ | ❌ |
| **작업 영속성** | ✅ (Redis) | ❌ | ❌ |
| **구현 복잡도** | ⭐⭐⭐ | ⭐ | ✅ |
| **의존성** | Redis + Celery | 없음 | 없음 |

**선택: Celery 필수**
- 40초 분석 시간
- 병렬 처리 필요
- Job 상태 추적 필요
- 워커 스케일 필요

---

---

## Part 2: Playwright 렌더링 방식 비교

### 2.1 세 가지 방식

#### **방식 A: 로컬 Playwright (현재 추천)**

```python
from playwright.async_api import async_playwright

async def render_with_playwright(url: str) -> str:
    """로컬에서 Playwright로 렌더링"""
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        await page.goto(url, timeout=30000)
        await page.wait_for_load_state("networkidle")
        
        # 콘텐츠 추출
        content = await page.content()
        screenshot = await page.screenshot()
        
        await browser.close()
        
    return content, screenshot
```

**특징:**
- Worker 내부에서 직접 렌더링
- Playwright 프로세스를 로컬에서 관리
- Browser pool 사용으로 최적화

**장점:**
- 간단한 구조
- 개발 빠름
- 전체 제어 가능

**단점:**
- 메모리 사용 높음 (브라우저 인스턴스 유지)
- CPU 집약적 (JS 실행)
- 렌더링 시간 길다 (30초)
- 에러 처리 복잡

---

#### **방식 B: Playwright MCP (권장)**

**MCP (Model Context Protocol)**는 LLM이 직접 웹사이트를 분석할 수 있는 표준 프로토콜이다.

```python
# Worker: Playwright MCP 서버 구동
from mcp.server import Server
from mcp_playwright import PlaywrightServer

mcp_server = PlaywrightServer()

# 1. Worker에서 MCP 서버 시작
async def start_mcp_server():
    await mcp_server.start()

# 2. LLM이 MCP를 통해 렌더링 요청
# LLM의 지시:
# "https://example.com 의 콘텐츠를 분석해줘"
# ↓
# LLM이 내부적으로 MCP 호출:
# fetch_page("https://example.com")
# ↓
# Worker의 Playwright가 렌더링
# ↓
# 결과를 LLM에게 전달

# 3. Worker 코드는 매우 간단
async def analyze_with_mcp(url: str) -> dict:
    """MCP를 통해 Gemini가 직접 분석"""

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=GEMINI_API_KEY)

    response = client.models.generate_content(
        model="gemini-3.1-flash-lite",
        contents=f"""
        다음 URL을 분석해줘: {url}

        1. AI 서비스인지 판별
        2. 카테고리 분류
        3. 유용성 점수 (1-10)
        4. 신뢰도 점수 (1-10)
        5. 한 문장 요약

        응답은 JSON 형식으로.
        """,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            max_output_tokens=2000,
        ),
    )

    return parse_response(response)
```

**특징:**
- LLM이 자동으로 웹사이트 접근 및 분석
- Worker는 MCP 서버만 제공
- LLM이 tool use로 필요한 정보 추출

**장점:**
- 매우 간단한 구현
- LLM이 지능적으로 콘텐츠 선택
- 중복 분석 제거 (LLM이 스스로 판단)
- 에러 처리 자동

**단점:**
- MCP 서버 설정 필요
- 인터넷 접근 필요 (LLM 측에서)

---

#### **방식 C: 외부 렌더링 서비스 (Puppeteer/Playwright 클라우드)**

```python
import httpx

async def render_with_api(url: str) -> str:
    """외부 렌더링 서비스 사용"""
    
    async with httpx.AsyncClient() as client:
        # 예: Browserless, Apify 등
        response = await client.post(
            "https://api.browserless.io/chromium/render",
            json={
                "url": url,
                "html": True,  # HTML 콘텐츠
                "screenshot": True,
                "timeout": 30000
            },
            headers={"Authorization": f"Bearer {API_KEY}"}
        )
    
    result = response.json()
    return result["html"], result["screenshot"]
```

**특징:**
- 렌더링을 외부 서비스에 위임
- Worker는 API 호출만

**장점:**
- Worker 메모리 사용 최소
- 버그 처리 부담 적음
- 병렬 처리 높음

**단점:**
- API 비용 높음 (렌더링당 $0.01~0.05)
- 응답 지연 (네트워크 + 큐 대기)
- 제어 제한
- 또 다른 외부 의존성

❌ **비용 측면에서 비추천**

---

### 2.2 방식 A vs B 상세 비교

#### **성능 비교**

| 항목 | Playwright (A) | MCP (B) |
|------|----------------|--------|
| **렌더링 시간** | 30초 | 30초 (동일, LLM 측 포함) |
| **LLM 분석 시간** | 10초 | 0초 (LLM이 함께) |
| **전체 응답** | 40초 | 40초 |
| **메모리** | 500MB/인스턴스 | 200MB/인스턴스 |
| **CPU** | 높음 | 낮음 (LLM 측) |

**성능:** 동일 수준

---

#### **구현 복잡도 비교**

**방식 A (Playwright):**

```python
# Worker 코드 (복잡)
async def analyze(url: str):
    # 1. 렌더링
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto(url, timeout=30000)
        content = await page.content()
        await browser.close()
    
    # 2. 추출
    extracted = extract_content(content)
    
    # 3. LLM 분석
    result = await llm_analyze(extracted)
    
    # 4. 정규화
    normalized = normalize_result(result)
    
    return normalized
```

**라인 수:** ~100줄

---

**방식 B (MCP):**

```python
# Worker 코드 (매우 간단)
async def analyze(url: str):
    client = genai.Client(api_key=GEMINI_API_KEY)

    response = client.models.generate_content(
        model="gemini-3.1-flash-lite",
        contents=f"Analyze {url} as AI service",
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            max_output_tokens=2000,
        ),
    )

    return parse_response(response)

# + MCP 서버 설정 (한 번만)
async def start_mcp():
    from mcp_playwright import PlaywrightServer
    server = PlaywrightServer()
    await server.start()
```

**라인 수:** ~20줄 (MCP 서버 별도)

**복잡도:** MCP 훨씬 간단

---

#### **에러 처리 비교**

**방식 A (Playwright):**

```python
async def analyze_safe(url: str):
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(timeout=5000)
            page = await browser.new_page(timeout=10000)
            
            try:
                await page.goto(url, timeout=30000, 
                               wait_until="networkidle")
            except TimeoutError:
                # 렌더링 타임아웃
                pass
            except PlaywrightError:
                # 네비게이션 에러
                pass
            
            try:
                content = await page.content()
            except Exception as e:
                # 콘텐츠 추출 실패
                pass
            
            await browser.close()
    except Exception as e:
        # 브라우저 시작 실패
        pass
    
    # 부분적 콘텐츠로 분석?
    # 빈 결과 반환?
    # 직접 에러 처리 필요
```

**에러 종류:** 10가지 이상 수동 처리

---

**방식 B (MCP):**

```python
async def analyze_safe(url: str):
    try:
        response = client.messages.create(
            # LLM이 내부적으로 에러 처리
            # - 렌더링 실패
            # - 콘텐츠 파싱 실패
            # - MCP 호출 실패
            # 모두 자동으로 감지 및 대체
        )
        return parse_response(response)
    except Exception as e:
        # 최상위 Exception 처리만
        logger.error(f"Analysis failed: {e}")
        return {"error": str(e)}
```

**에러 종류:** 1가지만 처리

---

#### **유지보수 비용**

**방식 A:**
- Playwright 업데이트 추적
- 브라우저 호환성 관리
- 렌더링 에러 디버깅
- 성능 튜닝

❌ 지속적인 유지보수

**방식 B:**
- LLM 업데이트 자동
- MCP 표준만 준수
- 에러는 LLM이 처리
- 성능 최적화는 LLM 제공사가 담당

✅ 최소 유지보수

---

### 2.3 최종 추천: MCP 방식 (B)

| 항목 | Playwright (A) | MCP (B) |
|------|----------------|--------|
| **구현 복잡도** | ⭐⭐⭐⭐ 높음 | ⭐ 매우 낮음 |
| **유지보수** | 높음 | 낮음 |
| **에러 처리** | 복잡 | 자동 |
| **응답 시간** | 40초 | 40초 |
| **메모리** | 높음 | 낮음 |
| **의존성** | Playwright | google-genai SDK |
| **확장성** | 중간 | 높음 (LLM 개선) |

**선택: MCP 방식**

**이유:**
1. 구현이 매우 간단 (100줄 → 20줄)
2. 에러 처리 자동
3. 유지보수 비용 최소
4. 미래 LLM 개선이 자동 적용
5. 성능 동일

---

---

## Part 3: 최종 아키텍처 결정

### 최종 구성

```
┌─────────────────────┐
│   Spring Backend    │
│  (사용자 요청)      │
└──────────┬──────────┘
           │ POST /analyze?url=...
           ▼
┌─────────────────────┐
│   FastAPI Worker    │
│  - Job 생성         │
│  - Celery enqueue   │ ✅ Celery 필수
└──────────┬──────────┘
           │ enqueue
           ▼
┌─────────────────────┐
│  Celery Task Queue  │
│  (Redis Broker)     │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  Worker Process     │
│  ┌─────────────────┐│
│  │  MCP Server     ││ ✅ MCP 방식
│  │  (Playwright)   ││
│  └─────────────────┘│
│  ┌─────────────────┐│
│  │ Claude API      ││
│  │ (분석 수행)     ││
│  └─────────────────┘│
└──────────┬──────────┘
           │ 결과 저장
           ▼
┌─────────────────────┐
│   PostgreSQL DB     │
│  (AISite, Job)      │
└─────────────────────┘
```

### 기술 스택 (최종)

| Layer | Technology | 이유 |
|-------|-----------|------|
| API | FastAPI | 표준 |
| Queue | Celery + Redis | 비동기 처리 필수 |
| 렌더링 | MCP (Playwright) | 구현 간단, 유지보수 최소 |
| 분석 | Claude API | MCP 통합 |
| DB | PostgreSQL | 영속성 |
| ORM | SQLAlchemy | 표준 |

---

---

## Part 4: 구현 체크리스트

### Celery 설정

```
- [ ] Redis 설치 (Docker)
- [ ] Celery 설치
- [ ] Worker 설정
  - [ ] @celery_app.task 데코레이터
  - [ ] Retry 정책
  - [ ] Timeout 설정 (120초)
- [ ] 모니터링
  - [ ] Flower (웹 UI)
  - [ ] 작업 로깅
```

### MCP 설정

```
- [ ] Anthropic SDK 설치
- [ ] MCP Server 초기화
  - [ ] PlaywrightServer 구성
  - [ ] Tool 정의 (fetch_page, etc)
- [ ] Claude Integration
  - [ ] API 키 설정
  - [ ] Tool use 활성화
```

### 최종 검증

```
- [ ] 사용자 요청 → Job 생성 (즉시)
- [ ] Job ID 반환
- [ ] Celery Worker가 비동기로 처리
- [ ] Claude가 MCP로 렌더링 요청
- [ ] 결과 DB에 저장
- [ ] 사용자가 결과 조회
```

---

## 결론

1. **Celery: 필수** (비동기 처리 + Job 추적)
2. **MCP 방식: 권장** (간단한 구현 + 자동 유지보수)
