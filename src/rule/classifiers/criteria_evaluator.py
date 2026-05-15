"""
품질 기준(criteria) 평가, 코어 evaluator, 가중치 기반 상태 판정을 담당하는 모듈.
"""

from __future__ import annotations

import re
import logging
from typing import Any, Callable, Iterable

from src.rule.config import EvalConfig
from src.rule.classifiers.ai_scope_classifier import AiScopeClassifierMixin
from src.rule.classifiers.discovery_signals import DiscoverySignalMixin
from src.rule.keywords import ACTION_KEYWORDS, DOCS_TEXT, GENERIC_MARKETING_PHRASES, POLICY_TEXT, TASK_NOUNS
from src.rule.fetchers.page_fetcher import PageFetcher
from src.rule.models import ClearDescriptionLLM, CriterionResult, EvaluationResult, Evidence, FetchResult
from src.rule.classifiers.status_policy import StatusPolicyMixin
from src.rule.classifiers.taxonomy_classifier import TaxonomyClassifierMixin
from src.rule.utils import has_usable_url_hint, is_same_domain, keyword_hit, lower, normalize_url, snippet, split_sentences

logger = logging.getLogger(__name__)

PipelineStep = Callable[[Any, dict[str, object]], None]


class CriteriaEvaluatorMixin:
    """품질 criteria 평가 및 weighted 점수 계산 기능을 제공하는 믹스인."""

    def _build_criteria(
        self,
        homepage: FetchResult,
        all_pages: dict[str, FetchResult],
        extracted: dict[str, object],
    ) -> dict[str, CriterionResult]:
        """5개 품질 지표 결과를 생성해 dict로 반환한다."""
        ai_scope = extracted.get("ai_scope", {})
        if ai_scope and str(ai_scope.get("scope_decision", "")).lower() == "non_ai":
            return self._build_non_ai_scope_criteria(homepage, str(ai_scope.get("reason", "")))
        if ai_scope and "scope_decision" not in ai_scope and not bool(ai_scope.get("is_ai_site", True)):
            return self._build_non_ai_scope_criteria(homepage, str(ai_scope.get("reason", "")))
        taxonomy = extracted.get("taxonomy", {})
        if (not ai_scope) and taxonomy and not bool(taxonomy.get("is_ai_site", True)):
            return self._build_non_ai_scope_criteria(homepage, str(taxonomy.get("ai_site_reason", "")))

        domain = (re.sub(r"^https?://", "", homepage.final_url or homepage.url)).split("/")[0]

        usable_now = self._eval_usable_now(homepage, all_pages, extracted)
        logger.info("[%s] Criteria(usable_now): passed=%s (conf=%.2f)", domain, usable_now.passed, usable_now.confidence)

        clear_desc = self._eval_clear_function_desc(homepage, all_pages, extracted)
        logger.info("[%s] Criteria(clear_desc): passed=%s (conf=%.2f)", domain, clear_desc.passed, clear_desc.confidence)

        pricing = self._eval_pricing(homepage, all_pages, extracted)
        logger.info("[%s] Criteria(pricing): passed=%s", domain, pricing.passed)

        docs = self._eval_docs(homepage, all_pages, extracted)
        logger.info("[%s] Criteria(docs): passed=%s", domain, docs.passed)

        policy = self._eval_policy(homepage, all_pages, extracted)
        logger.info("[%s] Criteria(policy): passed=%s", domain, policy.passed)

        return {
            "usable_now": usable_now,
            "clear_function_desc": clear_desc,
            "has_pricing": pricing,
            "has_docs_or_help": docs,
            "has_privacy_or_data_policy": policy,
        }

    def _build_non_ai_scope_criteria(self, homepage: FetchResult, detail_reason: str) -> dict[str, CriterionResult]:
        """AI 사이트가 아닌 경우 평가 제외용 criterion 결과를 생성한다."""
        reason = "AI 사이트 판별 게이트에서 제외됨"
        if detail_reason:
            reason = f"{reason}: {detail_reason}"
        evidence = [Evidence(homepage.final_url, snippet(homepage.meta_description or homepage.text or homepage.title), "non_ai_scope_gate")]
        names = (
            "usable_now",
            "clear_function_desc",
            "has_pricing",
            "has_docs_or_help",
            "has_privacy_or_data_policy",
        )
        return {
            name: CriterionResult(
                name=name,
                passed=False,
                reason=reason,
                confidence=1.0,
                evidence=list(evidence),
            )
            for name in names
        }

    def _sample_ok_page_urls(self, all_pages: dict[str, FetchResult], limit: int = 3) -> str:
        """정상 수집된 페이지 URL 샘플 문자열을 반환한다."""
        ok_urls = [p.final_url for p in all_pages.values() if p.ok and p.final_url]
        if not ok_urls:
            return "-"
        sample = ok_urls[:limit]
        if len(ok_urls) > limit:
            return f"{', '.join(sample)} 외 {len(ok_urls) - limit}개"
        return ", ".join(sample)

    def _eval_usable_now(self, homepage: FetchResult, all_pages: dict[str, FetchResult], extracted: dict[str, object]) -> CriterionResult:
        """즉시 사용 가능 경로(가입/로그인/설치/실행) 존재 여부를 평가한다."""
        from src.rule.keywords import NEGATIVE_USE_TEXT, POSITIVE_USE_TEXT

        evidence: list[Evidence] = []
        usable_pages = [p for p in all_pages.values() if p.ok]
        if homepage.ok:
            blob = lower(" ".join([homepage.title, homepage.meta_description, homepage.text[:3000]]))
            link_blob = lower(" ".join([f"{t} {u}" for t, u in homepage.links]))
        else:
            if not usable_pages:
                if bool(extracted.get("anti_bot_blocked")):
                    return CriterionResult(name="usable_now", passed=False, reason="anti-bot/challenge 페이지로 인해 홈페이지 접근 실패", confidence=1.0, evidence=[])
                return CriterionResult(name="usable_now", passed=False, reason=f"홈페이지 접근 실패(status={homepage.status_code}, error={homepage.error})", confidence=1.0, evidence=[])
            blob = lower(" ".join(" ".join([p.title, p.meta_description, p.text[:3000]]) for p in usable_pages))
            link_blob = lower(" ".join(" ".join([f"{t} {u}" for t, u in p.links[:100]]) for p in usable_pages))
            evidence.append(Evidence(usable_pages[0].final_url, snippet(usable_pages[0].meta_description or usable_pages[0].text), "fallback_accessible_page"))

        positive_text = keyword_hit(blob, POSITIVE_USE_TEXT) or keyword_hit(link_blob, POSITIVE_USE_TEXT)
        positive_url_hint = False
        for p in usable_pages:
            for link_text, href in p.links[:120]:
                if not href:
                    continue
                if not is_same_domain(homepage.final_url, href):
                    continue
                if has_usable_url_hint(href):
                    positive_url_hint = True
                    evidence.append(Evidence(href, snippet(f"{link_text} {href}"), "positive_use_url_hint"))
                    break
            if positive_url_hint:
                break

        positive = positive_text or positive_url_hint
        negative = keyword_hit(blob, NEGATIVE_USE_TEXT) or keyword_hit(link_blob, NEGATIVE_USE_TEXT)
        oss_install_ok = False
        for p in all_pages.values():
            if not p.ok:
                continue
            docs_pages = extracted.get("docs_pages", [])
            if p.final_url in (docs_pages if isinstance(docs_pages, list) else []):
                doc_blob = lower(" ".join([p.title, p.meta_description, p.text[:3000]]))
                if any(k in doc_blob for k in ["install", "quickstart", "getting started", "docker", "run locally", "self-hosted", "설치", "시작하기"]):
                    oss_install_ok = True
                    evidence.append(Evidence(p.final_url, snippet(p.text), "docs_install_path"))
                    break

        if positive_text:
            evidence.append(Evidence(homepage.final_url, snippet(homepage.text), "positive_use_text_signal"))
        if negative and not positive and not oss_install_ok:
            return CriterionResult(name="usable_now", passed=False, reason="waitlist/coming soon/early access 신호만 있고 즉시 사용 경로가 없음", confidence=0.95, evidence=evidence or [Evidence(homepage.final_url, snippet(homepage.text), "negative_use_signal")])
        if positive or oss_install_ok:
            reason = "즉시 사용/가입/설치/실행 경로를 확인함" if homepage.ok else "홈페이지는 차단됐지만 대체 공개 페이지에서 즉시 사용/설치 경로를 확인함"
            confidence = 0.95 if positive_text else 0.9
            if oss_install_ok:
                confidence = max(confidence, 0.9)
            return CriterionResult(name="usable_now", passed=True, reason=reason, confidence=confidence, evidence=evidence or [Evidence(homepage.final_url, snippet(homepage.meta_description or homepage.text), "homepage")])
        reason = "즉시 사용 가능한 경로를 공개 페이지에서 확인하지 못함" if homepage.ok else "홈페이지 접근 실패 후 대체 페이지에서도 즉시 사용 가능한 경로를 확인하지 못함"
        return CriterionResult(name="usable_now", passed=False, reason=reason, confidence=0.7, evidence=[Evidence(homepage.final_url, snippet(homepage.text), "homepage")])

    def _eval_clear_function_desc(self, homepage: FetchResult, all_pages: dict[str, FetchResult], extracted: dict[str, object]) -> CriterionResult:
        """서비스 기능 설명의 구체성(누가/무엇을/어떻게)을 평가한다."""
        evidence: list[Evidence] = []
        candidate_texts: list[tuple[str, str]] = []
        for p in all_pages.values():
            if p.ok:
                candidate_texts.append((p.final_url, " ".join([p.title, p.meta_description, p.text[:2500]])))

        best_sentence = ""
        best_url = homepage.final_url
        best_score = 0.0
        for url, text in candidate_texts:
            for s in split_sentences(text)[:20]:
                s_lower = lower(s)
                score = 0.0
                if len(s) >= 40:
                    score += 0.15
                if keyword_hit(s_lower, ACTION_KEYWORDS):
                    score += 0.35
                if keyword_hit(s_lower, TASK_NOUNS):
                    score += 0.25
                if re.search(r"\b(for|helps?|let[s]?)\b", s_lower) or any(k in s_lower for k in ["위한", "도와", "지원", "allows you to"]):
                    score += 0.15
                if keyword_hit(s_lower, GENERIC_MARKETING_PHRASES):
                    score -= 0.2
                if any(k in s_lower for k in ["ai", "llm", "agent", "assistant", "어시스턴트", "에이전트"]):
                    score += 0.1
                if score > best_score:
                    best_score = score
                    best_sentence = s
                    best_url = url

        if homepage.meta_description and len(homepage.meta_description) >= 40:
            best_score += 0.1
        best_score = max(0.0, min(best_score, 1.0))

        llm = getattr(self, "llm", None)
        if self.config.enable_llm_for_clear_desc and llm and 0.35 <= best_score < 0.75:
            llm_out = llm.evaluate(
                {
                    "url": homepage.final_url,
                    "title": homepage.title,
                    "meta_description": homepage.meta_description,
                    "homepage_text": homepage.text[:2500],
                    "candidate_sentence": best_sentence,
                }
            )
            evidence.append(Evidence(best_url, snippet(str(llm_out.get("summary", best_sentence)) or best_sentence), "llm_interpreted_desc"))
            return CriterionResult(
                name="clear_function_desc",
                passed=bool(llm_out.get("passed", False)),
                reason=str(llm_out.get("reason", "")) or "LLM 보조 판정",
                confidence=float(llm_out.get("confidence", 0.5)),
                evidence=evidence,
            )

        if best_sentence:
            evidence.append(Evidence(best_url, snippet(best_sentence), "desc_sentence"))
        passed = best_score >= 0.55 and bool(best_sentence)
        reason = "누가/무엇을/어떻게에 해당하는 기능 설명을 추출 가능" if passed else "마케팅 문구는 있으나 구체 기능 설명으로 보기 어려움"
        return CriterionResult(name="clear_function_desc", passed=passed, reason=reason, confidence=best_score, evidence=evidence or [Evidence(homepage.final_url, snippet(homepage.meta_description or homepage.text), "homepage")])

    def _eval_pricing(self, homepage: FetchResult, all_pages: dict[str, FetchResult], extracted: dict[str, object]) -> CriterionResult:
        """공개 pricing/plan/licensing 신호 존재 여부를 평가한다."""
        pricing_pages: list[str] = extracted.get("pricing_pages", [])  # type: ignore[assignment]
        ok_page_count = sum(1 for p in all_pages.values() if p.ok)
        url_sample = self._sample_ok_page_urls(all_pages)
        if pricing_pages:
            url = pricing_pages[0]
            page = next((p for p in all_pages.values() if p.final_url == url), None)
            evidence = [Evidence(url, snippet(page.text), "pricing_page")] if page else []
            return CriterionResult(name="has_pricing", passed=True, reason="pricing/plans/billing 관련 공개 페이지를 확인함", confidence=0.95, evidence=evidence)
        if extracted.get("contact_sales_only"):
            return CriterionResult(
                name="has_pricing",
                passed=self.config.contact_sales_counts_as_pricing,
                reason=(
                    "문의(contact sales)만 확인되고 공개 가격/플랜 구조는 확인되지 않음"
                    if not self.config.contact_sales_counts_as_pricing
                    else "문의 기반 가격 정책을 pricing으로 인정"
                ),
                confidence=0.8,
                evidence=[Evidence(homepage.final_url, snippet(homepage.text), "contact_sales_only")],
            )
        if extracted.get("license_detected") and self.config.license_counts_as_pricing_for_oss:
            return CriterionResult(name="has_pricing", passed=True, reason="OSS로 보이며 라이선스 정보가 존재함", confidence=0.7, evidence=[Evidence(homepage.final_url, snippet(homepage.text), "license_detected")])
        return CriterionResult(
            name="has_pricing",
            passed=False,
            reason=(
                "공개 가격/플랜/라이선스 정보를 확인하지 못함 "
                f"(확인 페이지={ok_page_count}개, pricing_pages=0, "
                f"contact_sales_only={bool(extracted.get('contact_sales_only'))}, "
                f"license_detected={bool(extracted.get('license_detected'))}, "
                f"확인 URL 샘플={url_sample})"
            ),
            confidence=0.85,
            evidence=[Evidence(homepage.final_url, snippet(homepage.text), "homepage")],
        )

    def _eval_docs(self, homepage: FetchResult, all_pages: dict[str, FetchResult], extracted: dict[str, object]) -> CriterionResult:
        """docs/help/guide/faq 존재 여부를 평가한다."""
        docs_pages: list[str] = extracted.get("docs_pages", [])  # type: ignore[assignment]
        ok_pages = [p for p in all_pages.values() if p.ok]
        docs_hint_count = 0
        for p in ok_pages:
            docs_blob = lower(" ".join([p.final_url, p.title, p.meta_description]))
            if keyword_hit(docs_blob, DOCS_TEXT):
                docs_hint_count += 1
        url_sample = self._sample_ok_page_urls(all_pages)
        if docs_pages:
            url = docs_pages[0]
            page = next((p for p in all_pages.values() if p.final_url == url), None)
            evidence = [Evidence(url, snippet(page.text), "docs_page")] if page else []
            if extracted.get("faq_only_docs") and not self.config.faq_counts_as_docs:
                return CriterionResult(
                    name="has_docs_or_help",
                    passed=False,
                    reason=(
                        "FAQ 페이지만 확인됨("
                        f"{url}) 및 config.faq_counts_as_docs=False로 docs/help 기준 미충족"
                    ),
                    confidence=0.7,
                    evidence=evidence,
                )
            return CriterionResult(name="has_docs_or_help", passed=True, reason="docs/help/guide/faq 등 사용 문서를 확인함", confidence=0.9, evidence=evidence)
        return CriterionResult(
            name="has_docs_or_help",
            passed=False,
            reason=(
                "docs/help/guide/faq를 확인하지 못함 "
                f"(확인 페이지={len(ok_pages)}개, docs 키워드 힌트 페이지={docs_hint_count}개, "
                f"docs_pages=0, 확인 URL 샘플={url_sample})"
            ),
            confidence=0.9,
            evidence=[Evidence(homepage.final_url, snippet(homepage.text), "homepage")],
        )

    def _eval_policy(self, homepage: FetchResult, all_pages: dict[str, FetchResult], extracted: dict[str, object]) -> CriterionResult:
        """privacy/terms/data policy 관련 문서 존재 여부를 평가한다."""
        policy_pages: list[str] = extracted.get("policy_pages", [])  # type: ignore[assignment]
        ok_pages = [p for p in all_pages.values() if p.ok]
        policy_hint_count = 0
        for p in ok_pages:
            policy_blob = lower(" ".join([p.final_url, p.title, p.meta_description]))
            if keyword_hit(policy_blob, POLICY_TEXT):
                policy_hint_count += 1
        url_sample = self._sample_ok_page_urls(all_pages)
        if policy_pages:
            resolved_pages = [p for p in all_pages.values() if p.final_url in policy_pages]
            evidence = [Evidence(p.final_url, snippet(p.text), "policy_page") for p in resolved_pages[:2]]
            has_privacy_or_data_policy = False
            has_terms_only = False
            for page in resolved_pages:
                blob = lower(" ".join([page.final_url, page.title, page.meta_description, page.text[:2000]]))
                if any(tok in blob for tok in ["privacy", "privacy policy", "data policy", "data processing", "gdpr", "dpa", "개인정보"]):
                    has_privacy_or_data_policy = True
                    break
                if "terms" in blob or "이용약관" in blob:
                    has_terms_only = True
            if has_privacy_or_data_policy:
                return CriterionResult(name="has_privacy_or_data_policy", passed=True, reason="privacy/terms/data policy 관련 페이지를 확인함", confidence=0.95, evidence=evidence)
            if has_terms_only and not self.config.terms_only_counts_as_policy:
                first_url = policy_pages[0]
                return CriterionResult(
                    name="has_privacy_or_data_policy",
                    passed=False,
                    reason=(
                        f"terms 성격 페이지만 확인됨({first_url}) 및 "
                        "config.terms_only_counts_as_policy=False로 privacy/data policy 기준 미충족"
                    ),
                    confidence=0.8,
                    evidence=evidence or [Evidence(homepage.final_url, snippet(homepage.text), "homepage")],
                )
            return CriterionResult(name="has_privacy_or_data_policy", passed=True, reason="terms 기반 policy를 확인함", confidence=0.85, evidence=evidence)
        return CriterionResult(
            name="has_privacy_or_data_policy",
            passed=False,
            reason=(
                "privacy/terms/data policy를 확인하지 못함 "
                f"(확인 페이지={len(ok_pages)}개, policy 키워드 힌트 페이지={policy_hint_count}개, "
                f"policy_pages=0, 확인 URL 샘플={url_sample})"
            ),
            confidence=0.9,
            evidence=[Evidence(homepage.final_url, snippet(homepage.text), "homepage")],
        )

    def _calculate_weighted_scores(self, criteria: dict[str, CriterionResult]) -> tuple[dict[str, float], float, dict[str, float]]:
        """기준별 confidence와 가중치로 점수 상세/총점을 계산한다."""
        weights = {
            "usable_now": self.config.usable_now_weight,
            "clear_function_desc": self.config.clear_function_desc_weight,
            "has_docs_or_help": self.config.docs_or_help_weight,
            "has_privacy_or_data_policy": self.config.privacy_or_policy_weight,
            "has_pricing": self.config.pricing_weight,
        }
        criterion_scores: dict[str, float] = {}
        weighted_points: dict[str, float] = {}
        total = 0.0
        for name, result in criteria.items():
            base = max(0.0, min(result.confidence, 1.0)) if result.passed else 0.0
            criterion_scores[name] = base
            points = base * weights[name] * 100.0
            weighted_points[name] = points
            total += points
        return weighted_points, total, criterion_scores


