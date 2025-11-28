# landing-genie

AI-assisted landing page generator that uses Gemini CLI to create static marketing pages
and deploy them to Cloudflare Pages under subdomains of a domain you own.

## Requirements (answering the “what do I need?” list)

- Python `>=3.11` and `pip`
- Git (for cloning) and a POSIX shell (examples assume bash/zsh; PowerShell works with equivalent commands)
- A domain you own, already moved to Cloudflare (nameservers pointing at Cloudflare)
- Cloudflare account with:
  - Account ID and Pages project name ready (`CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_PAGES_PROJECT`)
  - API token with **Pages:Edit** and **DNS:Edit** permissions for that account (`CLOUDFLARE_API_TOKEN`)
- Gemini CLI installed and configured (see https://geminicli.com/docs/get-started/deployment/)
  - Use CLI with Google account login to consume included quota, or
  - Use CLI with a Gemini API key exported as `GEMINI_API_KEY`
- Optional: a preferred Gemini code and image model name (see `.env.example` defaults)

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
- `CLOUDFLARE_PAGES_PROJECT=...` (existing or new Pages project)
- `GEMINI_CODE_MODEL=...` / `GEMINI_IMAGE_MODEL=...` (optional overrides)
- `GEMINI_CLI_COMMAND=gemini` (change if your CLI is named differently)

If using an API key instead of CLI login, export `GEMINI_API_KEY` in your shell.

## Quick start

```bash
landing-genie init

landing-genie new --prompt "Landing page for an AI habit tracking app" --suggested-subdomain "habitlab"
# Review locally, give feedback if needed, then deploy:
landing-genie deploy habitlab
```

## Commands

- `landing-genie init`  
  Bootstrap config, validate environment, and ensure `sites/` exists.

- `landing-genie new`  
  Generate a new landing using Gemini CLI, serve it locally for review, and allow iterative refinements.

- `landing-genie deploy <slug>`  
  Deploy an existing landing under `sites/<slug>` to Cloudflare Pages and attach the custom subdomain on your root domain. (Currently a stub that prints what would be deployed—fill in Cloudflare API or wrangler steps.)

- `landing-genie list`  
  List generated landings under `sites/`.

## Notes and tips

- The generated sites live under `sites/<slug>` as static assets. You can edit them manually before deploy.
- Prompts used for generation live under `prompts/`; adjust them to steer tone and structure.
- `.gemini/` holds Gemini CLI configs; keep it in sync with your model choices and auth method.
- Cloudflare must manage the DNS for your `ROOT_DOMAIN`; if nameservers are not pointed to Cloudflare, custom subdomains will not resolve.
- `deploy` and `ensure_custom_domain` are scaffolds; wire them to the Cloudflare Pages API or wrangler when you’re ready to ship for real.

## Appendix: Cloudflare setup checklist

1) Move DNS to Cloudflare  
- Sign up/sign in to Cloudflare and add your domain.  
- Cloudflare scans existing DNS records; review and confirm (ensure A/AAAA/CNAME/MX/TXT records match your current registrar).  
- Cloudflare will show two nameservers (e.g., `emma.ns.cloudflare.com`, `ivan.ns.cloudflare.com`).  
- At your registrar (e.g., GoDaddy/Namecheap/Google Domains), replace existing nameservers with the two from Cloudflare.  
- Wait for propagation (often minutes, can be up to 24h). Your domain must now be “Active” in Cloudflare for Pages + DNS automation to work.

2) Create a Cloudflare Pages project (one-time)  
- In Cloudflare dashboard: `Workers & Pages` → `Create application` → `Pages project`.  
- Choose a project name (use the same value for `CLOUDFLARE_PAGES_PROJECT`). You can start with “Direct Upload” and skip connecting a repo for now.  
- Note your Cloudflare Account ID from the overview URL or the dashboard (set `CLOUDFLARE_ACCOUNT_ID`).

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
- Custom subdomains created by this tool will be added as DNS records (via API) pointing to your Pages project.  
- If nameservers aren’t pointed to Cloudflare, the automated DNS step will fail.
