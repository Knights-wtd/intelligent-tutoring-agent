const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";

/** Build-time backend API origin (empty means the browser's current origin). */
export const apiBaseUrl = API_BASE_URL;

/** Prefix a backend API path with the build-time API origin (empty for same-origin). */
export function apiUrl(path: string): string {
  return `${API_BASE_URL}${path}`;
}
