export interface WebSearchResult { title: string; url: string; snippet: string; }
export type WebSearchAdapter = (query: string, signal?: AbortSignal) => Promise<readonly WebSearchResult[]>;
export class WebSearchTool {
  constructor(private readonly adapter: WebSearchAdapter) {}
  async search(query: string, signal?: AbortSignal): Promise<readonly WebSearchResult[]> {
    if (!query.trim()) throw new TypeError("search query is required");
    return this.adapter(query, signal);
  }
}
