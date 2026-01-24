/**
 * Cloudflare Worker entrypoint for landing-genie contact form submissions.
 *
 * Accepts POST requests to `/api/contact` from any landing subdomain, formats the
 * submitted fields, and sends them to a configured inbox using Cloudflare Email
 * Routing. No submission data is stored.
 */

import { EmailMessage } from "cloudflare:email";

const CONTACT_ENDPOINT_PATHNAMES = ["/api/contact", "/api/contact/"];
const EMAIL_SUBJECT = "[Landing Lead] - New contact form submission";
const MAX_EMAIL_FIELD_COUNT = 80;
const MAX_FIELD_VALUE_LENGTH = 4000;
const SUBMISSION_QUERY_PARAM_NAME = "submitted";
const SUBMISSION_QUERY_PARAM_VALUE = "1";
const TURNSTILE_RESPONSE_FIELD_NAME = "cf-turnstile-response";
const LANDING_LEAD_DISPLAY_PREFIX = "Landing Lead";
const UNKNOWN_HOST_FALLBACK = "unknown-host";
const HOST_SUBDOMAIN_SEPARATOR = ".";
const EMPTY_STRING = "";
const MESSAGE_ID_DOMAIN_FALLBACK = "unknown-domain";
const AJAX_REQUEST_HEADER_NAME = "X-Requested-With";
const AJAX_REQUEST_HEADER_VALUE = "fetch";
const JSON_ACCEPT_HEADER_VALUE = "application/json";

const COMMON_EMAIL_FIELD_NAMES = [
  "email",
  "email_address",
  "emailAddress",
  "reply_to",
  "replyTo",
  "from",
];

const COMMON_NAME_FIELD_NAMES = [
  "name",
  "full_name",
  "fullName",
  "first_name",
  "firstName",
];

export default {
  /**
   * Cloudflare Worker fetch handler.
   *
   * Inputs:
   * - request: Incoming HTTP request from the browser form submission.
   * - env: Worker bindings and configuration vars (EMAIL, FROM_ADDRESS, TO_ADDRESS, ROOT_DOMAIN).
   *
   * Output:
   * - Response: 303 redirect on success, JSON error responses on failure.
   */
  async fetch(request, env) {
    try {
      return await handleRequest({ request, env });
    } catch (error) {
      logWorkerError("Unhandled worker error", error, {
        method: request.method,
        url: request.url,
      });
      const errorMessage = error instanceof Error ? error.message : String(error);
      return jsonResponse(
        500,
        {
          error: "Internal error while processing the contact form submission.",
          details: errorMessage,
        },
        { "Cache-Control": "no-store" },
      );
    }
  },
};

/**
 * Handle a single POST submission to the contact endpoint.
 */
async function handleRequest({ request, env }) {
  const url = new URL(request.url);
  if (!CONTACT_ENDPOINT_PATHNAMES.includes(url.pathname)) {
    return jsonResponse(404, { error: "Not found" });
  }

  if (request.method !== "POST") {
    return jsonResponse(405, { error: "Method not allowed" }, { Allow: "POST" });
  }

  const requestHost = normalizeHostHeader(request.headers.get("Host"));
  const rootDomain = normalizeRootDomain(env.ROOT_DOMAIN);
  if (!isHostAllowedForRootDomain({ requestHost, rootDomain })) {
    return jsonResponse(400, { error: "Invalid host for this handler." });
  }

  const submission = await parseSubmissionFromRequest({ request });

  if (isTurnstileEnabled(env)) {
    const turnstileToken = readSingleFieldValue(
      submission.fields,
      TURNSTILE_RESPONSE_FIELD_NAME,
    );
    if (!turnstileToken) {
      return jsonResponse(400, {
        error: "Turnstile token is required (missing cf-turnstile-response).",
      });
    }
    const verificationResult = await verifyTurnstileToken({
      token: turnstileToken,
      secretKey: env.TURNSTILE_SECRET_KEY,
      remoteIpAddress: request.headers.get("CF-Connecting-IP"),
    });
    if (!verificationResult.isVerified) {
      return jsonResponse(400, {
        error: "Turnstile verification failed.",
        details: verificationResult.errorMessages,
      });
    }
  }

  const fromAddress = normalizeEmailAddress(env.FROM_ADDRESS);
  if (!fromAddress) {
    return jsonResponse(500, {
      error: "Worker misconfiguration: FROM_ADDRESS is missing or invalid.",
    });
  }

  const toAddress = normalizeEmailAddress(env.TO_ADDRESS);
  if (!toAddress) {
    return jsonResponse(500, {
      error: "Worker misconfiguration: TO_ADDRESS is missing or invalid.",
    });
  }

  const displayName = buildFromDisplayName({ requestHost });
  const replyTo = deriveReplyToAddress(submission.fields);
  const senderName = deriveSenderName(submission.fields);

  const emailBody = buildEmailBody({
    submission,
    request,
    requestHost,
    senderName,
  });

  const rawEmail = buildRawEmailMessage({
    fromAddress,
    displayName,
    toAddress,
    subject: EMAIL_SUBJECT,
    replyToAddress: replyTo,
    bodyText: emailBody,
  });

  try {
    await env.EMAIL.send(new EmailMessage(fromAddress, toAddress, rawEmail));
  } catch (error) {
    logWorkerError("Email send failed", error, {
      fromAddress,
      toAddress,
      requestHost,
    });
    throw new Error("Email send failed.");
  }

  if (shouldReturnJsonResponse({ request })) {
    return jsonResponse(
      200,
      { ok: true },
      { "Cache-Control": "no-store" },
    );
  }

  const redirectUrl = buildSuccessRedirectUrl({ request, requestHost });
  return new Response(null, {
    status: 303,
    headers: {
      Location: redirectUrl,
      "Cache-Control": "no-store",
    },
  });
}

