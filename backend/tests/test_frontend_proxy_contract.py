from pathlib import Path


ROOT = Path(__file__).parents[2]


def test_frontend_uses_same_origin_api_and_compose_proxy() -> None:
    frontend = (ROOT / "frontend/src/main.tsx").read_text()
    proxy = (ROOT / "frontend/nginx.conf").read_text()
    assert 'const API = ""' in frontend
    assert "http://localhost:8000" not in frontend
    assert "location /api/" in proxy
    assert "proxy_pass http://api:8000" in proxy


def test_normal_compose_startup_does_not_depend_on_schema_bootstrap() -> None:
    compose = (ROOT / "docker-compose.yml").read_text()
    api = compose.split("\n  worker:", maxsplit=1)[0]
    worker = compose.split("\n  worker:", maxsplit=1)[1].split("\n  postgres:", maxsplit=1)[0]

    assert "schema:" not in api
    assert "schema:" not in worker
    assert 'profiles: ["bootstrap"]' in compose
