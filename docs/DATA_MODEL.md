# AI 사이트 데이터 모델

AI 웹사이트 분석 및 판별 결과를 저장하는 데이터베이스 스키마 정의.

---

## 테이블 구조

| 테이블 | 설명 | 주요 용도 |
|--------|------|----------|
| `ai_site` | AI 웹사이트 정보 | 분석 대상 및 결과 저장 |
| `analysis_job` | 분석 작업 기록 | 분석 진행 상황 추적 |
| `ai_category` | AI 카테고리 분류 | 다중 카테고리 할당 |
| `ai_tag` | AI 기능 태그 | 추가 메타데이터 |

---

## 공통 컬럼 (모든 테이블)

| 컬럼명 | 타입 | 설명 |
|--------|------|------|
| `created_at` | timestamptz | 생성 시각 (기본값: server_default=func.now()) |
| `updated_at` | timestamptz | 수정 시각 (기본값: server_default=func.now(), onupdate=func.now()) |
| `deleted_at` | datetime | 소프트 삭제 (NULL = 미삭제) |
| `created_by_member_id` | integer | 생성자 멤버 ID |
| `updated_by_member_id` | integer | 수정자 멤버 ID |
| `deleted_by_member_id` | integer | 삭제자 멤버 ID |

---

## 1. ai_site (AI 웹사이트)

분석된 AI 서비스의 기본 정보 및 판별/분류 결과를 저장.

| 컬럼명 | 타입 | NULL | Unique | Index | 설명 |
|--------|------|------|--------|-------|------|
| `site_id` | bigint | not null | PK | - | 기본 키 |
| `title` | varchar(255) | - | - | - | 웹사이트 제목 |
| `url` | varchar(2048) | not null | UK | idx_url | 웹사이트 URL |
| `analyzer` | varchar(50) | - | - | - | 분석에 사용된 도구 (`rule`, `gemini` 등) |
| `is_ai_tool` | boolean | not null | - | idx_is_ai_tool | AI 도구 여부 |
| `description` | text | - | - | - | 웹사이트 설명 |
| `score_utility` | integer | - | - | - | 유용성 점수 (1-10) |
| `score_trust` | integer | - | - | - | 신뢰도 점수 (1-10) |
| `score_originality` | integer | - | - | - | 독창성 점수 (1-10) |
| `total_score` | float | - | - | - | 종합 품질 점수 (0-100) |
| `hard_pass` | boolean | - | - | - | 필수 품질 기준 전체 통과 여부 |
| `review_required` | boolean | - | - | - | 수동 검수 필요 여부 |
| `last_analyzed_at` | datetime | - | - | idx_last_analyzed | 마지막 분석 완료 시각 (UTC) |
| `status` | varchar(20) | - | - | idx_status | 분석 상태 (ok / unreachable / blocked / failure). NULL은 미분류 |
| `unreachable_since` | datetime | - | - | - | 400 접근 불가 최초 감지 시각 (UTC). NULL이면 접근 가능 상태 |
| + common columns | | | | | created_at, updated_at, deleted_at, created_by_member_id, updated_by_member_id, deleted_by_member_id |

**품질 필드 계산 방식:**

| 분석기 | `total_score` | `hard_pass` | `review_required` |
|--------|--------------|-------------|-------------------|
| `rule` | 파이프라인 가중 점수 (0–100) | hard_criteria 모두 통과 여부 | 리뷰 게이트 판정 결과 |
| `gemini` | `(utility×0.4 + trust×0.3 + originality×0.3) × 10` | `is_ai_tool=true` 이고 `confidence ≥ 0.8` | `confidence < 0.7` 이거나 `(is_ai_tool이고 total_score < 60)` |

**캐시 신뢰 조건 (`rule/classify` 재분석 생략 기준):**

`analyzer == "rule"` 결과에 대해 아래 세 조건을 모두 충족하면 파이프라인을 재실행하지 않는다.

