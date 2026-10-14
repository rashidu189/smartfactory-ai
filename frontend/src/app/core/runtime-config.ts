/** Backend location from config.js (window.SF_CONFIG). Empty = same origin as the website. */
const cfg = (window as unknown as { SF_CONFIG?: { apiBaseUrl?: string } }).SF_CONFIG || {};

export const API_ORIGIN: string = (cfg.apiBaseUrl || '').trim().replace(/\/+$/, '');

/** Make a backend-relative URL (e.g. "/api/inspections/1/image") absolute when the API is on another origin. */
export function apiUrl(path: string): string {
  return path && path.startsWith('/api/') ? API_ORIGIN + path : path;
}
