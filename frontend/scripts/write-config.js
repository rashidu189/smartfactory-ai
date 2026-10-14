/**
 * Writes dist/smartfactory-ui/config.js from the API_BASE_URL environment variable.
 * Used on hosts that build the frontend themselves (e.g. Render Static Site):
 *   Build command:  npm ci && npx ng build && node scripts/write-config.js
 *   Env var:        API_BASE_URL=https://smartfactory-api.onrender.com
 * Without API_BASE_URL the file keeps apiBaseUrl '' (same address as the website).
 */
const fs = require('fs');
const path = require('path');

const raw = (process.env.API_BASE_URL || '').trim();
const url = raw.replace(/\/+$/, '').replace(/\/api$/, '');
if (url && !/^https?:\/\//.test(url)) {
  console.error(`API_BASE_URL must start with https:// (got "${raw}")`);
  process.exit(1);
}
const out = path.join(__dirname, '..', 'dist', 'smartfactory-ui', 'config.js');
fs.writeFileSync(out, `// Generated at build time by scripts/write-config.js\nwindow.SF_CONFIG = { apiBaseUrl: ${JSON.stringify(url)} };\n`);
console.log(`config.js written: apiBaseUrl = ${url || "'' (same origin)"}`);