/**
 * Parse the incoming request body into structured submission fields.
 *
 * Supports:
 * - HTML form posts (multipart/form-data or application/x-www-form-urlencoded)
 * - JSON payloads (application/json)
 */
async function parseSubmissionFromRequest({ request }) {
  const contentType = request.headers.get("Content-Type") || EMPTY_STRING;
  const receivedAt = new Date().toISOString();

  if (contentType.includes("application/json")) {
    const parsedJson = await request.json().catch(() => null);
    const fields = new Map();
    if (parsedJson && typeof parsedJson === "object") {
      for (const [key, value] of Object.entries(parsedJson)) {
        appendFieldValues(fields, key, value);
      }
    }
    return { receivedAt, fields: clampAndSanitizeFields(fields) };
  }

  const parsedFormData = await request.formData().catch(() => null);
  if (!parsedFormData) {
    return { receivedAt, fields: new Map() };
  }

  const fields = new Map();
  for (const [key, value] of parsedFormData.entries()) {
    if (typeof value === "string") {
      appendFieldValues(fields, key, value);
      continue;
    }
    appendFieldValues(
      fields,
      key,
      `${value.name} (${value.type || "file"}, ${value.size} bytes)`,
    );
  }
  return { receivedAt, fields: clampAndSanitizeFields(fields) };
}

/**
 * Add one or many values to the fields map under the given key.
 */
function appendFieldValues(fields, key, value) {
  const fieldName = String(key || EMPTY_STRING).trim();
  if (!fieldName) return;

  const existing = fields.get(fieldName) || [];
  if (Array.isArray(value)) {
    for (const item of value) {
      existing.push(String(item));
    }
  } else if (value === null || value === undefined) {
    // Skip nullish values.
  } else if (typeof value === "object") {
    existing.push(JSON.stringify(value));
  } else {
    existing.push(String(value));
  }
  fields.set(fieldName, existing);
}

/**
 * Clamp the field count and value sizes, and sanitize text for safe output.
 */
function clampAndSanitizeFields(fields) {
  const entries = Array.from(fields.entries()).slice(0, MAX_EMAIL_FIELD_COUNT);
  const sanitized = new Map();
  for (const [key, values] of entries) {
    const safeKey = sanitizeSingleLineText(key);
    const safeValues = (values || []).map((value) =>
      sanitizeMultilineText(String(value)).slice(0, MAX_FIELD_VALUE_LENGTH),
    );
    sanitized.set(safeKey, safeValues);
  }
  return sanitized;
}

/**
 * Return true when Turnstile verification is configured.
 */
function isTurnstileEnabled(env) {
  return Boolean(String(env.TURNSTILE_SECRET_KEY || EMPTY_STRING).trim());
}

/**
 * Verify Turnstile tokens with Cloudflare's siteverify endpoint.
 */
async function verifyTurnstileToken({ token, secretKey, remoteIpAddress }) {
  const body = new URLSearchParams();
  body.set("secret", secretKey);
  body.set("response", token);
  if (remoteIpAddress) {
    body.set("remoteip", remoteIpAddress);
  }

  const response = await fetch(
    "https://challenges.cloudflare.com/turnstile/v0/siteverify",
    { method: "POST", body },
  );

  const data = await response.json().catch(() => ({}));
  return {
    isVerified: Boolean(data && data.success),
    errorMessages: Array.isArray(data["error-codes"]) ? data["error-codes"] : [],
  };
}

