import { Refused } from '../api/refused';

/**
 * Why a room would not open, and whether buying time would help.
 *
 * **These sentences lived inside `interrogation.tsx`.** Routes carry no tests by
 * convention (`CLAUDE.md` → Frontend), so the words somebody reads at the worst
 * moment of using this product had nothing holding them. They moved when the
 * refusal had to grow a *decision* rather than only a sentence: with a buy
 * screen behind it (#90), each refusal now says whether money is the answer —
 * and getting that wrong takes payment for a room that will still not open.
 *
 * Copy lives here rather than on the server for the reason `Product.md` §9
 * gives — the API states the fact, the client writes the sentence — and because
 * these carry this product's register. The server's own message stays the
 * fallback for a code this build predates, so a refusal added later says
 * something true rather than a catch-all.
 */

export interface Refusal {
  /** What to put on the screen. */
  said: string;

  /**
   * Whether more minutes would actually fix this.
   *
   * **False by default and true in exactly one case**, because the expensive
   * mistake is the generous one. `daily_ceiling_reached` is the trap: it looks
   * like running out and is not. It is the runaway-cost circuit breaker (#73)
   * bounding what three providers can charge *us* in twenty-four hours, it
   * lifts on its own, and no purchase raises it by a cent — so an offer there
   * takes money for a room that will refuse again immediately.
   */
  buying: boolean;
}

export function refusalFor(thrown: unknown): Refusal {
  // The server's own diagnosis first, because it is the only thing that knows
  // WHY. A device reported "the room would not open, nothing was charged" while
  // the API was saying `no_minutes_remaining` — the catch-all below standing in
  // for an answer somebody could have acted on.
  if (thrown instanceof Refused) {
    return (
      REFUSED[thrown.code] ?? {
        said: thrown.message,
        // Never sell against a cause this build does not understand.
        buying: false,
      }
    );
  }

  const why = thrown instanceof Error ? thrown.message : '';

  if (why === 'denied') {
    return {
      said: 'Flintroom needs the microphone to hold a room. Turn it on in Settings, then try again.',
      buying: false,
    };
  }

  if (why === 'unavailable') {
    return {
      said: 'We could not reach the microphone. Try again in a moment.',
      buying: false,
    };
  }

  // Says nothing was charged, and that is the one thing worth saying to
  // somebody who just tried to spend minutes and assumes otherwise.
  return { said: 'The room would not open. Nothing was charged.', buying: false };
}

const REFUSED: Record<string, Refusal> = {
  // **§4.6 governs this sentence.** Never a depleting counter, and framed
  // generously — it says what is true (the minutes are spent) and what is still
  // theirs (everything already recorded), and it does not scold. The room costs
  // money to hold; running out is the product working, not a failure.
  //
  // **The only refusal that may offer to sell.** It used to say it could not,
  // because RevenueCat was unwired — that comment was true when written and is
  // not any more.
  no_minutes_remaining: {
    said: 'You have used your interrogation minutes. Your rooms and debriefs are all still here.',
    buying: true,
  },
  // One live room at a time, which is a real constraint rather than a fault —
  // and the recovery is to finish or leave the other one. Minutes are not the
  // constraint, so money changes nothing.
  active_session_exists: {
    said: 'A room is already open on this account. Finish that one, then start another.',
    buying: false,
  },
  // The runaway-cost circuit breaker (#73), and the only refusal here that is
  // about *us* rather than about them. It fires on abuse and will occasionally
  // fire on somebody who rehearsed all day — so it says nothing about spend,
  // does not scold, and leads with what is untouched. A user who reads this as
  // "I have done something wrong" has been told the wrong thing, and one who is
  // offered a purchase here has been charged for nothing.
  daily_ceiling_reached: {
    said: 'That is a lot of rooms in one day. This lifts within a day — your minutes and everything you have recorded are untouched.',
    buying: false,
  },
};
