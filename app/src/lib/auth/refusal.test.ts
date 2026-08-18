import { SignedOut } from './session';
import { refusalFor } from './refusal';

/**
 * What somebody is told when signing in does not work.
 *
 * One string for every failure was the state before this: "That did not go
 * through. Try again in a moment." It named nothing, offered no recovery, and
 * promised a resolution nothing could know — a server returning 500 for an hour
 * is not a moment, and an aeroplane with no signal will never become one.
 */

it('names the connection when the server was never reached', () => {
  // React Native rejects `fetch` with a TypeError when the request never
  // leaves the device. It is the one cause this code genuinely knows, and the
  // only one where the recovery is the user's to perform.
  const said = refusalFor(new TypeError('Network request failed'));

  expect(said).toMatch(/connection/i);
});

it('does not blame the connection for a server that answered', () => {
  const said = refusalFor(new Error('POST /v1/auth/sessions failed with 503'));

  expect(said).not.toMatch(/connection/i);
});

it('says a refused account is the account, not the network', () => {
  // A 401 from our own server means the provider's token was not accepted.
  // Telling somebody to check their signal would send them to fix a thing that
  // is not broken.
  const said = refusalFor(new SignedOut('refused by /v1/auth/sessions'));

  expect(said).toMatch(/account/i);
  expect(said).not.toMatch(/connection/i);
});

it('never promises a time it cannot know', () => {
  for (const error of [
    new TypeError('Network request failed'),
    new SignedOut('refused'),
    new Error('POST /v1/auth/sessions failed with 500'),
    new Error('Google returned no token.'),
  ]) {
    expect(refusalFor(error)).not.toMatch(/in a (moment|second|few)/i);
  }
});

it('always offers something to do next', () => {
  for (const error of [
    new TypeError('Network request failed'),
    new SignedOut('refused'),
    new Error('anything at all'),
  ]) {
    expect(refusalFor(error)).toMatch(/try|check/i);
  }
});

it('leaks no internal detail into what is shown', () => {
  // The message carries a path and a status code. Those belong in a log line,
  // not on a screen a stranger is looking at — CLAUDE.md keeps `context` off
  // the client for exactly this reason.
  const said = refusalFor(new Error('POST /v1/auth/sessions failed with 503'));

  expect(said).not.toMatch(/503|\/v1\/|POST/);
});

it('tells somebody how to fix stale Play services, which they alone can', () => {
  // `google.ts` calls `hasPlayServices()` precisely so this surfaces as a
  // typed failure rather than dying inside the sheet — and then the copy sent
  // it to the same dead end as everything else. It is the one failure here
  // whose recovery is entirely the user's, so it is the one worth naming.
  const stale = Object.assign(new Error('Play services not available'), {
    code: 'PLAY_SERVICES_NOT_AVAILABLE',
  });

  expect(refusalFor(stale)).toMatch(/Play/);
  expect(refusalFor(stale)).toMatch(/update/i);
});

it('does not mistake an unrelated code for a Play services problem', () => {
  const other = Object.assign(new Error('nope'), { code: 'DEVELOPER_ERROR' });

  expect(refusalFor(other)).not.toMatch(/Play/);
});