| 조건 | 기준값 |
|------|--------|
| `hard_pass` | `true` |
| `review_required` | `false` |
| `total_score` | `>= 60.0` |

---

## 2. analysis_job (분석 작업)

분석 작업의 진행 상황과 상세 정보를 기록. Spring Backend에서 조회용.

| 컬럼명 | 타입 | NULL | Unique | Index | 설명 |
|--------|------|------|--------|-------|------|
| `job_id` | uuid | not null | PK | - | 작업 ID |
| `site_id` | bigint | - | - | idx_site_id | AI Site 외래키 |
| `url` | varchar(2048) | not null | - | idx_url | 분석 대상 URL |
| `status` | varchar(20) | not null | - | idx_status | 작업 상태 (pending, processing, success, failed) |
| `error_message` | text | - | - | - | 오류 메시지 |
| `started_at` | timestamptz | - | - | - | 시작 시각 |
| `completed_at` | timestamptz | - | - | - | 완료 시각 |
| `retry_count` | integer | not null | - | - | 재시도 횟수 |
| `request_source` | varchar(50) | - | - | - | 요청 출처 (spring_backend 등) |
| + common columns | | | | | created_at, updated_at, deleted_at, created_by_member_id, updated_by_member_id, deleted_by_member_id |

---

## 3. ai_category (카테고리 분류)

AI 사이트의 카테고리 분류 (다대다 관계).

| 컬럼명 | 타입 | NULL | Unique | Index | 설명 |
|--------|------|------|--------|-------|------|
| `category_id` | bigint | not null | PK | - | 기본 키 |
| `site_id` | bigint | not null | - | idx_site_id | AI Site 외래키 |
| `level_1` | varchar(50) | not null | - | idx_level_1 | 모달리티 (text, image, video 등) |
| `level_2` | varchar(100) | not null | - | idx_level_2 | 작업 유형 (text-generation 등) |
| `level_3` | varchar(100) | - | - | - | 세부 기능 (선택사항) |
| `is_primary` | boolean | not null | - | - | 주요 카테고리 여부 |
| + common columns | | | | | created_at, updated_at, deleted_at, created_by_member_id, updated_by_member_id, deleted_by_member_id |

**제약조건:**
- `UK (site_id, level_1, level_2)` — `uq_ai_category_site_level` 제약으로 중복 방지

---

## 4. ai_tag (기능 태그)

AI 사이트의 추가 기능 태그 (다대다 관계).

| 컬럼명 | 타입 | NULL | Unique | Index | 설명 |
|--------|------|------|--------|-------|------|
| `tag_id` | bigint | not null | PK | - | 기본 키 |
| `site_id` | bigint | not null | - | idx_site_id | AI Site 외래키 |
| `tag_name` | varchar(50) | not null | - | idx_tag_name | 태그명 (sub_tasks로부터 생성) |
| + common columns | | | | | created_at, updated_at, deleted_at, created_by_member_id, updated_by_member_id, deleted_by_member_id |

**제약조건:**
- `UK (site_id, tag_name)` — `uq_ai_tag_site_name` 제약으로 중복 방지

---

## 관계도

```
ai_site (1)
├── (1:N) analysis_job
├── (1:N) ai_category
└── (1:N) ai_tag
```

---

## 인덱스 전략

| 테이블 | 인덱스 | 용도 |
|--------|--------|------|
| ai_site | idx_url | URL 중복 검사 |
| ai_site | idx_is_ai_tool | AI 도구 필터링 |
| ai_site | idx_last_analyzed | 최근 분석 날짜 조회 |
| analysis_job | idx_site_id | 작업 조회 |
| analysis_job | idx_status | 상태별 작업 조회 |
| analysis_job | idx_url | URL로 작업 검색 |
| ai_category | idx_site_id | 카테고리 조회 |
| ai_category | idx_level_1, idx_level_2 | 카테고리 필터링 |
| ai_tag | idx_site_id | 태그 조회 |
| ai_tag | idx_tag_name | 태그 검색 |
