// The app's config is app.json. This file adds the values that differ between builds or cannot be
// committed.
//
// extra.apiBaseUrl: the Q-Vault server the app talks to. app.json's value (the live domain) unless
// QVAULT_API_BASE_URL is set when the config is read. The `rework` build profile in eas.json sets it
// to the staging server. `extra` also travels inside every over-the-air update's manifest (the app
// reads it through Constants.expoConfig, which an update replaces), so an `eas update` published
// with a different QVAULT_API_BASE_URL, or without it, repoints installed apps with no new build.
// Every `eas update` must therefore be run with the value the target phones should use
// (OWNER-ACTIONS §2.3). A value that is not a bare https origin stops the build or update here,
// rather than shipping an app that can reach nothing.
//
// android.googleServicesFile: Firebase's google-services.json for project qvault-90763, which push
// needs on Android (FCM, plan R8). It is kept out of git. An EAS build reads it from the file
// environment variable GOOGLE_SERVICES_JSON (OWNER-ACTIONS §2.12); a local build reads
// ./google-services.json when it is there (gitignored). With neither, the build has no FCM: it
// starts and works, and the server's pushes simply never reach it.
const fs = require('fs');
const path = require('path');

function apiBaseUrl(fallback) {
  const raw = process.env.QVAULT_API_BASE_URL;
  if (raw === undefined || raw.trim() === '') return fallback;
  const value = raw.trim().replace(/\/+$/, '');
  if (!/^https:\/\/[a-z0-9.-]+(:[0-9]+)?$/i.test(value)) {
    throw new Error(`QVAULT_API_BASE_URL must be an https origin with no path, got "${raw}"`);
  }
  return value;
}

module.exports = ({ config }) => {
  const local = path.join(__dirname, 'google-services.json');
  const file = process.env.GOOGLE_SERVICES_JSON || (fs.existsSync(local) ? './google-services.json' : undefined);
  return {
    ...config,
    extra: { ...config.extra, apiBaseUrl: apiBaseUrl(config.extra.apiBaseUrl) },
    android: { ...config.android, ...(file ? { googleServicesFile: file } : {}) },
  };
};
