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
