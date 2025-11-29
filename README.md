# landing-genie

AI-assisted landing page generator that uses Gemini CLI to create static marketing pages
and deploy them to Cloudflare Pages under subdomains of a domain you own.

## Requirements (answering the “what do I need?” list)

- Python `>=3.11` and `pip`
- Git (for cloning) and a POSIX shell (examples assume bash/zsh; PowerShell works with equivalent commands)
- A domain you own, already moved to Cloudflare (nameservers pointing at Cloudflare)
- Cloudflare account with:
  - Account ID (`CLOUDFLARE_ACCOUNT_ID`)
  - API token with **Pages:Edit** and **DNS:Edit** permissions for that account (`CLOUDFLARE_API_TOKEN`)
- Gemini CLI installed and configured (see https://geminicli.com/docs/get-started/deployment/). Text prompts run via the CLI using its own auth (login recommended); set `GEMINI_ALLOW_CLI_API_KEY=1` only if you want the CLI to use your API key as well.
- Billing-enabled `GEMINI_API_KEY` **only** for image generation (Python client). This key is not passed to the CLI by default so text requests stay on the non-billed flow.
- Optional: a preferred Gemini code and image model name (see `.env.example` defaults)

### Gemini image generation requires billing

- Google’s free Gemini tier only covers text models (plus very limited embeddings). Image models such as `gemini-2.5-flash-image`, `gemini-2.0-flash-image`, and earlier `preview-image` variants have **0** free daily/minute requests and **0** free input tokens.
- Calls to those image models on the free tier return `RESOURCE_EXHAUSTED` with `limit: 0` because no quota is allocated.
- To generate images you must have a billing-enabled Gemini API key (pay-as-you-go) or remaining GCP free-trial credits. Without billing, image generation is blocked even if text requests work.

## Setup

```bash
git clone <your-repo-url> landing-genie
cd landing-genie

python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate

pip install -e .

cp .env.example .env
```

Edit `.env`:
- `ROOT_DOMAIN=your-domain.tld` (the domain in Cloudflare)
- `CLOUDFLARE_ACCOUNT_ID=...`
- `CLOUDFLARE_API_TOKEN=...` (token with Pages+DNS edit)
- `GEMINI_CODE_MODEL=...` / `GEMINI_IMAGE_MODEL=...` (optional overrides)
- `GEMINI_CLI_COMMAND=gemini` (default: `gemini`; change if your CLI is named differently)
- `GEMINI_ALLOW_CLI_API_KEY=0` (default: `0`; set to `1` only if you want the CLI to consume `GEMINI_API_KEY`)
- `GEMINI_API_KEY=` (enable image generation via Python; not passed to the CLI unless `GEMINI_ALLOW_CLI_API_KEY=1`)
- `GEMINI_TELEMETRY_OTLP_ENDPOINT=` (optional OTLP collector endpoint; landing-genie sets this for CLI runs, while `.gemini/settings.json` keeps `otlpEndpoint` blank so ad-hoc CLI usage stays quiet)

## Quick start

```bash
landing-genie init

landing-genie new --prompt "Landing page for an AI habit tracking app" --suggested-subdomain "habitlab"
# Review locally, give feedback if needed, then deploy:
landing-genie deploy habitlab
# Skip image generation for a run:
landing-genie new --prompt "Landing page for an AI habit tracking app" --suggested-subdomain "habitlab" --no-images
```

With `GEMINI_API_KEY` set, `landing-genie new` will also render images for any `assets/*.png` placeholders it finds. Skip with `--no-images` or regenerate later with `landing-genie images <slug>` (add `--overwrite` to replace existing files).

### Tests (light, minimal tokens)

```bash
# Run all tests
pytest

# Run just the CLI smoke test (uses Gemini CLI with a tiny prompt)
pytest -s tests/test_gemini_cli.py

# Run just the image smoke test (uses GEMINI_API_KEY once)
pytest tests/test_image_generation.py
```

Notes:
- Tests load `.env` via `Config.load()`, so run from the repo root with your env set.
- The CLI test respects `GEMINI_ALLOW_CLI_API_KEY`; by default it strips `GEMINI_API_KEY` from the CLI env.
- The image test skips if `GEMINI_API_KEY` is unset; it writes the generated file under pytest’s temp dir (e.g., `/tmp/pytest-of-<user>/.../sites/image-smoke/assets/test.png`).

## Commands

- `landing-genie init`  
  Bootstrap config, validate environment, and ensure `sites/` exists.

- `landing-genie new`  
  Generate a new landing using Gemini CLI, serve it locally for review, and allow iterative refinements.

- `landing-genie deploy <slug>`  
  Deploy an existing landing under `sites/<slug>` to Cloudflare Pages, creating a dedicated Pages project named `lp-<slug>-<rootdomain>` (e.g., `lp-smart-forget-ailablife`) and attaching the custom subdomain on your root domain.

- `landing-genie images <slug>`  
  Generate images for an existing landing using your `GEMINI_API_KEY` (skips existing files unless `--overwrite` is passed).

- `landing-genie list`  
  List generated landings under `sites/`.

## Notes and tips

- The generated sites live under `sites/<slug>` as static assets. You can edit them manually before deploy.
- With `GEMINI_API_KEY` set, image files under `sites/<slug>/assets/` are generated via Gemini's image model after the page is created. Skip with `--no-images` or regenerate later with `landing-genie images <slug>` (add `--overwrite` to replace existing files).
- `GEMINI_API_KEY` is stripped from Gemini CLI subprocesses by default so text prompts use your CLI login. Set `GEMINI_ALLOW_CLI_API_KEY=1` if you intentionally want the CLI to use that key too.
- Prompts used for generation live under `prompts/`; adjust them to steer tone and structure.
- `.gemini/` holds Gemini CLI configs; keep it in sync with your model choices and auth method.
- Cloudflare must manage the DNS for your `ROOT_DOMAIN`; if nameservers are not pointed to Cloudflare, custom subdomains will not resolve.
- Deploys create a new Cloudflare Pages project per subdomain automatically; no need to pre-create one.

## Appendix: Gemini API key and billing

1) Create a Gemini API key  
- Go to https://aistudio.google.com/app/apikey (Google account required).  
- Click **Create API key**, choose or create a GCP project, and copy the key.  
- Export it in your shell: `export GEMINI_API_KEY=your_key_here` (or add to `.env`).

