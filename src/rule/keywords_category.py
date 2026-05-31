"""카테고리/서브태스크/메타 카테고리 키워드 상수."""

from __future__ import annotations

PRIMARY_CATEGORY_KEYWORDS: dict[str, set[str]] = {
    "Writing & Docs": {
        "write", "writing", "document", "docs", "documentation", "email", "blog",
        "rewrite", "translate", "proofread", "grammar", "copywriting", "content",
        "knowledge base", "wiki", "note", "proposal", "report",
        "문서", "작성", "번역", "교정", "이메일", "블로그", "카피라이팅", "콘텐츠", "노트",
    },
    "Coding": {
        "code", "coding", "developer", "programming", "ide", "debug", "refactor",
        "repository", "sdk", "pull request", "source code", "codebase", "unit test",
        "integration test", "commit", "branch", "cli", "terminal",
        "코드", "개발", "디버그", "리팩토링", "테스트", "저장소", "코드베이스",
    },
    "Research": {
        "research", "search", "web search", "answer", "citation", "paper", "knowledge",
        "qa", "benchmark", "market", "insight", "analysis", "trend",
        "competitive", "competitor", "literature review", "fact check",
        "리서치", "검색", "논문", "조사", "분석", "트렌드", "경쟁사", "인사이트",
    },
    "Design & Creative": {
        "design", "creative", "image", "video", "edit image", "edit video",
        "presentation", "logo", "thumbnail", "mockup", "storyboard", "brand",
        "poster", "illustration", "ui", "ux", "concept art",
        "디자인", "이미지", "영상", "프레젠테이션", "브랜딩", "목업", "로고", "일러스트",
    },
    "Data & Analytics": {
        "data", "analytics", "sql", "dashboard", "visualization", "bi", "reporting",
        "experiment", "spreadsheet", "forecast", "modeling", "etl", "data pipeline",
        "query", "insights",
        "데이터", "대시보드", "통계", "분석", "스프레드시트", "예측", "리포트",
    },
    "Ops & Automation": {
        "automation", "workflow", "integrations", "orchestration", "zapier", "n8n",
        "make", "task automation", "rpa", "ops", "backoffice", "trigger", "scheduled",
        "ticket automation", "process automation",
        "자동화", "워크플로우", "연동", "운영", "백오피스", "트리거", "스케줄",
    },
    "Meeting & Sales": {
        "meeting", "transcript", "sales", "crm", "call", "customer support",
        "proposal", "meeting notes", "outreach", "pipeline", "lead", "deal",
        "follow-up", "discovery call", "sales deck",
        "회의", "영업", "고객", "녹취", "제안서", "리드", "파이프라인", "후속",
    },
    "DevOps / Security": {
        "devops", "security", "compliance", "vulnerability", "incident",
        "infrastructure", "cloud", "policy", "siem", "soc", "iam",
        "incident response", "audit", "secrets", "access control", "encryption",
        "보안", "취약점", "컴플라이언스", "인프라", "감사", "접근 제어", "암호화", "사고 대응",
    },
}

