"""src/rule/utils.py — 유틸 함수 단위 테스트."""

import pytest
from src.rule.utils import (
    normalize_url,
    get_domain,
    is_same_domain,
    squash_ws,
    lower,
    snippet,
    keyword_hit,
    keyword_hit_count,
    collect_keyword_hits,
    count_keyword_hits_bounded,
    split_sentences,
    has_pricing_url_hint,
    has_usable_url_hint,
    is_likely_pricing_link,
    is_strong_pricing_page,
    is_allowed_external_docs_link,
    is_allowed_external_policy_link,
    likely_related_external_candidates,
)


class TestNormalizeUrl:
    def test_adds_https_when_no_scheme(self):
        assert normalize_url("example.com") == "https://example.com/"

    def test_lowercases_netloc(self):
        assert normalize_url("https://EXAMPLE.COM") == "https://example.com/"

    def test_removes_trailing_slash_from_path(self):
        result = normalize_url("https://example.com/path/")
        assert result == "https://example.com/path"

    def test_keeps_root_slash(self):
        result = normalize_url("https://example.com")
        assert result.endswith("/")

    def test_strips_whitespace(self):
        result = normalize_url("  https://example.com  ")
        assert "example.com" in result


class TestGetDomain:
    def test_extracts_host(self):
        assert get_domain("https://example.com/path") == "example.com"

    def test_lowercase(self):
        assert get_domain("https://EXAMPLE.COM") == "example.com"

    def test_empty_on_invalid(self):
        assert get_domain("not_a_url") == ""


class TestIsSameDomain:
    def test_same_domain(self):
        assert is_same_domain("https://example.com/a", "https://example.com/b") is True

    def test_different_domain(self):
        assert is_same_domain("https://example.com", "https://other.com") is False

    def test_subdomain_is_different(self):
        assert is_same_domain("https://example.com", "https://docs.example.com") is False


class TestSquashWs:
    def test_collapses_spaces(self):
        assert squash_ws("hello   world") == "hello world"

    def test_strips_edges(self):
        assert squash_ws("  hi  ") == "hi"

    def test_empty_string(self):
        assert squash_ws("") == ""

    def test_none_like_empty(self):
        assert squash_ws(None) == ""  # type: ignore[arg-type]


class TestLower:
    def test_lowercases_and_squashes(self):
        assert lower("Hello   WORLD") == "hello world"


class TestSnippet:
    def test_short_text_unchanged(self):
        assert snippet("short", max_len=100) == "short"

    def test_long_text_truncated(self):
        result = snippet("a" * 300, max_len=100)
        assert len(result) == 100
        assert result.endswith("...")

    def test_exact_max_len(self):
        result = snippet("a" * 220)
        assert len(result) == 220


class TestKeywordHit:
    def test_finds_keyword(self):
        assert keyword_hit("This is an AI tool", {"ai tool"}) is True

    def test_returns_false_when_absent(self):
        assert keyword_hit("nothing here", {"ai tool"}) is False

    def test_case_insensitive(self):
        assert keyword_hit("MACHINE LEARNING", {"machine learning"}) is True


class TestKeywordHitCount:
    def test_counts_matches(self):
        text = "ai assistant chatbot llm model"
        result = keyword_hit_count(text, {"ai", "chatbot", "llm"})
        assert result == 3

    def test_zero_when_none(self):
        assert keyword_hit_count("hello world", {"ai", "robot"}) == 0

    def test_normalized_mode(self):
        result = keyword_hit_count("ai chatbot llm", {"ai", "chatbot"}, normalized=True)
        assert result == 2


class TestCollectKeywordHits:
    def test_returns_matching_keywords(self):
        hits = collect_keyword_hits("machine learning deep learning", {"machine learning", "deep learning", "xyz"})
        assert "machine learning" in hits
        assert "deep learning" in hits
        assert "xyz" not in hits

    def test_single_alpha_word_uses_boundary(self):
        # "ai"가 단어 경계에 있는 경우만 매칭
        hits = collect_keyword_hits("this is an ai tool", {"ai"})
        assert "ai" in hits

    def test_no_false_positive_for_boundary(self):
        # "mail"에서 "ai"가 매칭되지 않아야 함
        hits = collect_keyword_hits("email gmail", {"ai"})
        assert "ai" not in hits

    def test_empty_text_returns_empty(self):
        assert collect_keyword_hits("", {"ai", "robot"}) == set()


