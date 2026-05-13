# Worker API 명세

Spring Backend와 통신하는 AI 사이트 분석 Worker의 REST API.

---

## 기본 정보

- **Base URL**: `http://localhost:8000/api/v1` (로컬) / 배포 환경별
- **인증**: API Key (header: `x-api-key`)
- **응답 형식**: JSON
- **타임아웃**: 30초 (API), 120초 (분석 작업)

---

## 1. 비동기 분석 요청 (단건·다건)

URL 목록을 전송하여 비동기 분석 작업을 시작합니다. 단건(1개)과 다건(최대 5개) 모두 지원합니다.

LLM으로 이미 분석된 URL은 기존 job을 즉시 반환합니다. `rule`로 분류된 URL은 LLM으로 재분석합니다.

### Endpoint
```
POST /analyze
```

### Request

**Header:**
```
x-api-key: {api_key}
Content-Type: application/json
```

**Body:**
```json
{
  "urls": [
    "https://www.example-ai-tool.com",
    "https://www.another-tool.com"
  ],
  "force_reanalyze": false
}
```

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `urls` | array | ✓ | 분석할 웹사이트 URL 목록 (1~5개) |
| `force_reanalyze` | boolean | - | 기존 결과 무시하고 재분석 (기본: false) |

### Response

**Status: 202 Accepted**

```json
[
  {
    "job_id": "550e8400-e29b-41d4-a716-446655440000",
    "url": "https://www.example-ai-tool.com",
    "status": "pending",
    "created_at": "2026-05-04T10:30:00Z",
    "started_at": null,
    "completed_at": null,
    "retry_count": 0,
    "error_message": null
  }
]
```

URL별로 job 객체가 담긴 배열을 반환합니다.

| 필드 | 타입 | 설명 |
|------|------|------|
| `job_id` | uuid | 분석 작업 ID (상태 조회용) |
| `url` | string | 분석 대상 URL |
| `status` | string | 작업 상태 (`pending`, `processing`, `success`, `failed`) |
| `created_at` | ISO 8601 | 작업 생성 시각 |
| `started_at` | ISO 8601 \| null | 작업 시작 시각 |
| `completed_at` | ISO 8601 \| null | 작업 완료 시각 |
| `retry_count` | integer | 재시도 횟수 |
| `error_message` | string \| null | 오류 메시지 |

### Errors

**Status: 422 Unprocessable Entity**
```json
{
  "detail": "URL 형식 오류 또는 urls 필드 누락"
}
```

---

## 2. 비동기 일괄 분석 — 파일 업로드

파일을 직접 업로드하여 URL 목록을 추출하고 일괄 비동기 분석합니다.

**지원 형식:**
- JSON: 문자열 배열 `["url1", ...]` 또는 객체 배열 `[{"link": "url1"}, ...]`
- 텍스트: 한 줄에 URL 하나

### Endpoint
```
POST /analyze/batch/upload
```

### Request

**Header:**
```
x-api-key: {api_key}
Content-Type: multipart/form-data
```

**Form:**

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `file` | file | ✓ | URL 목록 파일 (JSON 또는 텍스트, 최대 500개) |
| `force_reanalyze` | boolean | - | 기존 분석 결과 무시하고 재분석 (기본: false) |

### Response

**Status: 202 Accepted**

