from __future__ import annotations
import os
from dataclasses import dataclass
from typing import Literal, overload
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    root_domain: str
    cf_account_id: str
    cf_api_token: str
    gemini_code_model: str
    gemini_image_model: str
    gemini_cli_command: str
    gemini_api_key: str | None
    gemini_telemetry_otlp_endpoint: str | None
    gemini_image_cost_per_1k_tokens: float | None

    @classmethod
    def load(cls) -> "Config":
        @overload
        def _get(name: str, *, required: Literal[True] = True, default: None = None) -> str:
            ...

        @overload
        def _get(name: str, *, required: Literal[False], default: str) -> str:
            ...

        @overload
        def _get(name: str, *, required: Literal[False], default: None = None) -> str | None:
            ...

        def _get(name: str, *, required: bool = True, default: str | None = None) -> str | None:
            value = os.getenv(name)
            if value is None:
                value = default
            if required and not value:
                raise RuntimeError(f"Missing required environment variable: {name}")
            return value

        image_cost_str = _get("GEMINI_IMAGE_COST_PER_1K_TOKENS", required=False, default=None)
        image_cost_per_1k_tokens: float | None
        if image_cost_str is None or image_cost_str == "":
            image_cost_per_1k_tokens = None
        else:
            try:
                image_cost_per_1k_tokens = float(image_cost_str)
            except ValueError:
                raise RuntimeError("Invalid GEMINI_IMAGE_COST_PER_1K_TOKENS; must be a number (e.g. 0.03)")

        return cls(
            root_domain=_get("ROOT_DOMAIN"),
            cf_account_id=_get("CLOUDFLARE_ACCOUNT_ID"),
            cf_api_token=_get("CLOUDFLARE_API_TOKEN"),
            gemini_code_model=_get("GEMINI_CODE_MODEL", required=False, default="gemini-2.5-pro"),
            gemini_image_model=_get("GEMINI_IMAGE_MODEL", required=False, default="gemini-2.5-flash-image"),
            gemini_cli_command=_get("GEMINI_CLI_COMMAND", required=False, default="gemini"),
            gemini_api_key=_get("GEMINI_API_KEY", required=False, default=None),
            gemini_telemetry_otlp_endpoint=_get("GEMINI_TELEMETRY_OTLP_ENDPOINT", required=False, default=None),
            gemini_image_cost_per_1k_tokens=image_cost_per_1k_tokens,
        )
