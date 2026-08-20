// Keep the native build inside this machine's memory budget, durably.
//
// The first local release build died with a JVM "Native memory allocation (mmap) failed" crash on a
// 16 GB machine. Cause was not the JS side at all: Gradle was compiling React Native's C++ for FOUR
// ABIs concurrently -- armeabi-v7a, arm64-v8a, x86, x86_64 -- across six JVMs.
//
// Three of those four are dead weight here. x86 and x86_64 exist for emulators; armeabi-v7a is
// 32-bit ARM, effectively gone from phones since ~2017. Every device in this project's demo is
// arm64-v8a, so building one architecture cuts the native work roughly fourfold and takes the peak
// memory with it.
//
// This lives in a config plugin because `expo prebuild --clean` regenerates android/gradle.properties
// and would silently drop the settings -- reintroducing a crash that looks like a hardware problem.

const { withGradleProperties } = require('@expo/config-plugins');

// Widen this (e.g. 'arm64-v8a,armeabi-v7a') only if a target device is genuinely 32-bit; the APK
// simply will not install on an architecture it was not built for.
const ARCHITECTURES = 'arm64-v8a';

const SETTINGS = {
  reactNativeArchitectures: ARCHITECTURES,
  // Explicit rather than inherited: the default grows until the OS refuses, which is exactly the
  // failure seen. Metaspace is separate from the heap and the Kotlin compiler is hungry for it.
  // Modest on purpose. The crash was a NATIVE allocation failure (clang/ninja), not a Java heap
  // exhaustion -- so a smaller JVM reservation leaves MORE room for the C++ compile, not less.
  'org.gradle.jvmargs': '-Xmx2048m -XX:MaxMetaspaceSize=512m -Dfile.encoding=UTF-8',
  // Parallelism multiplies peak memory by the worker count, which is the thing under pressure.
  'org.gradle.workers.max': '2',
};

module.exports = (config) =>
  withGradleProperties(config, (cfg) => {
    cfg.modResults = cfg.modResults.filter(
      (item) => !(item.type === 'property' && item.key in SETTINGS),
    );
    for (const [key, value] of Object.entries(SETTINGS)) {
      cfg.modResults.push({ type: 'property', key, value });
    }
    return cfg;
  });
