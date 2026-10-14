/*
 * SmartFactory AI – runtime configuration (edit after build, no rebuild needed).
 *
 * apiBaseUrl: where the Python backend lives.
 *   ''  (empty)  → same address as this website (Cloud Run one-container deploy, local dev proxy,
 *                  Cloudflare Pages proxy function). This is the default.
 *   'https://smartfactory-api-xxxxx-uc.a.run.app'  → frontend hosted elsewhere (Firebase Hosting,
 *                  Netlify, S3…). The backend must then allow this site in CORS_ORIGINS.
 */
window.SF_CONFIG = {
  apiBaseUrl: ''
};
