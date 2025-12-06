from __future__ import annotations

import http.server
import json
import re
import socketserver
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from threading import Thread
from typing import Any, TypedDict, cast
from urllib.parse import urlparse

from .config import Config
from .gemini_runner import refine_site
from .image_generator import ensure_placeholder_assets
from .site_paths import normalize_site_dir

# Track running preview servers so we can reuse an existing one instead of
# attempting to bind the same port again.


@dataclass
class _ServerState:
    httpd: socketserver.TCPServer
    thread: Thread
    slug: str
    debug: bool
    project_root: Path
    config: Config | None
    port: int


_SERVERS: dict[int, _ServerState] = {}


class ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True


class _RefinePayload(TypedDict, total=False):
    instruction: str
    sectionText: str
    sectionLabel: str


def _stop_server(port: int) -> None:
    server_info = _SERVERS.pop(port, None)
    if not server_info:
        return
    server_info.httpd.shutdown()
    server_info.httpd.server_close()
    server_info.thread.join(timeout=1)


def _configs_match(first: Config | None, second: Config | None) -> bool:
    if first is None and second is None:
        return True
    if first is None or second is None:
        return False
    return first == second


def _inject_preview_layer(html: str) -> str:
    overlay = """
<style id="landing-genie-preview-style">
  :root { --lg-accent: #7c3aed; --lg-bg: rgba(17, 24, 39, 0.75); --lg-panel: #0f172a; --lg-text: #e2e8f0; --lg-muted: #94a3b8; }
  [data-lg-previewable] { position: relative; }
  [data-lg-previewable]:hover { outline: 2px dashed var(--lg-accent); outline-offset: 4px; cursor: pointer; }
  [data-lg-previewable]::after { content: "Refine"; position: absolute; top: 6px; right: 8px; background: var(--lg-accent); color: #fff; font-size: 11px; padding: 2px 8px; border-radius: 999px; opacity: 0; transition: opacity 120ms ease; pointer-events: none; }
  [data-lg-previewable]:hover::after { opacity: 1; }
  #lg-preview-hint { position: fixed; bottom: 14px; right: 14px; background: var(--lg-bg); color: var(--lg-text); padding: 10px 14px; border-radius: 12px; font-size: 13px; z-index: 2147483000; box-shadow: 0 12px 40px rgba(0,0,0,0.35); backdrop-filter: blur(10px); display: flex; align-items: center; gap: 8px; }
  #lg-preview-hint button { background: transparent; border: none; color: var(--lg-muted); cursor: pointer; }
  #lg-preview-modal { position: fixed; inset: 0; background: rgba(15,23,42,0.65); display: none; align-items: center; justify-content: center; z-index: 2147483001; padding: 24px; }
  #lg-preview-modal.lg-open { display: flex; }
  #lg-preview-modal .lg-box { background: var(--lg-panel); color: var(--lg-text); width: min(720px, 100%); border-radius: 16px; padding: 20px; box-shadow: 0 24px 80px rgba(0,0,0,0.45); border: 1px solid rgba(255,255,255,0.08); }
  #lg-preview-modal .lg-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
  #lg-preview-modal .lg-header h3 { margin: 0; font-size: 18px; }
  #lg-preview-modal .lg-close { background: transparent; border: none; color: var(--lg-text); font-size: 18px; cursor: pointer; }
  #lg-preview-modal .lg-body { display: grid; gap: 10px; }
  #lg-preview-modal .lg-body label { font-size: 13px; color: var(--lg-muted); }
  #lg-preview-modal .lg-body textarea { width: 100%; min-height: 120px; border-radius: 10px; border: 1px solid rgba(255,255,255,0.08); background: rgba(255,255,255,0.05); color: var(--lg-text); padding: 10px; resize: vertical; }
  #lg-preview-modal .lg-body .lg-selection { background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); border-radius: 10px; padding: 10px; font-size: 13px; max-height: 180px; overflow: auto; white-space: pre-wrap; }
  #lg-preview-modal .lg-footer { display: flex; justify-content: space-between; align-items: center; margin-top: 6px; gap: 10px; }
  #lg-preview-modal .lg-footer small { color: var(--lg-muted); }
  #lg-preview-modal .lg-footer button { background: var(--lg-accent); color: #fff; border: none; border-radius: 10px; padding: 10px 16px; cursor: pointer; font-weight: 600; }
  #lg-preview-modal .lg-footer button[disabled] { opacity: 0.6; cursor: not-allowed; }
</style>
<script id="landing-genie-preview-script">
(() => {
  if (window.__LANDING_GENIE_PREVIEW__) return;
  window.__LANDING_GENIE_PREVIEW__ = true;
  const onReady = (fn) => {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn);
    } else {
      fn();
    }
  };
  const selectors = ["header", "section", "article", ".hero", ".problem", ".solution", ".features", ".feature", ".social-proof", ".contact", "main"];

  const hint = document.createElement("div");
  hint.id = "lg-preview-hint";
  hint.innerHTML = '<span>Preview mode: click any text section to refine</span><button type="button" aria-label="Hide preview hint">×</button>';
  hint.querySelector("button")?.addEventListener("click", () => hint.remove());
  onReady(() => document.body.appendChild(hint));

  const modal = (() => {
    const root = document.createElement("div");
    root.id = "lg-preview-modal";
    root.innerHTML = `
      <div class="lg-box">
        <div class="lg-header">
          <h3>Refine section</h3>
          <button class="lg-close" aria-label="Close">×</button>
        </div>
        <div class="lg-body">
          <div>
            <label for="lg-instruction">What should change?</label>
            <textarea id="lg-instruction" placeholder="e.g., make the headline punchier with a hint of humour"></textarea>
          </div>
          <div>
            <label>Selected text</label>
            <div class="lg-selection" id="lg-selection"></div>
          </div>
        </div>
        <div class="lg-footer">
          <small id="lg-status"></small>
          <div style="display:flex; gap:8px; align-items:center;">
            <button type="button" id="lg-cancel">Cancel</button>
            <button type="button" id="lg-apply">Apply refinement</button>
          </div>
        </div>
      </div>`;
    const close = () => root.classList.remove("lg-open");
    root.querySelector(".lg-close")?.addEventListener("click", close);
    root.querySelector("#lg-cancel")?.addEventListener("click", close);
    root.addEventListener("click", (event) => {
      if (event.target === root) {
        close();
      }
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") close();
    });
    onReady(() => document.body.appendChild(root));
    return {
      root,
      close,
      instruction: () => root.querySelector("#lg-instruction"),
      selection: () => root.querySelector("#lg-selection"),
      status: () => root.querySelector("#lg-status"),
      applyButton: () => root.querySelector("#lg-apply"),
      current: null,
      open(payload) {
        const instructionField = this.instruction();
        const selection = this.selection();
        const heading = this.root.querySelector(".lg-header h3");
        this.current = { text: payload.text, label: payload.label };
        if (heading) {
          heading.textContent = payload.label ? `Refine: ${payload.label}` : "Refine section";
        }
        selection.textContent = payload.text || "(no text found in this section)";
        instructionField.value = "";
        this.setStatus("Describe how to adjust this section.");
        this.setLoading(false);
        this.root.classList.add("lg-open");
        setTimeout(() => instructionField.focus(), 50);
      },
      setStatus(message) {
        const node = this.status();
        if (node) node.textContent = message;
      },
      setLoading(isLoading) {
        const button = this.applyButton();
        if (!button) return;
        button.disabled = isLoading;
        button.textContent = isLoading ? "Applying..." : "Apply refinement";
      },
    };
  })();

  function normalizeText(text) {
    return (text || "").replace(/\\s+/g, " ").trim();
  }

  function deriveLabel(element) {
    const heading = element.querySelector("h1, h2, h3, h4, h5");
    if (heading?.innerText) return normalizeText(heading.innerText);
    if (element.id) return element.id;
    const className = normalizeText(element.className || "").split(" ").slice(0, 2).join(" ");
    return className || element.tagName.toLowerCase();
  }

  function gatherPreviewables() {
    selectors.forEach((selector) => {
      document.querySelectorAll(selector).forEach((el) => {
        if (el.dataset.lgPreviewable) return;
        if (["FORM", "INPUT", "TEXTAREA", "BUTTON", "SELECT", "OPTION"].includes(el.tagName)) return;
        if (el.closest("#lg-preview-modal")) return;
        const snippet = normalizeText(el.innerText || "");
        if (!snippet || snippet.length < 12) return;
        el.dataset.lgPreviewable = "1";
        el.dataset.lgPreviewText = snippet.slice(0, 1600);
        el.dataset.lgPreviewLabel = deriveLabel(el);
      });
    });
  }

  gatherPreviewables();

  async function sendRefinement(payload) {
    const response = await fetch("/__preview/refine", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.error || "Refinement failed. Please try again.");
    }
    return data;
  }

  document.addEventListener("click", (event) => {
    if (event.target.closest("#lg-preview-modal")) return;
    const target = event.target.closest("[data-lg-previewable]");
    if (!target) return;
    const text = target.dataset.lgPreviewText || normalizeText(target.innerText || "");
    const label = target.dataset.lgPreviewLabel || deriveLabel(target);
    modal.open({ text, label });
    event.preventDefault();
  });

  modal.applyButton()?.addEventListener("click", async () => {
    const instructionField = modal.instruction();
    const instruction = normalizeText(instructionField?.value || "");
    if (!instruction) {
      modal.setStatus("Please describe how to adjust this section.");
      instructionField?.focus();
      return;
    }
    modal.setLoading(true);
    modal.setStatus("Applying refinement via Gemini...");
    try {
      await sendRefinement({
        instruction,
        sectionText: modal.current?.text || "",
        sectionLabel: modal.current?.label || "selected section",
      });
      modal.setStatus("Updated. Reloading preview...");
      setTimeout(() => window.location.reload(), 900);
    } catch (error) {
      modal.setStatus(error.message || "Something went wrong.");
    } finally {
      modal.setLoading(false);
    }
  });
})();
</script>
"""
    match = re.search(r"</body\s*>", html, flags=re.IGNORECASE)
    if match:
        return html[: match.start()] + overlay + html[match.start() :]
    return html + overlay


