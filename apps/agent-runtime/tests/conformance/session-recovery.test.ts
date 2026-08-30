jest.mock(
  "../../src/claudian/src/providers/claude/history/sdkSessionPaths",
  () => ({
    encodeVaultPathForSDK: (value: string) => value,
    getSDKProjectsPath: () => "unused",
    isValidSessionId: () => true,
  }),
);

import {
  type ClaudeSessionTimeCandidate,
  selectClaudeSessionRecoveryCandidate,
} from "../../src/claudian/src/providers/claude/history/ClaudeSessionRecovery";

const candidates: ClaudeSessionTimeCandidate[] = [
  {
    sessionId: "closest-start-wrong-end",
    firstTimestamp: 1_200,
    lastTimestamp: 40_000,
    hasAssistantMessage: true,
  },
  {
    sessionId: "matching-session",
    firstTimestamp: 1_900,
    lastTimestamp: 10_500,
    hasAssistantMessage: true,
  },
];

describe("Claudian session recovery conformance", () => {
  it("uses both creation and activity time to identify a unique transcript", () => {
    expect(selectClaudeSessionRecoveryCandidate(candidates, {
      createdAt: 1_000,
      lastActivityAt: 10_000,
    })).toBe("matching-session");
  });

  it("refuses a temporally ambiguous transcript match", () => {
    expect(selectClaudeSessionRecoveryCandidate([
      {
        sessionId: "first",
        firstTimestamp: 1_100,
        lastTimestamp: 10_100,
        hasAssistantMessage: true,
      },
      {
        sessionId: "second",
        firstTimestamp: 1_200,
        lastTimestamp: 10_200,
        hasAssistantMessage: true,
      },
    ], {
      createdAt: 1_000,
      lastActivityAt: 10_000,
    })).toBeNull();
  });
});
