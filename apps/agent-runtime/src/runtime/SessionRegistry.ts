import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { dirname } from "node:path";
import { randomUUID } from "node:crypto";

export interface RuntimeSessionRecord {
  session_id: string;
  provider: string;
  native_session_id: string;
  sequence: number;
  updated_at: string;
}

type SessionInput = Omit<RuntimeSessionRecord, "updated_at"> & { updated_at?: string };

interface PersistedRegistry {
  version: 1;
  sessions: RuntimeSessionRecord[];
}

export class SessionRegistry {
  private writeChain: Promise<void> = Promise.resolve();

  private constructor(
    private readonly statePath: string,
    private readonly sessions: Map<string, RuntimeSessionRecord>,
  ) {}

  static async open(statePath: string): Promise<SessionRegistry> {
    let persisted: PersistedRegistry = { version: 1, sessions: [] };
    try {
      persisted = JSON.parse(await readFile(statePath, "utf8")) as PersistedRegistry;
    } catch (error) {
      if (!isMissingFile(error)) throw error;
    }
    if (persisted.version !== 1 || !Array.isArray(persisted.sessions)) {
      throw new TypeError("Unsupported session registry format");
    }
    return new SessionRegistry(
      statePath,
      new Map(persisted.sessions.map(record => [record.session_id, validateRecord(record)])),
    );
  }

  get(sessionId: string): RuntimeSessionRecord | undefined {
    const record = this.sessions.get(sessionId);
    return record ? { ...record } : undefined;
  }

  list(): readonly RuntimeSessionRecord[] {
    return [...this.sessions.values()].map(record => ({ ...record }));
  }

  require(sessionId: string): RuntimeSessionRecord {
    const record = this.get(sessionId);
    if (!record) throw new Error(`Unknown Runtime session: ${sessionId}`);
    return record;
  }

  async upsert(input: SessionInput): Promise<RuntimeSessionRecord> {
    const record = validateRecord({ ...input, updated_at: input.updated_at ?? new Date().toISOString() });
    this.sessions.set(record.session_id, record);
    await this.persist();
    return { ...record };
  }

  async nextSequence(sessionId: string): Promise<number> {
    const current = this.require(sessionId);
    const next = { ...current, sequence: current.sequence + 1, updated_at: new Date().toISOString() };
    this.sessions.set(sessionId, next);
    await this.persist();
    return next.sequence;
  }

  private async persist(): Promise<void> {
    this.writeChain = this.writeChain.then(async () => {
      await mkdir(dirname(this.statePath), { recursive: true });
      const temporary = `${this.statePath}.${process.pid}.${randomUUID()}.tmp`;
      const body: PersistedRegistry = { version: 1, sessions: [...this.sessions.values()] };
      await writeFile(temporary, JSON.stringify(body, null, 2) + "\n", { encoding: "utf8", flag: "wx" });
      await rename(temporary, this.statePath);
    });
    await this.writeChain;
  }
}

function validateRecord(record: RuntimeSessionRecord): RuntimeSessionRecord {
  for (const key of ["session_id", "provider", "native_session_id", "updated_at"] as const) {
    if (typeof record[key] !== "string" || record[key].length === 0) throw new TypeError(`session.${key} is required`);
  }
  if (!Number.isSafeInteger(record.sequence) || record.sequence < 0) throw new TypeError("session.sequence must be a non-negative safe integer");
  return { ...record };
}

function isMissingFile(error: unknown): boolean {
  return typeof error === "object" && error !== null && "code" in error && error.code === "ENOENT";
}
