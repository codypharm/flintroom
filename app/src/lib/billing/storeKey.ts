/**
 * Which RevenueCat key this build opens the till with, or none.
 *
 * RevenueCat issues one public SDK key per store app: `goog_` for Play,
 * `appl_` for the App Store. Until 2026-10-01 the buy screen read the Android
 * key on every platform, so an iOS build would have configured the SDK with
 * Google's key and failed at the moment of paying.
 *
 * **The keys arrive as arguments, never read here.** Expo inlines an
 * `EXPO_PUBLIC_` variable only where the code spells it out as
 * `process.env.EXPO_PUBLIC_…`; a lookup by computed name is left as a runtime
 * read of an object that is empty in a release build. So the caller names
 * both, and this only chooses.
 *
 * `undefined` means `unconfiguredStore()`: a platform with no key of its own
 * sells nothing rather than borrowing another platform's.
 */
export function storeKeyFor(
  os: string,
  keys: { android?: string; ios?: string },
): string | undefined {
  const key = os === 'ios' ? keys.ios : os === 'android' ? keys.android : undefined;
  return key || undefined;
}