class TestCountKeywordHitsBounded:
    def test_short_word_uses_boundary(self):
        count = count_keyword_hits_bounded("api rest endpoint", {"api"})
        assert count == 1

    def test_long_keyword_substring_match(self):
        count = count_keyword_hits_bounded("machine learning framework", {"machine learning"})
        assert count == 1

    def test_no_match(self):
        assert count_keyword_hits_bounded("hello world", {"ai", "robot"}) == 0


class TestSplitSentences:
    def test_splits_by_period(self):
        text = "This is the first long sentence here. This is the second long sentence too. And the third one as well."
        result = split_sentences(text)
        assert len(result) >= 2

    def test_filters_short_sentences(self):
        text = "Hi. This is a proper sentence that is long enough to keep."
        result = split_sentences(text)
        assert all(len(s) >= 20 for s in result)

    def test_empty_returns_empty(self):
        assert split_sentences("") == []


class TestHasPricingUrlHint:
    def test_pricing_path(self):
        assert has_pricing_url_hint("https://example.com/pricing") is True

    def test_plans_path(self):
        assert has_pricing_url_hint("https://example.com/plans") is True

    def test_billing_path(self):
        assert has_pricing_url_hint("https://example.com/billing") is True

    def test_normal_path_false(self):
        assert has_pricing_url_hint("https://example.com/about") is False


class TestHasUsableUrlHint:
    def test_signup(self):
        assert has_usable_url_hint("https://example.com/signup") is True

    def test_login(self):
        assert has_usable_url_hint("https://example.com/login") is True

    def test_app_path(self):
        assert has_usable_url_hint("https://example.com/app") is True

    def test_about_false(self):
        assert has_usable_url_hint("https://example.com/about") is False


class TestIsLikelyPricingLink:
    def test_pricing_url(self):
        assert is_likely_pricing_link("Pricing", "https://example.com/pricing") is True

    def test_pricing_text(self):
        assert is_likely_pricing_link("See our plans", "https://example.com/features") is True

    def test_unrelated(self):
        assert is_likely_pricing_link("About us", "https://example.com/about") is False


class TestIsStrongPricingPage:
    def test_price_value_detected(self):
        assert is_strong_pricing_page(
            "https://example.com/pricing",
            "Pricing",
            "",
            "Start from $9/month for basic plan.",
        ) is True

    def test_pricing_path_with_plan_term(self):
        assert is_strong_pricing_page(
            "https://example.com/pricing",
            "Pricing Plans",
            "Choose a plan",
            "monthly annual subscription",
        ) is True

    def test_placeholder_without_plan_term_returns_false(self):
        # placeholder 신호만 있고 실제 plan 용어 없으면 False
        assert is_strong_pricing_page(
            "https://example.com/pricing",
            "Pricing",
            "",
            "coming soon under construction 출시 예정",
        ) is False

    def test_irrelevant_page_false(self):
        assert is_strong_pricing_page(
            "https://example.com/about",
            "About",
            "",
            "We are a company",
        ) is False


class TestIsAllowedExternalDocsLink:
    def test_docs_subdomain(self):
        assert is_allowed_external_docs_link("Docs", "https://docs.example.com/guide") is True

    def test_help_path(self):
        assert is_allowed_external_docs_link("Help", "https://other.com/help") is True

    def test_unrelated_external(self):
        assert is_allowed_external_docs_link("Blog", "https://medium.com/article") is False


class TestIsAllowedExternalPolicyLink:
    def test_privacy_path(self):
        assert is_allowed_external_policy_link("Privacy", "https://example.com/privacy") is True

    def test_terms_path(self):
        assert is_allowed_external_policy_link("Terms", "https://example.com/terms") is True

    def test_unrelated_link_false(self):
        assert is_allowed_external_policy_link("Blog", "https://example.com/blog") is False


class TestLikelyRelatedExternalCandidates:
    def test_openai_returns_candidates(self):
        result = likely_related_external_candidates("https://chatgpt.com")
        assert len(result) > 0

    def test_unknown_domain_returns_empty(self):
        result = likely_related_external_candidates("https://unknownsite.com")
        assert result == []

    def test_no_duplicates(self):
        result = likely_related_external_candidates("https://chatgpt.com")
        assert len(result) == len(set(result))
