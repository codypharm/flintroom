/**
 * A refusal the server explained, kept whole.
 *
 * Every endpoint here answers a business refusal the same way — a `code`, a
 * `message`, a status — because the recoveries differ and only the code can
 * tell them apart. Throwing that away is how a screen ends up saying "something
 * went wrong" about a problem the server had already diagnosed.
 *
 * **It lived in `debriefApi` until the sessions client needed it too.** That is
 * not a refactor for tidiness: `sessionsApi.start` was raising a bare `Error`
 * with a status code in it, so a device reported "the room would not open,
 * nothing was charged" when the server had said `no_minutes_remaining` and "You
 * are out of interrogation minutes". The type existed; the caller that needed
 * it most could not see it.
 */
export class Refused extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly status: number
  ) {
    super(message);
    this.name = 'Refused';
  }
}

/** The refusal a response explains, or null when it explains nothing. */
export async function refusalIn(response: Response): Promise<Refused | null> {
  try {
    const body = (await response.json()) as {
      error?: { code?: string; message?: string };
    };
    const error = body.error;

    // Both halves or neither. A code with no sentence leaves the screen with
    // nothing to say if it does not recognise the code, and a sentence with no
    // code cannot be told apart from any other failure.
    return error?.code && error?.message
      ? new Refused(error.code, error.message, response.status)
      : null;
  } catch {
    // A gateway, a proxy, an HTML error page. Nothing to carry.
    return null;
  }
}