```json
{
  "total": 2,
  "accepted": 2,
  "message": "2건 분석을 백그라운드에서 시작했습니다. 완료 후 data/ 디렉토리에 결과 파일이 생성됩니다."
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `total` | integer | 파일에서 추출된 전체 URL 수 |
| `accepted` | integer | 분석 대상으로 접수된 URL 수 |
| `message` | string | 배치 작업 접수 안내 |

### Errors

**Status: 400 Bad Request**
```json
{
  "detail": "파일에서 유효한 URL을 찾을 수 없습니다."
}
```

---

## 3. 비동기 일괄 분석 — 서버 경로

서버에 이미 존재하는 파일 경로를 지정하여 일괄 비동기 분석합니다.

**지원 형식:** JSON, 텍스트 (위와 동일)

### Endpoint
```
POST /analyze/batch/file
```

### Request

**Header:**
```
x-api-key: {api_key}
Content-Type: application/json
```

**Body:**
```json
{
  "file_path": "data/ai-tools.json",
  "force_reanalyze": false
}
```

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `file_path` | string | ✓ | 서버 내 파일 경로 |
| `force_reanalyze` | boolean | - | 기존 분석 결과 무시하고 재분석 (기본: false) |

### Response

**Status: 202 Accepted**

```json
{
  "total": 150,
  "accepted": 150,
  "message": "150건 분석을 백그라운드에서 시작했습니다. 완료 후 data/ 디렉토리에 결과 파일이 생성됩니다."
}
```

### Errors

**Status: 404 Not Found**
```json
{
  "detail": "파일을 찾을 수 없습니다: data/not-found.json"
}
```

**Status: 400 Bad Request**
```json
{
  "detail": "파일에서 유효한 URL을 찾을 수 없습니다."
}
```

---

## 4. 규칙기반 동기 분류

규칙기반 파이프라인으로 단일 URL을 동기적으로 분류하고 결과를 데이터베이스에 저장합니다. Celery 없이 즉시 결과를 반환하므로 실시간 분류가 필요한 경우에 활용합니다.

### Endpoint
```
POST /rule/classify
```

### Request

**Header:**
```
x-api-key: {api_key}
Content-Type: application/json
```

**Body:**
```json
{
  "url": "https://www.example-ai-tool.com"
}
```

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `url` | string | ✓ | 분류할 웹사이트 URL |

### Response

**Status: 200 OK**

```json
{
  "site_id": 42,
  "input_url": "https://www.example-ai-tool.com",
  "normalized_url": "https://example-ai-tool.com",
  "predicted_status": "ai",
  "final_status": "ai",
  "passed_count": 6,
  "hard_pass": true,
  "total_score": 85.5,
  "score_breakdown": {
    "content_ai_markers": 25.0,
    "api_availability": 10.0,
    "social_proof": 15.0,
    "business_model": 20.0,
    "technical_indicators": 15.5
  },
  "review_required": false,
  "review_reasons": [],
  "criteria": {
    "ai_markers": {
      "name": "AI Markers",
      "passed": true,
      "reason": "Found AI-specific indicators in content",
      "confidence": 0.95,
      "evidence": [
        {
          "url": "https://www.example.com/page",
          "snippet": "AI-powered content generation",
          "label": "keyword_match"
        }
      ]
    },
    "api_availability": {
      "name": "API Availability",
      "passed": true,
      "reason": "Public API endpoint detected",
      "confidence": 0.87,
      "evidence": []
    }
  },
  "summary": "Strong AI service indicators. Passed 6/8 critical criteria.",
  "extracted": {
    "title": "Example AI Tool",
    "description": "AI-powered content generation platform",
    "features": ["API", "Free tier", "Multilingual"]
  }
}
```

**응답 객체 필드:**

| 필드 | 타입 | 설명 |
|------|------|------|
| `site_id` | integer | 저장된 사이트 ID |
| `input_url` | string | 입력받은 원본 URL |
| `normalized_url` | string | 정규화된 URL |
| `predicted_status` | string | 예측 분류 결과 (`ai`, `not-ai`, `uncertain`) |
| `final_status` | string | 최종 분류 결과 |
| `passed_count` | integer | 통과한 기준의 개수 |
| `hard_pass` | boolean | 하드 패스 여부 (강한 신호 감지) |
| `total_score` | float | 종합 점수 (0-100) |
| `score_breakdown` | object | 세부 점수 항목별 분석 |
| `review_required` | boolean | 수동 검토 필요 여부 |
| `review_reasons` | array | 검토가 필요한 사유 목록 |
| `criteria` | object | 각 기준(key)별 평가 결과 (name, passed, reason, confidence, evidence) |
| `summary` | string | 분류 결과의 한 문장 요약 |
| `extracted` | object | 추출된 메타데이터 (제목, 설명, 기능 등) |

### Errors

**Status: 422 Unprocessable Entity**
```json
{
  "detail": "Invalid URL format"
}
```

**Status: 403 Forbidden**
```json
{
  "detail": "Invalid API key"
}
```

**Status: 500 Internal Server Error**
```json
{
  "detail": "Classification pipeline failed or database save failed"
}
```

---

## 5. 분석 상태 조회

작업 ID로 분석 진행 상황 및 결과를 조회합니다.

### Endpoint
```
GET /jobs/{job_id}
```

### Request

**Header:**
```
x-api-key: {api_key}
```

### Response (진행 중)

**Status: 200 OK**

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "url": "https://www.example-ai-tool.com",
  "status": "processing",
  "created_at": "2026-05-04T10:30:00Z",
  "started_at": "2026-05-04T10:31:00Z",
  "completed_at": null,
  "retry_count": 0,
  "error_message": null,
  "result": null
}
```

### Response (완료)

