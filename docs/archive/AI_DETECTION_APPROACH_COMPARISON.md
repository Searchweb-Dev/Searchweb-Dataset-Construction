# AI 사이트 판별 방식 비교: LLM vs 자체 모델

## 개요

AI 사이트 판별은 Worker의 핵심 기능이다.  
**LLM 기반 판별**과 **자체 모델(ML/규칙) 기반 판별** 두 가지 방식을 비교한다.

---

## 1. LLM 기반 판별 (현재 채택)

### 구조

```
Content Extraction
    ↓
Gemini/OpenAI API
    ↓
LLM 분석:
  - 문맥 이해 (semantic understanding)
  - 카테고리 분류
  - 신뢰도 판단
  - 요약 생성
    ↓
Pydantic 검증
    ↓
구조화된 결과
```

### 장점

| 항목 | 설명 |
|------|------|
| **정확도 높음** | 문맥과 의도를 이해하여 오탐지 낮음. 예: "AI를 설명하는 블로그"는 AI 도구 아님 |
| **신속한 개발** | 프롬프트 수정으로 즉시 개선 가능. 모델 학습 필요 없음 |
| **확장 용이** | 새로운 카테고리나 평가 기준 추가 간단 |
| **다양한 정보 처리** | 텍스트, 이미지(vision API), 비디오 메타데이터 등 다중 모달 지원 |
| **설명 가능성 높음** | LLM이 판단 이유를 함께 제시할 수 있음 |
| **최신 정보 반영** | LLM의 학습 데이터가 최신이므로 새로운 AI 도구도 빠르게 인식 |

### 단점

| 항목 | 설명 |
|------|------|
| **높은 비용** | API 호출당 0.01~0.10$ 소요. 월 10만 분석 시 1,000~10,000$ |
| **지연 시간** | API 응답 대기: 평균 5~15초 |
| **API 의존성** | OpenAI/Claude 서비스 다운 시 영향 |
| **레이트 제한** | API 호출 제한으로 인한 throttling 가능 |
| **일관성 변동** | 같은 입력에도 LLM 응답이 미묘하게 다를 수 있음 |
| **민감 정보** | 사이트 콘텐츠가 외부 API로 전송됨 (보안 고려) |

### 구현 예시

```python
from openai import OpenAI

async def analyze_with_llm(extracted_content: str, url: str) -> dict:
    """LLM으로 AI 사이트 판별"""
    
    client = OpenAI()
    
    prompt = f"""
    다음 웹사이트 콘텐츠를 분석하고 AI 서비스 여부를 판단해줘:
    
    URL: {url}
    Content: {extracted_content}
    
    다음 JSON 형식으로 응답해줘:
    {{
      "is_ai_tool": boolean,
      "category": "text-generation|image-generation|video-generation|speech|code|other",
      "confidence": 0-10,
      "utility": 1-10,
      "trust": 1-10,
      "originality": 1-10,
      "summary": "한국어 요약"
    }}
    """
    
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        response_format={"type": "json_object"}
    )
    
    return json.loads(response.choices[0].message.content)
```

---

## 2. 자체 모델 기반 판별

### 구조

```
Content Extraction
    ↓
특징 추출 (Feature Engineering)
  - 텍스트 특징: 키워드, 토픽
  - 메타데이터: 도메인, 기술 스택
  - 구조 특징: 가격 페이지, API 문서 존재 여부
    ↓
학습된 ML 모델
(분류 모델 또는 규칙 기반 엔진)
    ↓
예측 결과
```

### 세부 접근법

#### 2-1. 머신러닝 모델

```python
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction.text import TfidfVectorizer

# 학습
vectorizer = TfidfVectorizer(max_features=1000)
X_train = vectorizer.fit_transform(training_contents)
y_train = [1, 0, 1, 1, 0, ...]  # 1: AI tool, 0: non-AI

model = RandomForestClassifier(n_estimators=100)
model.fit(X_train, y_train)

# 예측
X_test = vectorizer.transform([new_content])
prediction = model.predict(X_test)[0]  # 0.92 confidence
```

**특징:**
- TF-IDF, Word2Vec, BERT 임베딩 등 가능
- 훈련 데이터 필요 (500~5000개)
- 예측 속도: <100ms

#### 2-2. 규칙 기반 엔진

