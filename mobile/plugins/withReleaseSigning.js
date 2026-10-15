// Give the release build a real signing identity, and keep it across `expo prebuild --clean`.
//
// Expo's template signs the RELEASE build type with `signingConfigs.debug`, whose keystore
// (android/app/debug.keystore) ships inside the template and is therefore identical in every Expo
// project on earth. That is fine for `expo run:android`, and wrong for an artefact whose whole
// subject is signing: anyone could produce an APK that installs over it as an upgrade.
//
// android/ is generated and wiped by prebuild, so hand-editing build.gradle does not survive. This
// plugin re-applies the change every time prebuild runs.
//
// IT NO-OPS WHEN THE KEYSTORE IS ABSENT, and that is deliberate. EAS Build supplies its own
// credentials and has no credentials/ directory; a plugin that unconditionally pointed the release
// config at a local file would break every cloud build with a missing-file error at the very end
// of a long queue.

const { withAppBuildGradle, withGradleProperties } = require('@expo/config-plugins');
const fs = require('fs');
const path = require('path');

const KEYSTORE = 'credentials/release.jks';
const PASSWORD_FILE = 'credentials/keystore.password';
const KEY_ALIAS = 'qvault';

function readCredentials(projectRoot) {
  const keystore = path.join(projectRoot, KEYSTORE);
  const passwordFile = path.join(projectRoot, PASSWORD_FILE);
  if (!fs.existsSync(keystore) || !fs.existsSync(passwordFile)) return null;
  return {
    // Gradle is happier with forward slashes on Windows, and this string lands in a .properties
    // file where a backslash is an escape character.
    storeFile: keystore.replace(/\\/g, '/'),
    password: fs.readFileSync(passwordFile, 'utf8').trim(),
  };
}

const PROPERTIES = {
  storeFile: 'QVAULT_RELEASE_STORE_FILE',
  storePassword: 'QVAULT_RELEASE_STORE_PASSWORD',
  keyAlias: 'QVAULT_RELEASE_KEY_ALIAS',
  keyPassword: 'QVAULT_RELEASE_KEY_PASSWORD',
};

const withSigningProperties = (config) =>
  withGradleProperties(config, (cfg) => {
    const creds = readCredentials(cfg.modRequest.projectRoot);
    if (!creds) return cfg;

    const values = {
      [PROPERTIES.storeFile]: creds.storeFile,
      [PROPERTIES.storePassword]: creds.password,
      [PROPERTIES.keyAlias]: KEY_ALIAS,
      [PROPERTIES.keyPassword]: creds.password,
    };
    // Replace rather than append, so repeated prebuilds do not accumulate duplicates.
    cfg.modResults = cfg.modResults.filter(
      (item) => !(item.type === 'property' && item.key in values),
    );
    for (const [key, value] of Object.entries(values)) {
      cfg.modResults.push({ type: 'property', key, value });
    }
    return cfg;
  });

const withSigningConfig = (config) =>
  withAppBuildGradle(config, (cfg) => {
    if (!readCredentials(cfg.modRequest.projectRoot)) return cfg;
    if (cfg.modResults.language !== 'groovy') {
      throw new Error('withReleaseSigning expects a Groovy build.gradle');
    }

    let contents = cfg.modResults.contents;

    // 1. Declare the release signingConfig next to the template's debug one. Anchored on the
    //    closing brace of `debug { ... }` inside signingConfigs, which is stable across SDKs.
    if (!contents.includes('QVAULT_RELEASE_STORE_FILE')) {
      const anchor = `            keyPassword 'android'\n        }`;
      if (!contents.includes(anchor)) {
        throw new Error('withReleaseSigning: could not find the debug signingConfig anchor');
      }
      contents = contents.replace(
        anchor,
        `${anchor}
        release {
            // Injected by plugins/withReleaseSigning.js from credentials/ (gitignored).
            if (project.hasProperty('QVAULT_RELEASE_STORE_FILE')) {
                storeFile file(QVAULT_RELEASE_STORE_FILE)
                storePassword QVAULT_RELEASE_STORE_PASSWORD
                keyAlias QVAULT_RELEASE_KEY_ALIAS
                keyPassword QVAULT_RELEASE_KEY_PASSWORD
            }
        }`,
      );
    }

    // 2. Point the release build type at it. The template hardcodes signingConfigs.debug here,
    //    with that exact comment above it; matching the comment too avoids touching the debug
    //    build type, which legitimately uses the debug config.
    const releaseSigning = `            // Caution! In production, you need to generate your own keystore file.
            // see https://reactnative.dev/docs/signed-apk-android.
            signingConfig signingConfigs.debug`;
    if (contents.includes(releaseSigning)) {
      contents = contents.replace(
        releaseSigning,
        `            signingConfig project.hasProperty('QVAULT_RELEASE_STORE_FILE') ? signingConfigs.release : signingConfigs.debug`,
      );
    } else if (!contents.includes('signingConfigs.release')) {
      throw new Error('withReleaseSigning: release buildType signingConfig anchor not found');
    }

    cfg.modResults.contents = contents;
    return cfg;
  });

module.exports = (config) => withSigningConfig(withSigningProperties(config));
