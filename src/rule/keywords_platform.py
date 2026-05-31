"""플랫폼 감지용 키워드 상수."""

from __future__ import annotations

PLATFORM_KEYWORDS: dict[str, set[str]] = {
    "web": {"web app", "browser-based", "in your browser", "online", "웹앱", "웹 앱", "웹 기반"},
    "mobile": {"ios", "android", "app store", "google play", "mobile"},
    "desktop": {"desktop app", "windows app", "mac app", "macos"},
    "browser_extension": {"chrome extension", "firefox add-on", "edge extension"},
    "slack": {"slack"},
    "vscode": {"vscode", "visual studio code"},
    "api": {" api ", "developer", "developers", "sdk", "endpoint", "/api"},
}
