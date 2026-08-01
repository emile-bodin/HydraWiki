import json
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).parents[2]


WORKLOAD_DEFAULTS = {
    "HYDRAWIKI_MAX_REPOSITORY_SIZE_BYTES": "1073741824",
    "HYDRAWIKI_MAX_SOURCE_FILES": "25000",
    "HYDRAWIKI_EMBEDDING_MAX_CONCURRENCY": "2",
}


def rendered_api_environment(overrides: dict[str, str]) -> dict[str, str]:
    environment = os.environ | {
        "HYDRAWIKI_DATABASE_URL": "postgresql://hydrawiki:validation-password@postgres:5432/hydrawiki",
        "HYDRAWIKI_POSTGRES_PASSWORD": "validation-password",
    }
    for variable in WORKLOAD_DEFAULTS:
        environment.pop(variable, None)
    environment.update(overrides)
    result = subprocess.run(
        ["docker", "compose", "config", "--format", "json"],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)["services"]["api"]["environment"]


def test_compose_uses_defaults_when_workload_variables_are_unset() -> None:
    assert {variable: rendered_api_environment({})[variable] for variable in WORKLOAD_DEFAULTS} == WORKLOAD_DEFAULTS


def test_compose_preserves_explicitly_empty_workload_variables() -> None:
    assert {variable: rendered_api_environment({variable: "" for variable in WORKLOAD_DEFAULTS})[variable] for variable in WORKLOAD_DEFAULTS} == {
        variable: "" for variable in WORKLOAD_DEFAULTS
    }


def test_compose_wires_workload_variables_only_to_the_api() -> None:
    compose = (ROOT / "docker-compose.yml").read_text()
    api = compose.split("\n  worker:", maxsplit=1)[0]
    worker = compose.split("\n  worker:", maxsplit=1)[1].split("\n  postgres:", maxsplit=1)[0]

    for variable, default in WORKLOAD_DEFAULTS.items():
        assert f'{variable}: "${{{variable}-{default}}}"' in api
        assert f'${{{variable}:-{default}}}' not in api
        assert variable not in worker


def test_env_example_documents_non_secret_workload_defaults() -> None:
    example = (ROOT / ".env.example").read_text()

    assert "HYDRAWIKI_MAX_REPOSITORY_SIZE_BYTES=1073741824" in example
    assert "HYDRAWIKI_MAX_SOURCE_FILES=25000" in example
    assert "HYDRAWIKI_EMBEDDING_MAX_CONCURRENCY=2" in example