2) Enable billing for image generation  
- In the same API key dialog, click **Manage billing** (or open https://console.cloud.google.com/billing).  
- Attach a billing account to the project that owns the API key (free tier does not include image quota).  
- Confirm the Gemini API is enabled for that project (AI Studio enables it automatically; you can also check in GCP API Library).  
- Optional: set budgets/alerts in Cloud Billing to watch spend.

3) Verify access  
- Run any simple image call (e.g., `landing-genie images <slug>`) to confirm you don’t get `RESOURCE_EXHAUSTED` with `limit: 0`.  
- If you still see quota errors, ensure billing is active on the same project where the API key was created.

## Appendix: Cloudflare setup checklist

1) Move DNS to Cloudflare  
- Sign up/sign in to Cloudflare and add your domain.  
- Cloudflare scans existing DNS records; review and confirm (ensure A/AAAA/CNAME/MX/TXT records match your current registrar).  
- Cloudflare will show two nameservers (e.g., `emma.ns.cloudflare.com`, `ivan.ns.cloudflare.com`).  
- At your registrar (e.g., GoDaddy/Namecheap/Google Domains), replace existing nameservers with the two from Cloudflare.  
- Wait for propagation (often minutes, can be up to 24h). Your domain must now be “Active” in Cloudflare for Pages + DNS automation to work.

2) Cloudflare Pages projects are auto-created  
- landing-genie creates a new Pages project for each subdomain (pattern `lp-<slug>-<rootdomain>`). No manual project setup required.

3) Create an API token with scoped permissions  
- Dashboard: `My Profile` → `API Tokens` → `Create Token` → `Create Custom Token`.  
- Permissions:  
  - `Account` → `Cloudflare Pages` → `Edit`  
  - `Zone` → `DNS` → `Edit`  
- Account resources: Restrict to the target account (recommended) instead of “All accounts.”  
- Zone resources: Restrict to the specific domain (recommended) instead of “All zones.”  
- Save the token and set it as `CLOUDFLARE_API_TOKEN` in `.env`. Store it securely; you won’t see it again.

4) Confirm DNS and Pages readiness  
- In Cloudflare DNS, ensure your root domain records are present.  
- Custom subdomains created by this tool will be added as DNS records (via API) pointing to the Pages project created for that subdomain.  
- If nameservers aren’t pointed to Cloudflare, the automated DNS step will fail.