def _build_feedback(section_label: str, section_text: str, instruction: str) -> str:
    text = (section_text or "").strip()
    if len(text) > 1600:
        text = text[:1600] + "..."
    lines = [
        f"Refine the '{section_label or 'selected'}' section based on the user's preview feedback.",
        "Existing copy:",
        text or "(no text supplied from the preview selection)",
        "",
        f"Requested refinement: {instruction}",
        "Make focused edits to this section only; preserve structure, layout, assets, and other sections.",
    ]
    return "\n".join(lines)


def serve_local(
    slug: str,
    project_root: Path,
    config: Config | None = None,
    port: int = 4173,
    debug: bool = False,
) -> str:
    site_dir = normalize_site_dir(slug, project_root)
    if not site_dir.exists():
        raise FileNotFoundError(f"Site directory not found: {site_dir}")

    existing = _SERVERS.get(port)
    if existing:
        if (
            existing.slug == slug
            and existing.debug == debug
            and existing.project_root == project_root
            and _configs_match(existing.config, config)
            and existing.thread.is_alive()
        ):
            return f"http://localhost:{existing.port}"
        _stop_server(port)

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=str(site_dir), **kwargs)

        def log_message(self, format: str, *args: Any) -> None:
            # Only log errors unless debug is enabled.
            if not debug:
                try:
                    status = int(args[1])
                except (IndexError, ValueError, TypeError):
                    status = None
                if status is None or status < 400:
                    return
            super().log_message(format, *args)

        def _serve_html(self, write_body: bool = True) -> None:
            parsed = urlparse(self.path)
            requested = parsed.path or "/"
            relative = "index.html" if requested in {"/", ""} else requested.lstrip("/")
            target = (site_dir / relative).resolve()
            try:
                target.relative_to(site_dir)
            except ValueError:
                self.send_error(HTTPStatus.NOT_FOUND, "Not found")
                return
            if not target.exists() or target.is_dir():
                self.send_error(HTTPStatus.NOT_FOUND, "Not found")
                return
            try:
                html = target.read_text(encoding="utf-8")
            except Exception:
                self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Failed to read page")
                return
            injected = _inject_preview_layer(html)
            data = injected.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if write_body:
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    # Client closed the connection before we finished writing; ignore quietly.
                    if debug:
                        print("[Preview] Client disconnected before response body was sent.")
                    return

        def do_HEAD(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path.endswith(".html") or parsed.path in {"/", ""}:
                return self._serve_html(write_body=False)
            return super().do_HEAD()

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path.endswith(".html") or parsed.path in {"/", ""}:
                return self._serve_html(write_body=True)
            return super().do_GET()

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path != "/__preview/refine":
                self.send_error(HTTPStatus.NOT_FOUND, "Endpoint not found")
                return
            try:
                length = int(self.headers.get("Content-Length") or "0")
            except ValueError:
                length = 0
            raw_body = self.rfile.read(length)
            payload: _RefinePayload = {}
            try:
                decoded_body: object = json.loads(raw_body.decode("utf-8")) if raw_body else {}
                if isinstance(decoded_body, dict):
                    payload = cast(_RefinePayload, decoded_body)
            except json.JSONDecodeError:
                payload = {}

            instruction = str(payload.get("instruction", "")).strip()
            section_text = str(payload.get("sectionText", "")).strip()
            section_label = str(payload.get("sectionLabel", "selected section")).strip() or "selected section"

            if not instruction:
                self._json_response(HTTPStatus.BAD_REQUEST, {"error": "Instruction is required"})
                return

            feedback = _build_feedback(section_label=section_label, section_text=section_text, instruction=instruction)
            try:
                active_config = config or Config.load()
                refine_site(slug=slug, feedback=feedback, project_root=project_root, config=active_config, debug=debug)
                ensure_placeholder_assets(slug=slug, project_root=project_root)
            except Exception as exc:  # noqa: BLE001
                if debug:
                    print(f"[preview] Refinement failed: {exc}")
                self._json_response(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
                return

            self._json_response(HTTPStatus.OK, {"status": "ok"})

        def _json_response(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    # Bind explicitly to localhost so the preview server is not exposed on
    # all network interfaces.
    httpd = ReusableTCPServer(("127.0.0.1", port), Handler)
    bound_port = httpd.server_address[1]

    def _run() -> None:
        if debug:
            print(f"Serving {site_dir} at http://localhost:{bound_port}")
        httpd.serve_forever()

    thread = Thread(target=_run, daemon=True)
    thread.start()
    _SERVERS[bound_port] = _ServerState(
        httpd=httpd,
        thread=thread,
        slug=slug,
        debug=debug,
        project_root=project_root,
        config=config,
        port=bound_port,
    )
    return f"http://localhost:{bound_port}"
