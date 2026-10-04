// Web screenshot harness ONLY. Never loaded by a normal `expo start` / EAS build: it takes effect
// solely when EXPO_OVERRIDE_METRO_CONFIG points at this file (see shoot.sh).
//
// It is the stock Expo config plus three web-only redirects, so the real screens render in a
// browser for design review:
//   expo-secure-store          -> shims/secure-store.ts   (localStorage; the web build has none)
//   expo-local-authentication  -> shims/local-authentication.ts (reports a strong biometric, auto-passes)
//   ./App (from index.ts only) -> HarnessApp.tsx (points the API at the page's own origin)
const path = require('path');
const { getDefaultConfig } = require('expo/metro-config');

const projectRoot = path.resolve(__dirname, '..', '..');
const config = getDefaultConfig(projectRoot);

const norm = (p) => path.resolve(p).toLowerCase();
const entry = norm(path.join(projectRoot, 'index.ts'));
const redirects = {
  'expo-secure-store': path.join(__dirname, 'shims', 'secure-store.ts'),
  'expo-local-authentication': path.join(__dirname, 'shims', 'local-authentication.ts'),
};

const upstream = config.resolver.resolveRequest;
config.resolver.resolveRequest = (context, moduleName, platform) => {
  if (platform === 'web') {
    if (redirects[moduleName]) return { type: 'sourceFile', filePath: redirects[moduleName] };
    if (moduleName === './App' && norm(context.originModulePath) === entry) {
      return { type: 'sourceFile', filePath: path.join(__dirname, 'HarnessApp.tsx') };
    }
  }
  return (upstream ?? context.resolveRequest)(context, moduleName, platform);
};

module.exports = config;