/**
 * Find a reply-to address from common email field names or first email-like value.
 */
function deriveReplyToAddress(fields) {
  const senderEmailAddress = findFirstEmailFieldValue(fields);
  return senderEmailAddress ? normalizeEmailAddress(senderEmailAddress) : EMPTY_STRING;
}

/**
 * Find a sender name from common name field names.
 */
function deriveSenderName(fields) {
  for (const candidateName of COMMON_NAME_FIELD_NAMES) {
    const value = readSingleFieldValue(fields, candidateName);
    if (value) return sanitizeSingleLineText(value);
  }
  return EMPTY_STRING;
}

/**
 * Return the first field value that looks like an email address.
 */
function findFirstEmailFieldValue(fields) {
  for (const candidateName of COMMON_EMAIL_FIELD_NAMES) {
    const value = readSingleFieldValue(fields, candidateName);
    if (value) return value;
  }

  for (const values of fields.values()) {
    for (const value of values || []) {
      if (looksLikeEmailAddress(value)) return value;
    }
  }
  return EMPTY_STRING;
}

/**
 * Read the first value for a given field name.
 */
function readSingleFieldValue(fields, fieldName) {
  const values = fields.get(fieldName);
  if (!values || !values.length) return EMPTY_STRING;
  return String(values[0] || EMPTY_STRING).trim();
}

/**
 * Basic email-shaped check to avoid rejecting unusual but valid addresses.
 */
function looksLikeEmailAddress(value) {
  const text = String(value || EMPTY_STRING).trim();
  if (!text) return false;
  return text.includes("@") && !text.includes(" ");
}

/**
 * Normalize and validate an email address string.
 */
function normalizeEmailAddress(value) {
  const emailAddress = String(value || EMPTY_STRING).trim();
  return emailAddress && looksLikeEmailAddress(emailAddress) ? emailAddress : EMPTY_STRING;
}

/**
 * Normalize the root domain for host checks.
 */
function normalizeRootDomain(value) {
  const rootDomain = String(value || EMPTY_STRING).trim().toLowerCase();
  return rootDomain || EMPTY_STRING;
}

/**
 * Normalize the Host header to lowercase.
 */
function normalizeHostHeader(value) {
  const host = String(value || EMPTY_STRING).trim().toLowerCase();
  return host || EMPTY_STRING;
}

/**
 * Ensure the request host matches the configured root domain or subdomain.
 */
function isHostAllowedForRootDomain({ requestHost, rootDomain }) {
  if (!rootDomain) return true;
  if (!requestHost) return false;
  if (requestHost === rootDomain) return true;
  return requestHost.endsWith(`${HOST_SUBDOMAIN_SEPARATOR}${rootDomain}`);
}

/**
 * Build the display name for the "From" header, including the hostname.
 */
function buildFromDisplayName({ requestHost }) {
  const hostLabel = requestHost || UNKNOWN_HOST_FALLBACK;
  return `${LANDING_LEAD_DISPLAY_PREFIX} (${hostLabel})`;
}

/**
 * Build the email body with context and all submitted fields.
 */
function buildEmailBody({ submission, request, requestHost, senderName }) {
  const url = new URL(request.url);
  const ipAddress = request.headers.get("CF-Connecting-IP") || EMPTY_STRING;
  const userAgent = request.headers.get("User-Agent") || EMPTY_STRING;
  const referer = request.headers.get("Referer") || EMPTY_STRING;

  const lines = [];
  lines.push("New landing form submission");
  lines.push(EMPTY_STRING);
  if (requestHost) lines.push(`Landing: https://${requestHost}`);
  lines.push(`Endpoint: ${url.pathname}`);
  lines.push(`Received: ${submission.receivedAt}`);
  if (ipAddress) lines.push(`IP: ${ipAddress}`);
  if (userAgent) lines.push(`User-Agent: ${sanitizeMultilineText(userAgent)}`);
  if (referer) lines.push(`Referer: ${sanitizeMultilineText(referer)}`);
  if (senderName) lines.push(`Sender name (best-effort): ${senderName}`);
  lines.push(EMPTY_STRING);
  lines.push("Fields:");

  for (const [key, values] of submission.fields.entries()) {
    const printableValues = (values || []).map((value) => sanitizeMultilineText(value));
    if (!printableValues.length) {
      lines.push(`- ${key}:`);
      continue;
    }
    if (printableValues.length === 1) {
      lines.push(`- ${key}: ${printableValues[0]}`);
      continue;
    }
    lines.push(`- ${key}:`);
    for (const value of printableValues) {
      lines.push(`  - ${value}`);
    }
  }

  return lines.join("\n");
}