**Status: 200 OK**

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "url": "https://www.example-ai-tool.com",
  "status": "success",
  "created_at": "2026-05-04T10:30:00Z",
  "started_at": "2026-05-04T10:31:00Z",
  "completed_at": "2026-05-04T10:35:00Z",
  "retry_count": 0,
  "error_message": null,
  "result": {
    "site_id": 42,
    "url": "https://www.example-ai-tool.com",
    "is_ai_tool": true,
    "title": "Example AI Tool",
    "description": "AI 기반 콘텐츠 생성 서비스",
    "categories": [
      {
        "level_1": "text",
        "level_2": "text-generation",
        "level_3": "blog-writing",
        "is_primary": true
      }
    ],
    "tags": [
      "api-available",
      "free-tier",
      "multilingual"
    ],
    "scores": {
      "utility": 8,
      "trust": 7,
      "originality": 9
    },
    "analyzer": "gemini",
    "last_analyzed_at": "2026-05-04T10:35:00Z"
  }
}
```

**result 객체 필드:**

| 필드 | 타입 | 설명 |
|------|------|------|
| `site_id` | integer | 사이트 ID |
| `url` | string | 분석 대상 URL |
| `is_ai_tool` | boolean | AI 도구 여부 |
| `title` | string \| null | 사이트 제목 |
| `description` | string \| null | 사이트 설명 |
| `categories` | array | 카테고리 분류 목록 |
| `tags` | array | 기능 태그 목록 |
| `scores` | object | 점수 (`utility`, `trust`, `originality`, 각 1-10) |
| `analyzer` | string \| null | 분석에 사용된 도구 (`gemini`) |
| `last_analyzed_at` | ISO 8601 \| null | 마지막 분석 시각 |

### Response (실패)

**Status: 200 OK**

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "url": "https://www.example-ai-tool.com",
  "status": "failed",
  "created_at": "2026-05-04T10:30:00Z",
  "started_at": "2026-05-04T10:31:00Z",
  "completed_at": "2026-05-04T10:35:00Z",
  "retry_count": 2,
  "error_message": "분석 실패",
  "result": null
}
```

### Errors

**Status: 400 Bad Request**
```json
{
  "detail": "Invalid job_id format"
}
```

**Status: 404 Not Found**
```json
{
  "detail": "Job not found"
}
```

---

## 비동기 분석 상태 값

| 상태 | 설명 |
|------|------|
| `pending` | 큐에 대기 중 |
| `processing` | 분석 진행 중 |
| `success` | 분석 완료 |
| `failed` | 분석 실패 |

---

## 에러 처리

### 재시도 정책

- 최대 3회 재시도
- 지수 백오프: 30초, 60초, 120초
- 반복 가능한 오류만 재시도 (네트워크, 타임아웃)

### 일반적인 오류

| 오류 | HTTP 상태 | 설명 |
|------|----------|------|
| Invalid URL | 400/422 | URL 형식 오류 |
| Invalid API Key | 403 | 잘못된 API 키 |
| Not Found | 404 | 리소스 미존재 |
| Rate Limited | 429 | 요청 한도 초과 |
| Server Error | 500 | 내부 서버 오류 |

---

## 예제

### cURL

#### 비동기 분석 요청
```bash
curl -X POST http://localhost:8000/api/v1/analyze \
  -H "x-api-key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"urls": ["https://www.example-ai-tool.com"]}'
```

#### 비동기 일괄 분석 — 파일 업로드
```bash
curl -X POST http://localhost:8000/api/v1/analyze/batch/upload \
  -H "x-api-key: your-api-key" \
  -F "file=@urls.json" \
  -F "force_reanalyze=false"
```

#### 비동기 일괄 분석 — 서버 경로
```bash
curl -X POST http://localhost:8000/api/v1/analyze/batch/file \
  -H "x-api-key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"file_path": "data/ai-tools.json", "force_reanalyze": false}'
```

#### 상태 조회
```bash
curl -X GET http://localhost:8000/api/v1/jobs/{job_id} \
  -H "x-api-key: your-api-key"
```

#### 규칙기반 동기 분류
```bash
curl -X POST http://localhost:8000/api/v1/rule/classify \
  -H "x-api-key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.example-ai-tool.com"}'
```

### Python (requests)

#### 비동기 분석 요청
```python
import requests

api_key = "your-api-key"
headers = {"X-API-Key": api_key}

# 분석 요청
response = requests.post(
    "http://localhost:8000/api/v1/analyze",
    headers=headers,
    json={"urls": ["https://www.example-ai-tool.com"]}
)
jobs = response.json()
job_id = jobs[0]["job_id"]

# 상태 조회
response = requests.get(
    f"http://localhost:8000/api/v1/jobs/{job_id}",
    headers=headers
)
print(response.json())
```

#### 비동기 일괄 분석 — 파일 업로드
```python
import requests

api_key = "your-api-key"
headers = {"X-API-Key": api_key}

with open("urls.json", "rb") as f:
    response = requests.post(
        "http://localhost:8000/api/v1/analyze/batch/upload",
        headers=headers,
        files={"file": ("urls.json", f, "application/json")},
        data={"force_reanalyze": "false"},
    )
print(response.json())
```

#### 비동기 일괄 분석 — 서버 경로
```python
import requests

api_key = "your-api-key"
headers = {"X-API-Key": api_key}

response = requests.post(
    "http://localhost:8000/api/v1/analyze/batch/file",
    headers=headers,
    json={"file_path": "data/ai-tools.json", "force_reanalyze": False},
)
print(response.json())
```

#### 규칙기반 동기 분류
```python
import requests

api_key = "your-api-key"
headers = {"X-API-Key": api_key}

# 동기 분류 요청
response = requests.post(
    "http://localhost:8000/api/v1/rule/classify",
    headers=headers,
    json={"url": "https://www.example-ai-tool.com"}
)
result = response.json()
print(f"Site ID: {result['site_id']}")
print(f"Predicted Status: {result['predicted_status']}")
print(f"Total Score: {result['total_score']}")
```
