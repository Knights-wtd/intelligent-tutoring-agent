const SECRET_KEY = /(authorization|api[-_]?key|token|secret|password|cookie)/i;

export function redactEnvironment(environment: Readonly<Record<string, string | undefined>>): Record<string, string> {
  return Object.fromEntries(Object.entries(environment).map(([key, value]) => [key, SECRET_KEY.test(key) ? "[REDACTED]" : value ?? ""]));
}

export function redactText(value: string, secrets: readonly string[]): string {
  return secrets.filter(Boolean).reduce((text, secret) => text.split(secret).join("[REDACTED]"), value);
}
