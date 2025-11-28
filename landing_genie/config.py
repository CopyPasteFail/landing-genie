from __future__ import annotations
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    root_domain: str
    cf_account_id: str
    cf_api_token: str
    cf_pages_project: str
    gemini_code_model: str
    gemini_image_model: str
    gemini_cli_command: str

    @classmethod
    def load(cls) -> "Config":
        def _get(name: str, required: bool = True, default: str | None = None) -> str:
            value = os.getenv(name, default)
            if required and not value:
                raise RuntimeError(f"Missing required environment variable: {name}")
            return value or ""

        return cls(
            root_domain=_get("ROOT_DOMAIN"),
            cf_account_id=_get("CLOUDFLARE_ACCOUNT_ID"),
            cf_api_token=_get("CLOUDFLARE_API_TOKEN"),
            cf_pages_project=_get("CLOUDFLARE_PAGES_PROJECT"),
            gemini_code_model=_get("GEMINI_CODE_MODEL", required=False, default="gemini-2.5-pro"),
            gemini_image_model=_get("GEMINI_IMAGE_MODEL", required=False, default="gemini-3-pro-image"),
            gemini_cli_command=_get("GEMINI_CLI_COMMAND", required=False, default="gemini"),
        )
