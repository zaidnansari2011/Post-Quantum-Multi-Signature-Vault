// The app's config is app.json. This file adds the one value that cannot be committed.
//
// android.googleServicesFile: Firebase's google-services.json for project qvault-90763, which push
// needs on Android (FCM, plan R8). It is kept out of git. An EAS build reads it from the file
// environment variable GOOGLE_SERVICES_JSON (OWNER-ACTIONS §2.12); a local build reads
// ./google-services.json when it is there (gitignored). With neither, the build has no FCM: it
// starts and works, and the server's pushes simply never reach it.
const fs = require('fs');
const path = require('path');

module.exports = ({ config }) => {
  const local = path.join(__dirname, 'google-services.json');
  const file = process.env.GOOGLE_SERVICES_JSON || (fs.existsSync(local) ? './google-services.json' : undefined);
  return {
    ...config,
    android: { ...config.android, ...(file ? { googleServicesFile: file } : {}) },
  };
};
