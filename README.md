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

### 1) Clone and prepare Python

```bash
git clone <your-repo-url> landing-genie
cd landing-genie

python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate

pip install -e .
```

### 2) Copy the sample environment file and fill in secrets
```bash
cp .env.example .env
```

Edit `.env`:
- `ROOT_DOMAIN=your-domain.tld` (the domain in Cloudflare)
- `CLOUDFLARE_ACCOUNT_ID=...`
- `CLOUDFLARE_API_TOKEN=...` (token with Pages+DNS edit)
- `GEMINI_CODE_MODEL=...` / `GEMINI_IMAGE_MODEL=...` (optional overrides)
- `GEMINI_IMAGE_COST_PER_1K_TOKENS=` (optional; USD price per 1,000 tokens for your chosen Gemini image model, see https://ai.google.dev/gemini-api/docs/pricing)
- `GEMINI_CLI_COMMAND=gemini` (default: `gemini`; change if your CLI is named differently)
- `GEMINI_ALLOW_CLI_API_KEY=0` (default: `0`; set to `1` only if you want the CLI to consume `GEMINI_API_KEY`)
- `GEMINI_API_KEY=` (enable image generation via Python; not passed to the CLI unless `GEMINI_ALLOW_CLI_API_KEY=1`)
- `GEMINI_TELEMETRY_OTLP_ENDPOINT=` (optional OTLP collector endpoint; landing-genie sets this for CLI runs, while `.gemini/settings.json` keeps `otlpEndpoint` blank so ad-hoc CLI usage stays quiet)

### 4) Prepare NVM

```bash
nvm install 20.19.4
source ~/.nvm/nvm.sh
nvm use 20.19.4

```

> **Node version auto-switching**  
> The repo pins a version of Node in `.nvmrc`.
> For bash shells, append this helper to `~/.bashrc`:
> ```bash
> cat <<'EOF' >> ~/.bashrc
> load-nvmrc() {
>   local nvmrc="$PWD/.nvmrc"
>   if [ -f "$nvmrc" ]; then
>     nvm use --silent >/dev/null 2>&1 || nvm install
>   fi
> }
> export PROMPT_COMMAND="load-nvmrc${PROMPT_COMMAND:+;$PROMPT_COMMAND}"
> load-nvmrc
> EOF
> ```

### 5) Deploy the generated public/ folder to Cloudflare Pages
Direct Upload via Wrangler

```bash
npm install -g wrangler@4.49.0
```


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

```bash
landing-genie images dronehit --overwrite --prompt "Landing page for an AI habit tracking app"
```

### Tests (light, minimal tokens)

```bash
# Run all tests
pytest

# Run just the CLI smoke test (uses Gemini CLI with a tiny prompt)
pytest -s tests/test_gemini_cli.py

# Run just the Cloudflare Pages helper tests (fully mocked; no network)
pytest tests/test_cloudflare_api.py

# Run just the image smoke test (uses GEMINI_API_KEY once)
pytest -s tests/test_image_generation.py
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

## TODO / roadmap

- When generating a new site, gather follow-up questions from Gemini CLI to refine drafts (e.g., target audience, whether the product exists or is WIP, tone preferences).
- In preview mode, let users click a text section to open a popup and submit free-text refinements (e.g., “make it longer,” “add slight humour”) applied to that section.

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

## Why we switched from the raw Cloudflare Pages API to Wrangler

### Summary
The first implementation tried to deploy files directly using Cloudflare’s low-level Pages API. That path looks simple on paper, but in reality it is under-documented, fragile, and extremely easy to break in subtle ways. After multiple failures and inconsistent responses from the API, the deployment flow was replaced with a stable, supported mechanism: invoking **Wrangler** to handle the upload.

This change made deployments reliable and dramatically reduced the amount of custom logic needed in the codebase.

---

### The core issues with the raw API

Cloudflare Pages exposes HTTP endpoints that *look* like they let you upload static assets directly, but these endpoints are not fully documented and appear to exist primarily for internal use by Wrangler. Because of that:

- Small mistakes in the POST body or multipart formatting cause silent or vague failures.
- The API often accepts a deployment but does *not* attach the uploaded files, leading to pages that exist in the dashboard but serve 404 or empty responses.
- Error messages are generic and do not point to what is actually wrong.
- The expected multipart field shapes differ from example to example, making debugging guesswork.

This makes it extremely brittle to reimplement the uploader.

---

### What specifically broke

1. **Incorrect multipart field naming**
   - The manifest maps file paths to content hashes.
   - Cloudflare expects each file upload part to use the *hash* as the field name, not the file path.
   - Our initial implementation sent files under their filenames (`index.html`, `styles.css`), so Cloudflare could not match any assets to the manifest.

2. **Undocumented internal endpoints**
   - Endpoints like `/pages/assets/upload`, `/pages/assets/upsert-hashes`, and `/deployments` have no stable public schema.
   - Different sources show inconsistent JSON formats.
   - Even minor mismatches caused Cloudflare to return “Request body is incorrect” or to create a deployment with no assets.

3. **Dashboard mismatch**
   - The dashboard UI showed a successful deployment and listed files.
   - But the underlying asset store did not receive the blobs, so visiting the site returned a blank/404 response.
   - This makes debugging even harder because the UI suggests everything is fine.

Overall: reimplementing this workflow manually is error-prone and not worth the ongoing maintenance.

---

### Why Wrangler solves all of it

Wrangler is Cloudflare’s official CLI tool, and it already implements the entire asset-upload pipeline correctly:

- It calculates hashes exactly as Cloudflare expects.
- It uploads blobs to the correct internal asset store.
- It creates deployments with the correct manifest format.
- It is stable, supported, and kept in sync with Cloudflare’s backend.
- If something breaks, Wrangler gives useful logs and is easy to run manually for debugging.

By shelling out to:

```bash
npx wrangler pages deploy <folder> --project-name=<name> --branch=main
```

the tool delegates all the fragile low-level upload logic to Cloudflare itself. Our app only needs to:

- Provide the folder path
- Set the correct environment variables
- Configure the custom domain afterward

No reverse-engineering, no guessing multipart structures, no manifest construction by hand.

---

### Result

Using Wrangler:

- Deployments are consistent and predictable.
- Every subdomain correctly serves its unique content.
- The codebase is simpler, smaller, and far easier to maintain.
- Cloudflare handles all the complexity of asset uploading.

This is why the project moved from raw API calls to a Wrangler-based deployment flow.

## Image Pricing Breakdown (Gemini Pro vs Flash)

> For up to date information see https://ai.google.dev/gemini-api/docs/pricing.

Google charges for images based on **output tokens**, not per-image.  
The formula is always:

Cost = (Output tokens / 1,000,000) × Model Price

Average token usage per image:
- 1K image (1024×1024): ~1,100–1,300 tokens
- 2K image (2048×2048): ~2,000–2,500 tokens
- 4K image (4096×4096): ~3,500–4,000 tokens

Model prices per 1M output tokens:
- **Gemini 3 Pro Image Preview**: $120 per 1M tokens
- **Gemini Flash Image Preview**: $40 per 1M tokens

Effective cost per image:
- **Gemini 3 Pro**
  - 1K/2K image ≈ $0.13–$0.14
  - 4K image ≈ $0.24–$0.48
- **Gemini Flash**
  - 1K/2K image ≈ $0.05
  - 4K image ≈ $0.12–$0.16

Flash is roughly **3 times cheaper** than Pro.

**Example for one 1K image with Pro:**
Tokens ≈ 1,200  
Cost = (1,200 / 1,000,000) × 120 = $0.144

**Example for one 1K image with Flash:**
Tokens ≈ 1,200  
Cost = (1,200 / 1,000,000) × 40 = $0.048


## Image Resolution and Control (1K, 2K, 4K)

What 1K / 2K / 4K means:
- **1K** → roughly 1024×1024 pixels
- **2K** → roughly 2048×2048 pixels
- **4K** → roughly 4096×4096 pixels

Higher resolution → more output tokens → higher cost.

Current Gemini image models **do not allow exact resolution control** like `width` and `height` parameters.  
You cannot explicitly set 1024×1024 or 2048×2048 via API.

You *can influence* resolution using prompt instructions:
- “Generate a square 4K image”
- “High-resolution portrait”
- “16:9 widescreen landscape”
- “Ultra-high-quality 2048 wide render”

But the model chooses the final size internally.

Only older legacy models allowed explicit resolution fields. New Gemini image models use semantic sizing:
- Ask for “4K” → returns a higher-res image  
- Ask for “square” → returns a square  
- Ask for “portrait” → returns vertical aspect  

For strict resolution control, you must resize after generation.
