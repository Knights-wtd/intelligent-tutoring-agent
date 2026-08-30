import { SsrfGuard, SsrfBlockedError } from "../src/security/ssrf";

describe("SsrfGuard", () => {
  it.each(["http://127.0.0.1/x", "http://169.254.169.254/latest/meta-data", "http://[::1]/x", "file:///etc/passwd"])(
    "blocks private or unsupported target %s",
    async url => expect(new SsrfGuard().resolve(url)).rejects.toBeInstanceOf(SsrfBlockedError),
  );

  it("rejects a hostname if any A or AAAA answer is non-public", async () => {
    const guard = new SsrfGuard(async () => ["93.184.216.34", "10.0.0.7"]);
    await expect(guard.resolve("https://example.test/x")).rejects.toMatchObject({ code: "ssrf_blocked" });
  });
});
