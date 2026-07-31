from pathlib import Path


ROOT = Path(__file__).parents[2]


def test_frontend_uses_same_origin_api_and_compose_proxy() -> None:
    frontend = (ROOT / "frontend/src/main.tsx").read_text()
    proxy = (ROOT / "frontend/nginx.conf").read_text()
    assert 'const API = ""' in frontend
    assert "http://localhost:8000" not in frontend
    assert "location /api/" in proxy
    assert "proxy_pass http://api:8000" in proxy
