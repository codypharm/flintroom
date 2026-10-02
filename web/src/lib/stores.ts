/**
 * Where the app is downloaded, in one place.
 *
 * Every download button on the site reads from here, so the App Store link is
 * added once when Apple approves the iPhone build rather than hunted for across
 * the landing page, the tool layout and the comparison pages.
 *
 * `referrer` is Google Play's install referrer. Play Console's acquisition
 * report credits installs carrying it to the website, which answers "does the
 * site send anyone" without a script on the page.
 */

export const PLAY_URL =
  'https://play.google.com/store/apps/details?id=com.flintroom.app' +
  '&referrer=utm_source%3Dflintroom.app%26utm_medium%3Dwebsite';
