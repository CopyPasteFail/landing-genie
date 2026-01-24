"""Configuration loading and defaults."""

from __future__ import annotations
import os
from dataclasses import dataclass, fields
from typing import ClassVar, Literal, overload
from dotenv import load_dotenv

load_dotenv()

_REDACTED_VALUE = "<redacted>"


@dataclass
class Config:
    """Runtime configuration for landing-genie."""
    _secret_field_names: ClassVar[set[str]] = {"cf_api_token", "gemini_api_key"}
    root_domain: str
    cf_account_id: str
    cf_api_token: str
    lead_to_email: str | None
    gemini_code_model: str
    gemini_image_model: str
    gemini_cli_command: str
    gemini_api_key: str | None
    gemini_telemetry_otlp_endpoint: str | None
    gemini_image_cost_per_1k_tokens: float | None
    gemini_image_input_cost_per_1k_tokens: float | None

    def __repr__(self) -> str:
        """
        Return a redacted representation for tracebacks/logs.

        Inputs: the current Config instance.
        Output: a string representation with secret fields masked.
        Edge cases: None/empty secrets are shown as-is to aid debugging.
        """
        field_parts: list[str] = []
        for field_info in fields(self):
            value = getattr(self, field_info.name)
            if field_info.name in self._secret_field_names and value:
                display_value = repr(_REDACTED_VALUE)
            else:
                display_value = repr(value)
            field_parts.append(f"{field_info.name}={display_value}")
        return f"{self.__class__.__name__}({', '.join(field_parts)})"

    @classmethod
    def load(cls) -> "Config":
        """Load configuration from environment variables."""
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
            """Read an environment variable with optional defaults and validation."""
            value = os.getenv(name)
            if value is None:
                value = default
            if required and not value:
                raise RuntimeError(f"Missing required environment variable: {name}")
            return value

        image_cost_str = _get("GEMINI_IMAGE_OUTPUT_COST_PER_1K_TOKENS", required=False, default=None)
        image_input_cost_str = _get("GEMINI_IMAGE_INPUT_COST_PER_1K_TOKENS", required=False, default=None)
        image_cost_per_1k_tokens: float | None
        image_input_cost_per_1k_tokens: float | None
        if image_cost_str is None or image_cost_str == "":
            image_cost_per_1k_tokens = None
        else:
            try:
                image_cost_per_1k_tokens = float(image_cost_str)
            except ValueError:
                raise RuntimeError("Invalid GEMINI_IMAGE_OUTPUT_COST_PER_1K_TOKENS; must be a number (e.g. 0.03)")

        if image_input_cost_str is None or image_input_cost_str == "":
            image_input_cost_per_1k_tokens = None
        else:
            try:
                image_input_cost_per_1k_tokens = float(image_input_cost_str)
            except ValueError:
                raise RuntimeError(
                    "Invalid GEMINI_IMAGE_INPUT_COST_PER_1K_TOKENS; must be a number (e.g. 0.0003)"
                )

        return cls(
            root_domain=_get("ROOT_DOMAIN"),
            cf_account_id=_get("CLOUDFLARE_ACCOUNT_ID"),
            cf_api_token=_get("CLOUDFLARE_API_TOKEN"),
            lead_to_email=_get("LEAD_TO_EMAIL", required=False, default=None),
            gemini_code_model=_get("GEMINI_CODE_MODEL", required=False, default="gemini-2.5-pro"),
            gemini_image_model=_get("GEMINI_IMAGE_MODEL", required=False, default="gemini-2.5-flash-image"),
            gemini_cli_command=_get("GEMINI_CLI_COMMAND", required=False, default="gemini"),
            gemini_api_key=_get("GEMINI_API_KEY", required=False, default=None),
            gemini_telemetry_otlp_endpoint=_get("GEMINI_TELEMETRY_OTLP_ENDPOINT", required=False, default=None),
            gemini_image_cost_per_1k_tokens=image_cost_per_1k_tokens,
            gemini_image_input_cost_per_1k_tokens=image_input_cost_per_1k_tokens,
        )
