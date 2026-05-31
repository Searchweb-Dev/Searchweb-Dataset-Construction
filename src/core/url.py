"""URL 정규화 로직."""

from urllib.parse import urlparse, urlunparse, parse_qs, urlencode


def normalize_url(url: str) -> str:
    """URL을 정규화하여 canonical URL 생성.

    - 프로토콜 소문자화
    - 빈 포트 제거
    - 쿼리 파라미터 정렬 및 불필요한 파라미터 제거
    - 프래그먼트 제거
    - 경로 정규화
    """
    try:
        raw = url.strip()
        # 스킴 없는 URL은 urlparse가 netloc을 path로 오파싱 → //를 앞에 붙여 교정
        if not raw.startswith(("http://", "https://", "//")):
            raw = "//" + raw
        parsed = urlparse(raw)

        # 프로토콜 없으면 https 추가
        scheme = parsed.scheme.lower() if parsed.scheme else "https"

        # 호스트명 소문자화
        netloc = parsed.netloc.lower() if parsed.netloc else ""

        # www. 제거 (www.example.com → example.com 으로 통일)
        if netloc.startswith("www."):
            netloc = netloc[4:]

        # 표준 포트 제거
        if ":" in netloc:
            host, port = netloc.rsplit(":", 1)
            if (scheme == "http" and port == "80") or (scheme == "https" and port == "443"):
                netloc = host

        # 경로 정규화 (trailing slash 제거)
        path = parsed.path.rstrip("/") or ""

        # 쿼리 파라미터 정렬
        if parsed.query:
            params = parse_qs(parsed.query, keep_blank_values=True)
            # 각 파라미터를 정렬하여 다시 구성
            sorted_params = sorted((k, sorted(v)) for k, v in params.items())
            query = urlencode(sorted_params, doseq=True)
        else:
            query = ""

        # 프래그먼트는 제거
        fragment = ""

        canonical = urlunparse((scheme, netloc, path, "", query, fragment))
        return canonical
    except (ValueError, AttributeError):
        # 파싱 실패 시 원본 URL 반환
        return url.strip()


