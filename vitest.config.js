import { defineWorkersConfig } from "@cloudflare/vitest-pool-workers/config";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";

const repositoryRoot = fileURLToPath(new URL(".", import.meta.url));
const emailStubPath = resolve(
  repositoryRoot,
  "cloudflare/contact-form-worker/tests/email-stub.js",
);

export default defineWorkersConfig({
  resolve: {
    alias: {
      "cloudflare:email": emailStubPath,
    },
  },
  test: {
    include: ["cloudflare/contact-form-worker/tests/**/*.test.js"],
    poolOptions: {
      workers: {
        wrangler: { configPath: "./cloudflare/contact-form-worker/wrangler.test.toml" },
      },
    },
  },
});