```python
def classify_as_ai_tool(extracted_content: dict, url: str) -> dict:
    """규칙 기반 AI 사이트 판별"""
    
    score = 0
    indicators = []
    
    # 키워드 검사
    ai_keywords = ["AI", "machine learning", "deep learning", "neural", "algorithm"]
    content_lower = extracted_content["full_text"].lower()
    
    keyword_count = sum(1 for kw in ai_keywords if kw.lower() in content_lower)
    score += keyword_count * 2
    if keyword_count > 0:
        indicators.append("ai_keywords")
    
    # 가격 페이지 존재
    if "pricing" in extracted_content["pages"]:
        score += 3
        indicators.append("has_pricing")
    
    # API 문서
    if "api" in extracted_content["full_text"].lower():
        score += 2
        indicators.append("has_api")
    
    # 기술 스택
    tech_indicators = ["tensorflow", "pytorch", "transformers", "llama", "bert"]
    if any(tech in content_lower for tech in tech_indicators):
        score += 5
        indicators.append("ml_framework")
    
    # 도메인 화이트리스트
    if is_known_ai_domain(url):
        score += 10
        indicators.append("known_domain")
    
    is_ai_tool = score >= 5
    confidence = min(10, score / 2)
    
    return {
        "is_ai_tool": is_ai_tool,
        "confidence": confidence,
        "indicators": indicators,
        "score": score
    }
```

### 장점

| 항목 | 설명 |
|------|------|
| **비용 거의 없음** | 학습 후 로컬 모델 실행, API 비용 0$ |
| **빠른 응답** | <100ms, API 네트워크 지연 없음 |
| **독립적 운영** | 외부 서비스 의존성 없음, 24/7 안정적 |
| **데이터 프라이버시** | 민감한 콘텐츠가 외부로 나가지 않음 |
| **일관성 높음** | 같은 입력에 항상 같은 출력 (규칙/모델 고정) |
| **정교한 커스터마이징** | 도메인별 특성 반영 가능 |
| **모니터링 용이** | 모델 예측 과정을 명확히 추적 가능 |

### 단점

| 항목 | 설명 |
|------|------|
| **낮은 정확도** | 문맥 이해 부족. "AI 관련 뉴스" vs "AI 도구" 구분 어려움 |
| **긴 개발 시간** | 학습 데이터 수집/라벨링 (수주~수개월) |
| **유지보수 비용** | 새로운 카테고리나 트렌드에 대응하려면 재학습 필요 |
| **특징 엔지니어링** | 수작업으로 최적의 특징 선택해야 함 (시간 소모) |
| **과적합/과소적합** | 학습 데이터에 따라 성능 크게 변동 |
| **새로운 유형 인식 불가** | 학습 데이터에 없던 새로운 AI 도구 놓칠 수 있음 |

---

## 3. 하이브리드 접근 (LLM + 규칙)

### 구조

```
Content Extraction
    ↓
규칙 기반 빠른 판별
(확신 있으면 즉시 반환)
    ↓
├─ 확신도 높음 (>0.9) → 결과 반환 (LLM 스킵)
├─ 확신도 낮음 (<0.5) → 결과 반환 (non-AI로 판정)
└─ 모호함 (0.5~0.9) → LLM에 추가 분석 의뢰
    ↓
LLM 최종 판단 + 이유 설명
    ↓
결과 반환
```

### 구현

```python
async def hybrid_classify(extracted_content: dict, url: str) -> dict:
    """하이브리드: 규칙 먼저, 필요시 LLM"""
    
    # 1단계: 규칙 기반 빠른 판별
    rule_result = classify_as_ai_tool(extracted_content, url)
    
    if rule_result["confidence"] > 0.9:
        # 매우 확실 → 규칙 결과 사용
        return {**rule_result, "method": "rule_high_confidence"}
    
    if rule_result["confidence"] < 0.3:
        # 매우 낮음 → non-AI로 판정
        return {**rule_result, "method": "rule_low_confidence"}
    
    # 2단계: 모호한 경우 LLM 분석
    llm_result = await analyze_with_llm(extracted_content, url)
    
    # 3단계: 하이브리드 결과 (규칙 + LLM)
    return {
        "is_ai_tool": llm_result["is_ai_tool"],
        "category": llm_result["category"],
        "confidence": (rule_result["confidence"] + llm_result["confidence"]) / 2,
        "rule_score": rule_result["score"],
        "llm_reasoning": llm_result.get("reasoning"),
        "method": "hybrid"
    }
```

