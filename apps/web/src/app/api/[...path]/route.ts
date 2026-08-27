type ApiRouteContext = {
  params: Promise<{ path: string[] }>;
};

const DEFAULT_API_INTERNAL_URL = "http://127.0.0.1:8000";
const BODYLESS_METHODS = new Set(["GET", "HEAD"]);

function apiInternalUrl(): URL {
  const configured = process.env.API_INTERNAL_URL?.trim() || DEFAULT_API_INTERNAL_URL;
  const url = new URL(configured);
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new Error("API_INTERNAL_URL must use http or https");
  }
  return url;
}

async function proxy(request: Request, context: ApiRouteContext): Promise<Response> {
  const { path } = await context.params;
  const upstreamUrl = apiInternalUrl();
  upstreamUrl.pathname = `/api/${path.map(encodeURIComponent).join("/")}`;
  upstreamUrl.search = new URL(request.url).search;

  const headers = new Headers(request.headers);
  headers.delete("host");

  const init: RequestInit & { duplex?: "half" } = {
    method: request.method,
    headers,
    redirect: "manual",
  };
  if (!BODYLESS_METHODS.has(request.method)) {
    init.body = request.body;
    init.duplex = "half";
  }

  const upstreamResponse = await fetch(new Request(upstreamUrl, init));
  return new Response(upstreamResponse.body, {
    status: upstreamResponse.status,
    statusText: upstreamResponse.statusText,
    headers: upstreamResponse.headers,
  });
}

export const dynamic = "force-dynamic";

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
export const OPTIONS = proxy;
