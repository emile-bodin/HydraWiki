from pathlib import Path


ROOT = Path(__file__).parents[2]


def test_compose_wires_workload_overrides_to_the_api_with_backend_defaults() -> None:
    compose = (ROOT / "docker-compose.yml").read_text()
    api = compose.split("\n  worker:", maxsplit=1)[0]
    worker = compose.split("\n  worker:", maxsplit=1)[1].split("\n  postgres:", maxsplit=1)[0]

    expected = {
        "HYDRAWIKI_MAX_REPOSITORY_SIZE_BYTES": "1073741824",
        "HYDRAWIKI_MAX_SOURCE_FILES": "25000",
        "HYDRAWIKI_EMBEDDING_MAX_CONCURRENCY": "2",
    }
    for variable, default in expected.items():
        assert f'{variable}: "${{{variable}:-{default}}}"' in api
        assert variable not in worker


def test_env_example_documents_non_secret_workload_defaults() -> None:
    example = (ROOT / ".env.example").read_text()

    assert "HYDRAWIKI_MAX_REPOSITORY_SIZE_BYTES=1073741824" in example
    assert "HYDRAWIKI_MAX_SOURCE_FILES=25000" in example
    assert "HYDRAWIKI_EMBEDDING_MAX_CONCURRENCY=2" in example
