# Flintroom — client

Expo / React Native client. See the repository root `CLAUDE.md` for product
scope, the metering boundary, and the frontend standards this code follows.

## Running it

**Expo Go will not work.** It ships a fixed set of native modules and cannot
load `react-native-audio-api`, which the interrogation screen depends on. You
need a development build — your own binary, containing our native modules.

```bash
npm install
npx expo run:ios --device      # once, and after any native dependency change
npx expo run:android --device  # ditto, for Android
```

After that, the daily loop is:

```bash
npx expo start --dev-client
```

…then open **Flintroom** on the device. It connects to Metro over the LAN and
hot-reloads JavaScript. Rebuild only when native dependencies change — editing
TypeScript does not need one.

Because the phone is a different machine, the API base URL must be your
development machine's LAN address. `localhost` on the phone means the phone.

## Getting an Android phone attached

Wireless debugging over a shared Wi-Fi network works and is the usual route:
enable it in Developer options, `adb pair` once with the code the phone shows,
and afterwards adb finds the device over mDNS by itself.

**The phone's own hotspot is not a substitute.** Android binds wireless
debugging to the Wi-Fi connection, so a phone that drops Wi-Fi to *become* a
hotspot switches wireless debugging off with it — tried, and it stays off. The
phone still answers ping (it is the gateway) while nothing listens on the adb
port, which makes this look like a stale port rather than an unavailable
feature. It is not recoverable from the Mac side.

So away from a router, the options are a USB **data** cable — a charge-only
cable presents no device and gives no dialog, which is indistinguishable from a
broken setup — or the emulator, which cannot answer acoustic questions at all.

`npx expo run:android --device` cannot select a device whose adb serial
contains a space (mDNS appends ` (2)` when it sees a duplicate record). Build
and install directly instead, which also skips starting a second Metro:

```bash
android/gradlew -p android installDebug -PreactNativeArchitectures=arm64-v8a
```

## Android needs JDK 17, not the one Android Studio ships

Android Studio bundles its own JDK and points `JAVA_HOME` at it. On current
versions that is **JDK 25, which cannot build this project**:

```bash
export JAVA_HOME="/opt/homebrew/opt/openjdk@17"   # brew install openjdk@17
```

JDK 24 introduced JEP 472, restricting native access. That breaks Android
Gradle Plugin's *CMake configuration* step, so the build dies only on modules
with C++ — here `react-native-screens` and `react-native-worklets` — after
eleven minutes of successful Kotlin compilation, with the unhelpful message
`WARNING: A restricted method in java.lang.System has been called`. Nothing in
it names the JDK, and the modules it names are innocent.

The first build also needs `ANDROID_HOME` (`~/Library/Android/sdk`); Gradle
downloads the missing SDK platforms, build-tools and NDK itself.

To build only for the ABI a real phone uses, cutting the C++ compile roughly
fourfold:

```bash
./gradlew assembleDebug -PreactNativeArchitectures=arm64-v8a
```

## Tests

```bash
npm test
npx tsc --noEmit
```

One Jest runner for everything, `jest-expo/ios` preset — see the reasoning in
`jest.config.js`. Component tests and pure logic share it deliberately.

## API types

```bash
npm run generate:api
```

Regenerates `src/lib/api/schema.d.ts` from `contracts/openapi.yaml`. The
generated file is committed, so a fresh clone builds without running codegen.
The generator runs through a pinned `npx` rather than sitting in
`devDependencies`; the root `CLAUDE.md` explains why, and why not to "fix" it.

## Native directories

`ios/` and `android/` are generated and gitignored. They are produced from
`app.json` by prebuild, so configuration changes belong in `app.json` and its
config plugins — never in the generated projects, where they are silently lost
on the next prebuild.
