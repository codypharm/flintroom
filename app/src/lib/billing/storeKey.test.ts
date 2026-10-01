import { storeKeyFor } from './storeKey';

/**
 * Found 2026-10-01, the day Apple enrollment cleared: the buy screen read
 * `EXPO_PUBLIC_REVENUECAT_ANDROID_KEY` on every platform. RevenueCat issues one
 * public SDK key per store app, `goog_` for Play and `appl_` for the App Store,
 * so an iOS build would have opened the till with Google's key and been sold
 * nothing. The key is chosen per platform, and a platform with no key gets the
 * shut shop rather than the other platform's.
 */

const keys = { android: 'goog_android', ios: 'appl_ios' };

it('gives an iPhone the App Store key', () => {
  expect(storeKeyFor('ios', keys)).toBe('appl_ios');
});

it('gives Android the Play key', () => {
  expect(storeKeyFor('android', keys)).toBe('goog_android');
});

it('never hands one platform the other platform’s key', () => {
  // The bug itself: an iOS build with only the Android key set must not
  // configure RevenueCat with it. No key means `unconfiguredStore`, which is
  // honest; the wrong key is a till that fails at the moment of paying.
  expect(storeKeyFor('ios', { android: 'goog_android' })).toBeUndefined();
  expect(storeKeyFor('android', { ios: 'appl_ios' })).toBeUndefined();
});

it('treats an empty key as no key', () => {
  // EAS writes an unset variable as an empty string in some setups, and an
  // empty string handed to the SDK is a configured store with nothing behind it.
  expect(storeKeyFor('ios', { ios: '' })).toBeUndefined();
});

it('sells nothing on a platform with no store', () => {
  expect(storeKeyFor('web', keys)).toBeUndefined();
});
