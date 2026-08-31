import { SignedOut } from '../auth/session';

/**
 * Asking to be forgotten, and the sentences that go with it.
 *
 * Apple has required in-app account deletion since 2022 for any app that
 * supports account creation, so this is a store blocker rather than a courtesy
 * — and `docs/privacy-policy.md` cannot be published while it claims a control
 * the app does not have.
 *
 * `docs/account-deletion.md` decided the shape: seven recoverable days, and
 * signing in during them calls the deletion off. Both halves put weight on
 * copy, which is why the copy lives here as data rather than inline in a
 * screen. The window is worth nothing to somebody who is not told when it
 * closes, and a cancellation nobody mentions is worse than no cancellation at
 * all — the user's data is still there and they never find out.
 *
 * Plain TypeScript rather than a component. The confirmation is a sequence —
 * ask, call, forget, tell — and its failure modes are orderings: deleting
 * before asking, or forgetting the credentials after a request that never
 * landed. A renderer proves neither.
 */

/** What the app says when a sign-in reverses a scheduled deletion. */
export const CANCELLED_ON_SIGN_IN =
  'Your account was scheduled for deletion. Signing in has cancelled that.';

export const CONFIRM_TITLE = 'Delete your account?';

/**
 * Named in full, because a person deciding this should not have to remember
 * what the settings screen listed above the button. The order is what goes
 * first from their point of view, not the order the purge runs in.
 */
export const CONFIRM_BODY =
  'Your rooms, what was said in them, and any material you attached will be ' +
  'deleted. You have seven days to change your mind. Signing in during that ' +
  'time cancels it.';

/**
 * What the app says when the credential turned out to be dead.
 *
 * Separated from the failure below because the two need different actions from
 * the person. "Try again" is wrong here — trying again will fail identically
 * until they sign in — and it would leave them tapping a button that cannot
 * work.
 */
export const NOT_SIGNED_IN =
  'Your account was not deleted. You are signed out. Sign in and try again.';

/** What the app says when the request could not be made. */
export const COULD_NOT_SCHEDULE =
  'Your account was not deleted. We could not reach the server, and nothing ' +
  'has changed. Try again in a moment.';

/**
 * "25 August", not "in seven days" and not an ISO string.
 *
 * The same rule `SettingsScreen` already follows for retention: a date is a
 * fact, and a countdown is a clock running down on something the person chose.
 * The window exists to be used, so the sentence says how.
 */
export function scheduledMessage(purgeAt: Date): string {
  const on = purgeAt.toLocaleDateString('en-GB', { day: 'numeric', month: 'long' });

  return `Your account will be deleted on ${on}. Until then, signing in cancels it.`;
}

export interface ConfirmDeletionOptions {
  /** The second yes. Resolves true only if the person confirmed. */
  ask(title: string, body: string): Promise<boolean>;
  /** `DELETE /v1/me`, resolving to when the purge happens. */
  deleteAccount(): Promise<Date>;
  /**
   * Clear the tokens held on this device.
   *
   * Not the sign-out endpoint: the request already revoked every refresh token
   * server-side, so calling it would present a credential that is dead by
   * design and take a 401 for it.
   */
  forgetCredentials(): Promise<void>;
  /**
   * Tell the gate its answer has changed, so the app leaves the signed-in
   * screens.
   *
   * Part of this flow rather than the caller's afterthought, because it was the
   * caller's afterthought and got dropped: the settings route wired every other
   * step and not this one, and the flow ended with a signed-out person still
   * sitting in Settings (2026-08-31, on a real device).
   *
   * Synchronous on purpose. `Gateway.recheck` sets state and returns; awaiting
   * it would imply a completion this has no way to observe.
   */
  signedOut(): void;
  tell(message: string): Promise<void>;
}

/**
 * The whole flow, in the order the failures matter.
 *
 * **Ask first.** The button is one yes and this is the second. A single tap on
 * a destructive control at the bottom of a scrolling screen is not consent for
 * something that cannot be undone after a week.
 *
 * **Forget only after the server agreed.** Clearing the credentials on a
 * failed request strands somebody: the account is alive, they can no longer
 * reach it, and nothing on screen distinguishes that from the deletion they
 * asked for.
 *
 * Never rejects. Every outcome is a sentence, because the caller is a button
 * handler and an unhandled rejection there is a screen that does nothing.
 */
export async function confirmDeletion({
  ask,
  deleteAccount,
  forgetCredentials,
  signedOut,
  tell,
}: ConfirmDeletionOptions): Promise<void> {
  if (!(await ask(CONFIRM_TITLE, CONFIRM_BODY))) {
    return;
  }

  let purgeAt: Date;
  try {
    purgeAt = await deleteAccount();
  } catch (error) {
    // The one distinction worth making, and the same one `authApi` draws: a
    // 401 means the session is over, and "try again in a moment" would send
    // somebody back to a button that cannot work until they sign in. Every
    // other failure is a server we could not reach, and the person needs to
    // know their account is untouched — which status came back is a fact about
    // us rather than about them.
    await tell(error instanceof SignedOut ? NOT_SIGNED_IN : COULD_NOT_SCHEDULE);
    return;
  }

  await forgetCredentials();
  // **Before the message, not after.** `tell` waits on a dismissal, so gating
  // afterwards leaves the device holding dead credentials on a screen that can
  // still act on them — for as long as the alert sits there. That window is
  // where the reported bug lived: a second tap on Delete refused with
  // `SignedOut` and told somebody to sign in, from the settings screen, having
  // already done what was asked.
  signedOut();
  await tell(scheduledMessage(purgeAt));
}