/**
 * Build a raw RFC-822 formatted message to send via Email Routing.
 */
function buildRawEmailMessage({
  fromAddress,
  displayName,
  toAddress,
  subject,
  replyToAddress,
  bodyText,
}) {
  const safeDisplayName = sanitizeSingleLineText(displayName);
  const safeSubject = sanitizeSingleLineText(subject);
  const safeReplyToAddress = normalizeEmailAddress(replyToAddress);

  const lines = [];
  lines.push(`From: ${safeDisplayName} <${fromAddress}>`);
  lines.push(`To: <${toAddress}>`);
  lines.push(`Subject: ${safeSubject}`);
  if (safeReplyToAddress) {
    lines.push(`Reply-To: <${safeReplyToAddress}>`);
  }
  const now = new Date();
  const senderDomain = fromAddress.split("@")[1] || MESSAGE_ID_DOMAIN_FALLBACK;
  const messageId = `<${crypto.randomUUID()}@${senderDomain}>`;
  lines.push(`Date: ${now.toUTCString()}`);
  lines.push(`Message-ID: ${messageId}`);
  lines.push("X-Contact-Source: landing-genie");
  lines.push("MIME-Version: 1.0");
  lines.push("Content-Type: text/plain; charset=UTF-8");
  lines.push("Content-Transfer-Encoding: 8bit");
  lines.push(EMPTY_STRING);
  lines.push(bodyText);
  return lines.join("\r\n");
}

/**
 * Build a safe redirect URL back to the landing page.
 */
function buildSuccessRedirectUrl({ request, requestHost }) {
  const referer = request.headers.get("Referer") || EMPTY_STRING;
  const fallbackHost = requestHost || normalizeHostHeader(request.headers.get("Host"));
  const safeFallback = fallbackHost ? `https://${fallbackHost}/#contact` : "/";

  let redirectUrl;
  try {
    redirectUrl = referer ? new URL(referer) : new URL(safeFallback);
  } catch {
    redirectUrl = new URL(safeFallback);
  }

  const targetHost = normalizeHostHeader(redirectUrl.host);
  if (fallbackHost && targetHost && targetHost !== fallbackHost) {
    redirectUrl = new URL(safeFallback);
  }

  redirectUrl.searchParams.set(
    SUBMISSION_QUERY_PARAM_NAME,
    SUBMISSION_QUERY_PARAM_VALUE,
  );
  redirectUrl.hash = "contact";
  return redirectUrl.toString();
}

/**
 * Decide whether the caller expects a JSON response.
 *
 * Inputs:
 * - request: Incoming HTTP request.
 *
 * Output:
 * - boolean: True when JSON is requested (AJAX form submit).
 */
function shouldReturnJsonResponse({ request }) {
  const acceptHeader = request.headers.get("Accept") || EMPTY_STRING;
  if (acceptHeader.includes(JSON_ACCEPT_HEADER_VALUE)) {
    return true;
  }

  const requestHeader = request.headers.get(AJAX_REQUEST_HEADER_NAME) || EMPTY_STRING;
  if (requestHeader.toLowerCase() === AJAX_REQUEST_HEADER_VALUE) {
    return true;
  }

  return false;
}

/**
 * Sanitize a string for use in a single-line email header.
 */
function sanitizeSingleLineText(value) {
  return String(value || EMPTY_STRING).replace(/[\r\n]+/g, " ").trim();
}

/**
 * Sanitize multiline text for safe inclusion in the email body.
 */
function sanitizeMultilineText(value) {
  return String(value || EMPTY_STRING).replace(/\r/g, "").trim();
}

/**
 * Create a JSON response with common headers.
 */
function jsonResponse(statusCode, payload, headers = {}) {
  return new Response(JSON.stringify(payload, null, 2), {
    status: statusCode,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      ...headers,
    },
  });
}

/**
 * Log structured errors to Worker logs for debugging.
 */
function logWorkerError(message, error, context = {}) {
  const errorMessage = error instanceof Error ? error.message : String(error);
  const errorStack = error instanceof Error && error.stack ? error.stack : EMPTY_STRING;
  console.error(
    JSON.stringify({
      message,
      errorMessage,
      errorStack,
      context,
    }),
  );
}

export { buildFromDisplayName, buildRawEmailMessage, handleRequest, parseSubmissionFromRequest };