class BaseToolQualityEvaluator(
    DiscoverySignalMixin,
    AiScopeClassifierMixin,
    TaxonomyClassifierMixin,
    CriteriaEvaluatorMixin,
    StatusPolicyMixin,
):
    """파이프라인 오케스트레이션과 결과 조립을 담당하는 코어 평가기."""

    def __init__(
        self,
        fetcher: PageFetcher,
        config: EvalConfig | None = None,
        llm: ClearDescriptionLLM | None = None,
    ):
        """설정/수집기(fetcher)/파이프라인 스텝 컨테이너를 초기화한다."""
        self.config = config or EvalConfig()
        self.fetcher = fetcher
        self.llm = llm
        self.pipeline_steps: list[PipelineStep] = []

    def set_pipeline_steps(self, steps: Iterable[PipelineStep]) -> None:
        """실행 스텝 순서를 외부에서 주입한다."""
        self.pipeline_steps = list(steps)

    def evaluate(self, url: str) -> EvaluationResult:
        """단일 URL에 대해 파이프라인을 실행하고 EvaluationResult를 반환한다."""
        context: dict[str, Any] = {
            "input_url": url,
            "normalized_url": normalize_url(url),
        }
        if not self.pipeline_steps:
            raise RuntimeError("pipeline steps are not configured. call set_pipeline_steps(...) before evaluate().")
        for step in self.pipeline_steps:
            step(self, context)
        ctx = context

        return EvaluationResult(
            input_url=ctx["input_url"],
            normalized_url=ctx["normalized_url"],
            predicted_status=ctx["predicted_status"],
            final_status=ctx["final_status"],
            passed_count=ctx["passed_count"],
            hard_pass=ctx["hard_pass"],
            review_required=ctx["review_required"],
            review_reasons=ctx["review_reasons"],
            criteria=ctx["criteria"],
            summary=ctx["summary"],
            extracted=ctx["extracted"],
            total_score=ctx.get("score_context", {}).get("total_score"),
            score_breakdown=ctx.get("score_context", {}).get("score_breakdown"),
        )