### 장점

| 항목 | 설명 |
|------|------|
| **낮은 API 비용** | 80% 경우만 규칙으로 처리, 20%만 LLM 사용 |
| **빠른 응답** | 대부분 <100ms, 모호한 경우만 5~15초 |
| **높은 정확도** | LLM의 문맥 이해 + 규칙의 빠른 판별 결합 |
| **독립성 유지** | 규칙만으로도 기본 기능 작동 |

### 단점

| 항목 | 설명 |
|------|------|
| **복잡한 구현** | 두 시스템 모두 유지보수 필요 |
| **일관성 문제** | 규칙/LLM 판별 결과 충돌 가능 |

---

## 4. 비교 요약표

| 항목 | LLM | 자체 모델 | 하이브리드 |
|------|-----|---------|----------|
| **정확도** | ⭐⭐⭐⭐⭐ (90%+) | ⭐⭐⭐ (75%~85%) | ⭐⭐⭐⭐ (85%~95%) |
| **비용/월** | 1,000~10,000$ | 0$ | 200~2,000$ |
| **응답 시간** | 5~15초 | <100ms | 100ms~15초 |
| **개발 시간** | 1~2주 | 2~3개월 | 3~5주 |
| **유지보수** | 프롬프트 조정 | 재학습 필요 | 양쪽 모두 |
| **API 의존성** | 높음 | 낮음 | 중간 |
| **설명 가능성** | 높음 | 낮음 | 높음 |
| **확장 용이성** | 높음 | 낮음 | 중간 |
| **프라이버시** | 낮음 (외부 전송) | 높음 | 중간 |

---

## 5. 프로젝트 맥락에서의 선택

### 선택: **LLM 기반 (Gemini/OpenAI)**

**이유:**

1. **MVP 우선** 
   - 학습 데이터 없이도 시작 가능
   - 1~2주 내 런칭 가능

2. **정확도 중요**
   - AI 사이트 판별은 정확도가 핵심
   - 오탐지(비AI를 AI로)는 사용자 신뢰 손상

3. **비용 수용**
   - 초기 단계: 월 수천$ 수준
   - 사용자 증가에 따라 최적화 검토 가능

4. **빠른 개선 사이클**
   - 프롬프트 수정으로 즉시 성능 개선
   - A/B 테스트 용이

### 향후 최적화 경로

```
Phase 1: LLM 기반 (지금)
  ↓
Phase 2 (3개월): 성능 데이터 수집
  - LLM 판별 결과에 사용자 피드백 축적
  - 오류 패턴 분석
  ↓
Phase 3 (6개월): 하이브리드로 전환
  - 규칙 기반 엔진 개발 (축적된 데이터로 학습)
  - LLM 비용 50~80% 감축
  ↓
Phase 4 (1년+): 자체 ML 모델
  - 충분한 라벨링된 데이터 확보 후
  - BERT 기반 분류 모델 개발
  - API 비용 거의 0으로
```

---

## 6. 구현 체크리스트

### LLM 방식 (Phase 1)

```
- [ ] OpenAI API 키 설정
- [ ] 프롬프트 작성 및 테스트
  - [ ] 분류 (AI vs Non-AI)
  - [ ] 카테고리 분류
  - [ ] 스코어 계산
- [ ] Pydantic 스키마 정의
- [ ] 에러 처리
  - [ ] API 타임아웃
  - [ ] Rate limit
  - [ ] Invalid response
- [ ] 비용 모니터링
- [ ] 성과 지표
  - [ ] 정확도 측정
  - [ ] 응답 시간
  - [ ] 실패율
```

### 하이브리드 전환 (Phase 3)

```
- [ ] 규칙 기반 엔진 개발
- [ ] LLM 피드백 축적 시스템
- [ ] A/B 테스트 구성
- [ ] 비용 vs 정확도 분석
- [ ] 점진적 마이그레이션
```

---

## 결론

**지금은 LLM 기반으로 시작하라.**

- 정확도가 높고 개발이 빠르다
- 사용자 만족도를 먼저 확보하는 것이 중요
- 데이터가 충분히 모인 후 (3~6개월) 하이브리드로 최적화

비용은 초기 관심사가 아니다. 사용자 확보 → 데이터 축적 → 최적화 순서로 진행하자.
