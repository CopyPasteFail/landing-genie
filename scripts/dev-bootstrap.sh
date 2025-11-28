#!/usr/bin/env bash
set -e

python -m venv .venv
source .venv/bin/activate

pip install -e .

echo "Created .venv and installed landing-genie in editable mode."
echo "Next steps:"
echo "  cp .env.example .env"
echo "  edit .env"
echo "  gemini login"
echo "  landing-genie init"
