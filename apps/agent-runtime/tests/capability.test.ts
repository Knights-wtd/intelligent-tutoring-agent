import { signCapability, verifyCapability, CapabilityError } from "../src/security/capability";

const secret = "0123456789abcdef0123456789abcdef";
const now = new Date("2026-08-28T00:00:00Z");
const payload = {
  version: "1",
  user_id: "user-1",
  session_id: "session-1",
  grants: [{ knowledge_base_id: "kb-1", actions: ["read", "write"] as const }],
  tool_categories: ["vault", "web"] as const,
  vault_roots: ["C:/vault"],
  issued_at: "2026-08-27T23:59:00Z",
  expires_at: "2026-08-28T00:05:00Z",
  nonce: "nonce_0123456789abcdef",
};

describe("workspace capabilities", () => {
  it("verifies signature, expiry, session binding, grants and tool categories", () => {
    const token = signCapability(payload, secret);
    const capability = verifyCapability(token, { secret, sessionId: "session-1", now });
    expect(capability.requireGrant("kb-1", "write").knowledge_base_id).toBe("kb-1");
    expect(() => capability.requireGrant("kb-1", "delete")).toThrow(CapabilityError);
    expect(() => capability.requireTool("web")).not.toThrow();
    expect(() => capability.requireTool("shell")).toThrow(CapabilityError);
  });

  it("rejects tampering, expiration, wrong session and invalid nonce", () => {
    const token = signCapability(payload, secret);
    expect(() => verifyCapability(token + "x", { secret, sessionId: "session-1", now })).toThrow(CapabilityError);
    expect(() => verifyCapability(token, { secret, sessionId: "other", now })).toThrow(CapabilityError);
    expect(() => verifyCapability(token, { secret, sessionId: "session-1", now: new Date("2026-08-28T00:06:00Z") })).toThrow(CapabilityError);
    const invalidNonce = signCapability({ ...payload, nonce: "../bad" }, secret);
    expect(() => verifyCapability(invalidNonce, { secret, sessionId: "session-1", now })).toThrow(CapabilityError);
  });
});
