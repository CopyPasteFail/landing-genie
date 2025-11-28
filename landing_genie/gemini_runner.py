from __future__ import annotations
import subprocess
from pathlib import Path
from typing import Optional

from .config import Config


def _run_gemini(prompt_text: str, model: str, config: Config, cwd: Optional[Path] = None) -> None:
    cmd = [
        config.gemini_cli_command,
        "--model", model,
        "--prompt", prompt_text,
        "--yolo",
        "--output-format", "json",
    ]
    result = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd is not None else None,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Gemini CLI failed. Command: {' '.join(cmd)}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )


def generate_site(slug: str, product_prompt: str, project_root: Path, config: Config) -> None:
    prompts_dir = project_root / "prompts"
    template_path = prompts_dir / "runtime_generation_prompt.md"
    if not template_path.exists():
        raise FileNotFoundError(f"Prompt template not found at {template_path}")

    template = template_path.read_text(encoding="utf-8")
    text = (
        template
        .replace("{{ slug }}", slug)
        .replace("{{ root_domain }}", config.root_domain)
        .replace("{{ product_prompt }}", product_prompt)
        .replace("{{ product_type }}", "hybrid")
    )

    _run_gemini(text, config.gemini_code_model, config, cwd=project_root)


def refine_site(slug: str, feedback: str, project_root: Path, config: Config) -> None:
    prompts_dir = project_root / "prompts"
    template_path = prompts_dir / "refine_landing_prompt.md"
    if not template_path.exists():
        raise FileNotFoundError(f"Refine prompt template not found at {template_path}")

    template = template_path.read_text(encoding="utf-8")
    text = (
        template
        .replace("{{ slug }}", slug)
        .replace("{{ feedback }}", feedback)
    )

    _run_gemini(text, config.gemini_code_model, config, cwd=project_root)
