"""AI/비AI 사이트 판별용 키워드 상수."""

from __future__ import annotations

import re

POSITIVE_USE_TEXT = {
    "sign up", "signup", "get started", "start free", "try now", "try for free",
    "use now", "launch app", "open app", "login", "log in", "download", "install",
    "quickstart", "quick start", "start building", "run locally", "self-hosted",
    "start creating", "create now", "generate now", "make art", "create image",
    "무료로 시작", "시작하기", "무료 체험", "다운로드", "설치", "로그인", "사용해보기",
    "지금 생성", "이미지 생성", "바로 만들기",
}

NEGATIVE_USE_TEXT = {
    "join waitlist", "waitlist", "coming soon", "early access", "request access",
    "get early access", "private beta", "beta waitlist",
    "사전 신청", "얼리 액세스", "출시 예정", "곧 출시", "대기자 명단",
}

STRONG_PRICING_TEXT = {
    "pricing", "plans", "plan", "billing", "subscription",
    "contact sales", "quote",
    "요금", "가격", "플랜", "구독",
}

PRICE_VALUE_RE = re.compile(
    r"(\$|₩|€|£)\s*\d+"
    r"|\b\d+(\.\d+)?\s*(/|per)\s*(month|year|mo|yr|seat|user)\b"
    r"|\b(monthly|annual|per seat|per user)\b"
    r"|\b(월|연)\s*\d+",
    re.I,
)

DOCS_TEXT = {
    "docs", "documentation", "help", "help center", "support", "faq", "guide",
    "getting started", "quickstart", "quick start", "manual", "readme",
    "문서", "가이드", "도움말", "고객지원", "faq", "시작하기", "사용법",
}

POLICY_TEXT = {
    "privacy", "privacy policy", "data policy", "data processing", "terms",
    "terms of service", "security", "dpa", "gdpr",
    "개인정보", "개인정보처리방침", "이용약관", "보안", "데이터 처리", "정책",
}

ACTION_KEYWORDS = {
    "write", "generate", "create", "edit", "rewrite", "translate", "summarize",
    "search", "research", "analyze", "code", "debug", "review", "refactor",
    "answer", "query", "extract", "automate", "transcribe", "record", "plan",
    "build", "design", "visualize", "classify", "tag", "parse",
    "작성", "생성", "편집", "요약", "번역", "검색", "리서치", "분석",
    "코드", "리팩토링", "디버그", "자동화", "전사", "추출", "설계", "정리",
}

TASK_NOUNS = {
    "document", "docs", "email", "report", "meeting", "transcript", "code",
    "api", "image", "video", "research", "search", "data", "dashboard",
    "workflow", "ticket", "customer support", "crm", "spreadsheet", "sql",
    "document editing", "presentation", "agent",
    "문서", "이메일", "보고서", "회의", "녹취", "코드", "이미지", "영상",
    "리서치", "검색", "데이터", "대시보드", "워크플로우", "티켓", "고객지원",
    "스프레드시트", "sql", "프레젠테이션", "에이전트",
}

GENERIC_MARKETING_PHRASES = {
    "future of work", "supercharge your workflow", "unlock productivity",
    "reimagine", "ai-powered experience", "next generation", "boost productivity",
    "혁신", "미래", "생산성 향상", "새로운 경험",
}

AI_SITE_STRONG_KEYWORDS = {
    "artificial intelligence", "generative ai", "llm", "gpt",
    "machine learning", "foundation model", "large language model",
    "fine-tuning", "fine tuning", "finetuning", "instruction tuning",
    "lora", "rlhf", "inference", "neural network", "prompt engineering",
    "생성형 ai", "인공지능", "머신러닝", "대규모 언어 모델",
}

AI_SITE_WEAK_KEYWORDS = {
    "ai assistant", "ai agent", "assistant", "agent",
    "rag", "prompt", "prompts",
    "멀티모달", "에이전트", "어시스턴트",
}

# 하위 호환을 위해 기존 상수도 유지한다.
AI_SITE_KEYWORDS = AI_SITE_STRONG_KEYWORDS | AI_SITE_WEAK_KEYWORDS

NON_AI_SITE_STRONG_KEYWORDS = {
    "breaking news", "top stories", "headlines", "latest headlines",
    "news coverage", "political news", "market news", "sports scores",
    "weather forecast", "live blog", "local news", "finance news",
    "stock market news", "entertainment news", "movie review",
    "community forum", "discussion board",
    "add to cart", "buy now", "checkout",
    "flight booking", "hotel booking", "restaurant reviews",
    "오늘의 뉴스", "속보", "헤드라인", "스포츠 뉴스", "연예 뉴스", "정치 뉴스",
    "커뮤니티 포럼", "토론 게시판", "장바구니", "구매하기", "결제",
    "항공권 예약", "호텔 예약", "맛집 리뷰", "주식 시황",
}

NON_AI_SITE_WEAK_KEYWORDS = {
    "weather", "sports", "entertainment", "live updates", "opinion",
    "editorial", "celebrity", "tv shows", "comments", "forum",
    "community", "thread", "shopping", "marketplace", "shipping",
    "coupon", "recipe", "gaming",
    "날씨", "기상", "사설", "칼럼", "신문", "잡지", "댓글", "포럼",
    "쇼핑", "쿠폰", "레시피", "게임",
}

# 하위 호환을 위해 기존 상수도 유지한다.
NON_AI_SITE_KEYWORDS = NON_AI_SITE_STRONG_KEYWORDS | NON_AI_SITE_WEAK_KEYWORDS

EXTERNAL_DOCS_HOST_PREFIXES = ("help.", "docs.", "support.", "developers.", "developer.")
EXTERNAL_POLICY_HOSTS = ("openai.com", "www.openai.com")

KNOWN_AI_BRAND_TOKENS = {
    "openai",
    "anthropic",
    "huggingface",
    "perplexity",
    "midjourney",
    "stability",
    "mistral",
    "cohere",
    "deepmind",
    "gemini",
    "claude",
    "copilot",
    "cursor",
    "runway",
    "elevenlabs",
    "suno",
    "udio",
    "pika",
    "synthesia",
    "jasper",
    "writesonic",
    "character",
    "inflection",
    "xai",
    "together",
    "replicate",
    "fireworks",
    "groq",
}
