import { describe, expect, it, vi } from "vitest";

import {
  buildFromDisplayName,
  buildRawEmailMessage,
  handleRequest,
} from "../src/index.js";

const ROOT_DOMAIN = "example.com";
const FROM_ADDRESS = "leads@example.com";
const TO_ADDRESS = "dest@example.com";
const HOST = "alpha.example.com";

function createEnv() {
  return {
    ROOT_DOMAIN,
    FROM_ADDRESS,
    TO_ADDRESS,
    EMAIL: { send: vi.fn() },
  };
}

describe("contact form worker", () => {
  it("builds a display name that includes the host", () => {
    const displayName = buildFromDisplayName({ requestHost: HOST });
    expect(displayName).toBe("Landing Lead (alpha.example.com)");
  });

  it("builds the raw email with the fixed subject", () => {
    const rawEmail = buildRawEmailMessage({
      fromAddress: FROM_ADDRESS,
      displayName: "Landing Lead (alpha.example.com)",
      toAddress: TO_ADDRESS,
      subject: "[Landing Lead] - New contact form submission",
      replyToAddress: "sender@example.com",
      bodyText: "Hello there",
    });

    expect(rawEmail).toContain("Subject: [Landing Lead] - New contact form submission");
    expect(rawEmail).toContain("From: Landing Lead (alpha.example.com) <leads@example.com>");
    expect(rawEmail).toContain("Reply-To: <sender@example.com>");
  });

  it("accepts a submission, sends an email, and redirects back", async () => {
    const env = createEnv();
    const request = new Request("https://alpha.example.com/api/contact", {
      method: "POST",
      headers: {
        Host: HOST,
        "Content-Type": "application/x-www-form-urlencoded",
      },
      body: "name=Test%20User&email=test@example.com&message=Hello",
    });

    const response = await handleRequest({ request, env });

    expect(response.status).toBe(303);
    expect(env.EMAIL.send).toHaveBeenCalledTimes(1);
    expect(response.headers.get("Location")).toContain("submitted=1");
    expect(response.headers.get("Location")).toContain("#contact");
  });

  it("returns JSON success when requested by the client", async () => {
    const env = createEnv();
    const request = new Request("https://alpha.example.com/api/contact", {
      method: "POST",
      headers: {
        Host: HOST,
        Accept: "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
      },
      body: "name=Test%20User&email=test@example.com&message=Hello",
    });

    const response = await handleRequest({ request, env });
    const payload = await response.json();

    expect(response.status).toBe(200);
    expect(payload).toEqual({ ok: true });
  });

  it("rejects hosts outside the configured root domain", async () => {
    const env = createEnv();
    const request = new Request("https://evil.example.net/api/contact", {
      method: "POST",
      headers: {
        Host: "evil.example.net",
        "Content-Type": "application/x-www-form-urlencoded",
      },
      body: "email=test@example.com",
    });

    const response = await handleRequest({ request, env });

    expect(response.status).toBe(400);
  });
});
