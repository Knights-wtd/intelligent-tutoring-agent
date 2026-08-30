import { WebFetchTool } from "../src/tools/web/WebFetchTool";
import { WebSearchTool } from "../src/tools/web/WebSearchTool";
import { SsrfGuard } from "../src/security/ssrf";

describe("public web tools", () => {
  it("allows more than twenty sequential public fetches without a cumulative cap", async () => {
    const requests: string[] = [];
    const web = new WebFetchTool({
      guard: new SsrfGuard(async () => ["93.184.216.34"]),
      transport: async request => {
        requests.push(request.url.toString());
        expect(request.addresses).toEqual(["93.184.216.34"]);
        return { status: 200, headers: { "content-type": "text/plain" }, body: Buffer.from("ok") };
      },
    });
    for (let index = 0; index < 25; index += 1) await web.fetch(`https://public.example/${index}`);
    expect(requests).toHaveLength(25);
  });

  it("revalidates every redirect and blocks redirect-to-private", async () => {
    const web = new WebFetchTool({
      guard: new SsrfGuard(async hostname => hostname === "public.example" ? ["93.184.216.34"] : ["127.0.0.1"]),
      transport: async () => ({ status: 302, headers: { location: "http://internal.example/secret" }, body: Buffer.alloc(0) }),
    });
    await expect(web.fetch("https://public.example/start")).rejects.toMatchObject({ code: "ssrf_blocked" });
  });

  it("does not impose a fixed search result count", async () => {
    const search = new WebSearchTool(async () => Array.from({ length: 40 }, (_, index) => ({ title: `r${index}`, url: `https://example.com/${index}`, snippet: "x" })));
    await expect(search.search("topic")).resolves.toHaveLength(40);
  });
});
