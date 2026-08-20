/**
 * The order a room is closed in, which decides how it is recorded.
 *
 * **#82: every room in the dev database had ended as `client_disconnect` —
 * five of five, not "usually".** The old code read:
 *
 * ```ts
 * void sessions.end(settled).catch(() => undefined);
 * room.current?.leave();
 * ```
 *
 * with a comment above it saying *"the intent first, then the socket"*. That is
 * what it meant and not what it did: `void` does not wait, so a local socket
 * close raced a network round trip and won every time. The server saw the
 * disconnect first and settled the room as a dropped line, which its own
 * `EndReason` enum says is a different event to the business than somebody
 * deciding they are done.
 *
 * A function rather than four lines inside a component, because the ORDER is
 * the decision and an order that only exists inside a `useCallback` cannot be
 * tested — which is exactly how a comment came to describe behaviour the code
 * did not have.
 */

export interface Closing {
  /** Tell the server the presenter is finished. */
  tell(): Promise<void>;
  /** Drop the socket. Called exactly once, whatever `tell` does. */
  hangUp(): void;
  /**
   * How long to wait for the server before dropping the line anyway.
   *
   * The room is over either way. A presenter who has finished must never be
   * held on a screen by a hanging request — and the worst case of giving up is
   * the behaviour this fix replaces, with the reaper settling an abandoned room
   * and refunding it.
   */
  patience?: number;
}

const PATIENCE_MS = 2000;

export async function closeRoom({
  tell,
  hangUp,
  patience = PATIENCE_MS,
}: Closing): Promise<void> {
  let timer: ReturnType<typeof setTimeout> | undefined;

  try {
    await Promise.race([
      // Swallowed rather than propagated: a refusal is not a reason to keep a
      // dead socket open, and the caller has nothing useful to do with it.
      tell().catch(() => undefined),
      new Promise<void>((resolve) => {
        timer = setTimeout(resolve, patience);
      }),
    ]);
  } finally {
    // Cleared whichever way the race went, so a resolved request does not leave
    // a timer running against a screen that has already left.
    if (timer !== undefined) {
      clearTimeout(timer);
    }
    hangUp();
  }
}