class WeightedQualityEvaluator(BaseToolQualityEvaluator):
    """가중치 점수 기반 품질 평가 정책을 구현한 evaluator."""

    def _build_score_context(self, criteria: dict[str, CriterionResult]) -> dict[str, object]:
        """기준별 점수 상세/총점/기준 점수를 포함한 score context를 생성한다."""
        score_breakdown, total_score, criterion_scores = self._calculate_weighted_scores(criteria)
        return {
            "total_score": total_score,
            "score_breakdown": score_breakdown,
            "criterion_scores": criterion_scores,
        }

    def _predict_status(
        self,
        criteria: dict[str, CriterionResult],
        passed_count: int,
        hard_pass: bool,
        score_context: dict[str, object],
    ) -> str:
        """가중치 점수와 하한 게이트를 사용해 최종 상태를 예측한다."""
        criterion_scores = score_context.get("criterion_scores", {})
        total_score = float(score_context.get("total_score", 0.0))

        usable_score = float(criterion_scores.get("usable_now", 0.0))  # type: ignore[arg-type]
        clear_desc_score = float(criterion_scores.get("clear_function_desc", 0.0))  # type: ignore[arg-type]
        docs_score = float(criterion_scores.get("has_docs_or_help", 0.0))  # type: ignore[arg-type]
        privacy_score = float(criterion_scores.get("has_privacy_or_data_policy", 0.0))  # type: ignore[arg-type]

        if usable_score < self.config.usable_now_min_for_non_rejected:
            return "rejected"
        if clear_desc_score < self.config.clear_desc_min_for_non_rejected:
            return "rejected"

        if total_score >= self.config.curated_score_threshold:
            if docs_score < self.config.docs_min_for_curated:
                return "incubating"
            if privacy_score < self.config.privacy_min_for_curated:
                return "incubating"
            return "curated"

        if total_score >= self.config.incubating_score_threshold:
            return "incubating"

        return "rejected"

    def _build_summary(
        self,
        criteria: dict[str, CriterionResult],
        predicted_status: str,
        final_status: str,
        passed_count: int,
        review_required: bool,
        review_reasons: list[str],
        score_context: dict[str, object],
    ) -> str:
        """총점을 포함한 weighted 평가 요약 문자열을 생성한다."""
        passed_names = [name for name, result in criteria.items() if result.passed]
        failed_names = [name for name, result in criteria.items() if not result.passed]
        total_score = float(score_context.get("total_score", 0.0))

        text = (
            f"총 {passed_count}/5개 기준 충족. "
            f"총점={total_score:.1f}/100. "
            f"예상 상태={predicted_status}, 최종 상태={final_status}. "
            f"통과 항목={passed_names}, 미통과 항목={failed_names}."
        )
        non_ai_scope_reason = next(
            (
                result.reason
                for result in criteria.values()
                if result.reason.startswith("AI 사이트 판별 게이트에서 제외됨")
            ),
            "",
        )
        if non_ai_scope_reason:
            text += f" 비대상 처리 사유={non_ai_scope_reason}."
        if review_required:
            text += f" 수동 검수 필요 사유={review_reasons}."
        return text
