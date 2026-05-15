# Token Optimization Strategy

Gemini API 호출 단계에서 비용과 토큰 사용을 최소화하는 방법들:

## 1. DB 캐싱 (가장 효과적: 중복 제거)

**적용 방법:**
- 이미 분석한 URL은 DB에서 바로 반환
- 동일 URL 재요청 시 API 호출 자체를 생략

**구현:**
```python
async def analyze_with_cache(url: str) -> dict:
    # 1. DB에서 이미 분석된 URL 확인
    cached = db.query(AISite).filter_by(url=url).first()
    if cached:
        return cached.to_dict()  # API 호출 안 함

    # 2. 새로운 URL만 Gemini 분석
    result = await analyze_with_gemini(url)
    db.add(AISite(**result))
    db.commit()
    return result
```

**효과:**
- 같은 URL 재분석 시 100% 절감 (API 호출 자체 제거)
- 월 1000개 중 30% 반복 분석이면: API 호출 300회 절감

---

## 2. 프롬프트 최적화 (30~40% 절감)

**현재 (과다):**
```
분석 대상 URL: {url}
다음을 판단해줘:
1. AI 서비스인가? (true/false)
...
```

**최적화:**
```
Analyze {url}: is_ai_tool, category (level_1, level_2, level_3, tags), scores (utility/trust/originality 1-10)
```

**효과:** 프롬프트 토큰 30~40% 감소

---

## 3. JSON 모드 활용 (응답 안정성 향상)

Gemini는 `response_mime_type="application/json"` 설정으로 JSON만 반환하도록 강제할 수 있습니다.
불필요한 마크다운·설명 텍스트 없이 순수 JSON만 반환되어 응답 토큰을 줄입니다.

**구현:**
```python
config=types.GenerateContentConfig(
    response_mime_type="application/json",
    max_output_tokens=500,
)
```

---

## 4. 페이지 콘텐츠 트리밍 (입력 토큰 절감)

웹페이지 전체 텍스트 대신 앞부분 4000자만 분석에 사용합니다.

```python
page_content[:4000]
```

---

## Gemini Free Tier 한도

- 정확한 RPM/RPD/TPM은 계정·등급에 따라 다름
- [AI Studio 비율 제한 페이지](https://aistudio.google.com/rate-limit)에서 확인

---

## 구현 우선순위

1. **즉시 (MVP)**: DB 캐싱 → 중복 URL 100% 절감
2. **1개월**: 프롬프트 최적화 → 추가 30~40% 절감
3. **필요시**: 콘텐츠 트리밍 강화 → 입력 토큰 추가 절감
