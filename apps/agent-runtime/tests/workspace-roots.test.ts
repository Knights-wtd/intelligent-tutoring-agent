import { mapWorkspaceRoots } from "../src/runtime/workspace-roots";

describe("mapWorkspaceRoots", () => {
  it("maps Docker vault roots into the managed Windows host vault", () => {
    expect(mapWorkspaceRoots(
      ["/agent-vault/spaces/space-1/kb-1"],
      "E:\\repo\\.agent-data\\vault",
      "win32",
    )).toEqual(["E:\\repo\\.agent-data\\vault\\spaces\\space-1\\kb-1"]);
  });

  it.each([
    "/agent-vault/../outside",
    "/agent-vaultish/space-1",
    "C:\\Windows\\System32",
  ])("rejects workspace root %s outside the logical vault", root => {
    expect(() => mapWorkspaceRoots([root], "E:\\repo\\.agent-data\\vault", "win32"))
      .toThrow("Workspace root is outside the logical vault");
  });
});