SUBTASK_KEYWORDS_BY_PRIMARY: dict[str, dict[str, set[str]]] = {
    "Writing & Docs": {
        "요약": {"summarize", "summary", "executive summary", "요약"},
        "번역": {"translate", "translation", "localization", "번역"},
        "문서 작성": {"write", "document", "docs", "작성", "draft"},
        "교정": {"proofread", "grammar", "spell check", "교정"},
        "이메일 작성": {"email drafting", "compose email", "이메일 작성"},
        "블로그/콘텐츠 작성": {"blog writing", "content writing", "article", "콘텐츠 작성"},
        "카피라이팅": {"copywriting", "ad copy", "landing copy", "카피라이팅"},
    },
    "Coding": {
        "IDE 에이전트": {"ide", "editor", "vscode", "jetbrains", "coding agent"},
        "코드 생성": {"generate code", "code completion", "boilerplate", "코드 생성"},
        "코드 리뷰": {"code review", "pull request", "pr review", "리뷰"},
        "버그 분석": {"debug", "bug", "error", "stack trace", "디버그"},
        "테스트 코드 생성": {"unit test", "integration test", "test generation", "테스트 코드"},
        "리팩토링": {"refactor", "cleanup code", "technical debt", "리팩토링"},
        "API 문서/스펙 생성": {"openapi", "api spec", "swagger", "api docs", "api 문서"},
    },
    "Research": {
        "웹 리서치": {"web search", "research", "search the web", "검색"},
        "문서 질의응답(QA)": {"question answering", "qa", "ask docs", "rag", "질의응답"},
        "트렌드 분석": {"trend", "market", "analysis", "트렌드"},
        "경쟁사 분석": {"competitive analysis", "competitor", "benchmark", "경쟁사"},
        "논문 분석": {"paper analysis", "literature review", "citation", "논문 분석"},
        "팩트체크": {"fact check", "verify claim", "source validation", "검증"},
    },
    "Design & Creative": {
        "이미지 생성": {"image generation", "text to image", "이미지 생성"},
        "영상 생성": {"video generation", "text to video", "영상 생성"},
        "프레젠테이션 제작": {"presentation", "slides", "pitch deck", "프레젠테이션"},
        "브랜딩/로고": {"brand design", "logo design", "branding", "브랜딩", "로고"},
        "UI 목업": {"ui mockup", "wireframe", "prototype", "목업"},
        "이미지/영상 편집": {"edit image", "edit video", "retouch", "영상 편집", "이미지 편집"},
    },
    "Data & Analytics": {
        "SQL 생성": {"sql", "query", "쿼리"},
        "데이터 시각화": {"visualization", "chart", "dashboard", "시각화"},
        "리포트 생성": {"report", "analytics", "리포트"},
        "데이터 정제": {"data cleaning", "data prep", "deduplicate", "정제"},
        "예측/모델링": {"forecast", "predictive", "modeling", "예측"},
        "지표 분석": {"kpi", "funnel analysis", "cohort", "지표 분석"},
    },
    "Ops & Automation": {
        "워크플로우 자동화": {"workflow", "automation", "orchestration", "자동화"},
        "API 연동 자동화": {"api integration", "webhook", "integration", "연동"},
        "작업 스케줄링": {"schedule", "scheduler", "cron", "스케줄"},
        "티켓 자동 분류": {"ticket routing", "auto triage", "helpdesk", "티켓 분류"},
        "문서 처리 자동화": {"document processing", "ocr workflow", "form automation", "문서 자동화"},
        "알림/운영 자동화": {"alerting", "ops automation", "incident routing", "운영 자동화"},
    },
    "Meeting & Sales": {
        "회의 요약": {"meeting summary", "meeting notes", "회의 요약"},
        "CRM 자동 입력": {"crm", "pipeline", "lead", "crm 자동"},
        "세일즈 이메일 작성": {"sales email", "outreach", "cold email", "세일즈 이메일"},
        "콜 스크립트 생성": {"call script", "talk track", "discovery questions", "콜 스크립트"},
        "세일즈 제안서 작성": {"sales proposal", "proposal draft", "제안서 작성"},
        "후속 조치 정리": {"follow-up", "next steps", "action items", "후속 조치"},
    },
    "DevOps / Security": {
        "로그 분석": {"log analysis", "logs", "로그"},
        "취약점 분석": {"vulnerability", "cve", "취약점"},
        "컴플라이언스 점검": {"compliance", "soc2", "gdpr", "iso 27001", "컴플라이언스"},
        "인시던트 대응": {"incident response", "postmortem", "on-call", "사고 대응"},
        "보안 정책 점검": {"security policy", "access control", "least privilege", "보안 정책"},
        "클라우드 보안 점검": {"cloud security", "iam", "misconfiguration", "클라우드 보안"},
    },
}

META_CATEGORY_KEYWORDS: dict[str, set[str]] = {
    "Create": {"create", "generate", "build", "작성", "생성"},
    "Analyze": {"analyze", "analysis", "insight", "분석"},
    "Build": {"develop", "code", "ship", "deploy", "개발"},
    "Automate": {"automate", "workflow", "orchestrate", "자동화"},
    "Communicate": {"email", "meeting", "chat", "sales", "커뮤니케이션", "회의"},
    "Secure": {"security", "privacy", "compliance", "보안", "개인정보"},
}

DEFAULT_META_BY_PRIMARY: dict[str, list[str]] = {
    "Writing & Docs": ["Create", "Communicate"],
    "Coding": ["Build", "Create"],
    "Research": ["Analyze"],
    "Design & Creative": ["Create"],
    "Data & Analytics": ["Analyze"],
    "Ops & Automation": ["Automate"],
    "Meeting & Sales": ["Communicate", "Analyze"],
    "DevOps / Security": ["Secure", "Analyze"],
}
