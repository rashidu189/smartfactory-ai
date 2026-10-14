/**
 * Cloudflare Pages Function: forwards every /api/* request to the Python backend (e.g. on Render).
 *
 * Why a proxy instead of calling the backend directly from the browser:
 *  - same origin for the browser → no CORS setup, and links like /api/datasets/…/report.csv and
 *    /api/inspections/…/image keep working unchanged;
 *  - the backend URL lives in one place (Pages environment variable BACKEND_URL).
 *
 * Configure in Cloudflare: Pages project → Settings → Environment variables →
 *   BACKEND_URL = https://smartfactory-api.onrender.com   (no trailing slash)
 */
export async function onRequest({ request, env }) {
  const backend = (env.BACKEND_URL || '').replace(/\/+$/, '');
  if (!backend) {
    return new Response(JSON.stringify({ error: 'BACKEND_URL is not set for this Cloudflare Pages project.' }),
      { status: 500, headers: { 'content-type': 'application/json' } });
  }
  const url = new URL(request.url);
  const target = backend + url.pathname + url.search;

  const headers = new Headers(request.headers);
  headers.delete('host');
  headers.set('x-forwarded-host', url.host);
  headers.set('x-forwarded-proto', url.protocol.replace(':', ''));

  const init = { method: request.method, headers, redirect: 'manual' };
  if (!['GET', 'HEAD'].includes(request.method)) init.body = request.body;

  try {
    const resp = await fetch(target, init);
    return new Response(resp.body, { status: resp.status, statusText: resp.statusText, headers: resp.headers });
  } catch (err) {
    return new Response(JSON.stringify({ error: 'The backend could not be reached. On Render free tier it may be waking up — try again in a minute.' }),
      { status: 502, headers: { 'content-type': 'application/json' } });
  }
}
