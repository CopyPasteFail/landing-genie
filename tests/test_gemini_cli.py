import json
import os
import shutil
import subprocess

import pytest

from landing_genie.config import Config
from landing_genie.gemini_runner import _iter_json_objects


def test_gemini_cli_smoke() -> None:
    """Tiny prompt to confirm the Gemini CLI works with .env configuration."""
    config = Config.load()
    if not shutil.which(config.gemini_cli_command):
        pytest.skip(f"Gemini CLI command not found: {config.gemini_cli_command}")

    prompt = "hi"
    print(f"[gemini-cli-test] prompt: {prompt!r} (model={config.gemini_code_model})")
    cmd = [
        config.gemini_cli_command,
        "--model",
        config.gemini_code_model,
        "--prompt",
        prompt,
        "--yolo",
        "--output-format",
        "json",
    ]
    env = os.environ.copy()
    # Respect the CLI/API key separation just like production code.
    if config.gemini_api_key and not os.getenv("GEMINI_ALLOW_CLI_API_KEY"):
        env.pop("GEMINI_API_KEY", None)

    result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=45)
    if result.returncode != 0:
        pytest.fail(f"Gemini CLI failed: {result.stderr or result.stdout}")

    stdout = result.stdout.strip()
    print(f"[gemini-cli-test] stdout (captured):\n{stdout}")
    assert stdout, "Gemini CLI returned no output"
    objs = list(_iter_json_objects(stdout))
    if not objs:
        try:
            objs = [json.loads(stdout)]
        except json.JSONDecodeError:
            pytest.fail(f"Gemini CLI did not return JSON as expected. First chars: {stdout[:80]!r}")

    assert objs, "Gemini CLI output contained no JSON objects"
    assert any("candidates" in obj or "usageMetadata" in obj or "stats" in obj for obj in objs), (
        f"Gemini CLI JSON missing expected fields: {objs[0]}"
    )
