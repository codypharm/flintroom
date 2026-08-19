import { SignedOut } from '../auth/session';
import { Refused } from './refused';

/**
 * The unmetered half of the product, over HTTP.
 *
 * Four endpoints, built and tested in #57–#60 and reachable from nothing until
 * now. Written by hand for the reason `authApi` and `panelsApi` give: the
 * substance of this client is the refusal mapping, and `openapi-fetch` never
 * throws.
 *
 * **Nothing here touches a balance, and that is structural.** `Product.md` §4.1
 * meters live interrogation and nothing after it, so there is no ticket, no
 * meter and no path from any call in this file to the ledger. A future reader
 * looking for where the debrief bills will not find it, because it does not
 * exist.
 *
 * The five typed refusals are the reason this is not three lines of `fetch`.
 * Two of them share a status and have nothing in common as recoveries: a room
 * the provider broke has already returned its minutes and wants a fresh start;
 * a room that asked no questions is simply over.
 */

/** The six readings the debrief can return. `Weakness` in `agents/weakness.py`. */
export type WeaknessKind =
  | 'unanswered'
  | 'dismissed'
  | 'not_reached'
  | 'contradicted'
  | 'unsupported'
  | 'evasive';

export interface WeakAnswer {
  /** Where the question sits in the transcript. What sparring re-asks. */
  ordinal: number;
  question: string;
  /** An archetype key — `cfo`, `technical_skeptic`, `champion`. */
  askedBy: string;
  /** What they said, or null when they said nothing — itself a finding. */
  answer: string | null;
  weakness: WeaknessKind;
  /** The coach's sentence about what was missing. */
  why: string;
}

/**
 * How this room compared with the last, or nothing at all.
 *
 * `docs/difficulty-calibration.md` decision 5. Never a level and never a
 * number: a rung rendered on a debrief turns the screen into a score, which is
 * the delivery-metrics product §1 exists to refuse. Null when the rung did not
 * move, and null says nothing rather than saying "the same".
 */
export type Pressed = 'harder' | 'easier' | null;

export interface Debrief {
  /** Worst first, as the model ranked them with the whole room in view. */
  weakAnswers: WeakAnswer[];
  pressed: Pressed;
}

export interface CoachTurn {
  /** The caption. A v1 accessibility requirement, not a convenience. */
  text: string;
  /** The same words as audio, base64 — this is a JSON response. */
  speech: string;
  /**
   * What the transcriber made of the clip.
   *
   * Shown, not swallowed. A mishearing produces a reply that reads as the coach
   * having stopped listening, and this is the only way somebody can tell that
   * from a disagreement worth having. It is also the middle of the sparring
   * record — the answer the room got, this one, and what changed.
   */
  heard: string;
}

export interface Playback {
  url: string;
  expiresInSeconds: number;
}

/**
 * A refusal the server named, carried whole.
 *
 * Both fields matter. `code` is what a screen switches on to choose its own
 * sentence and its own next action; `message` is what it falls back to for a
 * code this app has never heard of, so a server that grows a new refusal says
 * something true here instead of nothing.
 */
// Re-exported rather than redefined. It moved to `refused.ts` when the sessions
// client needed it as well, and two classes named `Refused` would be two things
// `instanceof` disagrees about.
export { Refused } from './refused';

export interface DebriefApi {
  read(sessionId: string): Promise<Debrief>;
  /** One coaching turn: a clip in, a captioned and spoken reply out. */
  say(sessionId: string, clip: Blob): Promise<CoachTurn>;
  /** A re-answer to the weak answer at this rank. Anchored by rank, per #59. */
  spar(sessionId: string, rank: number, clip: Blob): Promise<CoachTurn>;
  playback(sessionId: string): Promise<Playback>;
}

export interface DebriefApiOptions {
  baseUrl: string;
  accessToken(): Promise<string>;
  fetch?: typeof fetch;
}

/** The wire's spelling, before the app renames it. */
interface WeakAnswerBody {
  ordinal: number;
  question: string;
  asked_by: string;
  answer: string | null;
  weakness: WeaknessKind;
  why: string;
}

export function createDebriefApi({
  baseUrl,
  accessToken,
  fetch: fetcher = fetch,
}: DebriefApiOptions): DebriefApi {
  const send = async (path: string, init: RequestInit = {}): Promise<Response> => {
    const response = await fetcher(`${baseUrl}${path}`, {
      ...init,
      headers: {
        // Deliberately nothing else. A multipart body needs a boundary in its
        // Content-Type and only the runtime knows the one it generated; setting
        // the header by hand produces a body the server cannot split, which
        // surfaces as a 422 about a missing field rather than as a bad header.
        Authorization: `Bearer ${await accessToken()}`,
      },
    });

    if (response.status === 401) {
      throw new SignedOut(`refused by ${path}`);
    }

    if (!response.ok) {
      throw await refusal(response, path);
    }

    return response;
  };

  /**
   * The server's own code and sentence, or an honest stand-in.
   *
   * A refusal is not guaranteed to be ours: a proxy that gave up returns HTML,
   * and parsing that as JSON throws on top of the real failure — which is how a
   * 502 reaches somebody as "Unexpected token < in JSON".
   */
  const refusal = async (response: Response, path: string): Promise<Refused> => {
    try {
      const body = (await response.json()) as { error?: { code?: string; message?: string } };
      if (body.error?.code) {
        return new Refused(
          body.error.code,
          body.error.message ?? 'That did not work.',
          response.status
        );
      }
    } catch {
      // Falls through to the unnamed refusal below.
    }

    return new Refused('unreachable', `${path} failed with ${response.status}`, response.status);
  };

  const turn = async (path: string, clip: Blob): Promise<CoachTurn> => {
    const form = new FormData();
    // `clip` is the field name both handlers read. Named here rather than
    // derived, because a mismatch is a 422 the user sees as the recording
    // having failed.
    form.append('clip', clip, 'turn.wav');

    return (await (await send(path, { method: 'POST', body: form })).json()) as CoachTurn;
  };

  return {
    read: async (sessionId) => {
      const body = (await (
        await send(`/v1/sessions/${sessionId}/debrief`)
      ).json()) as { weak_answers: WeakAnswerBody[]; pressed: Pressed };

      return {
        weakAnswers: body.weak_answers.map((weak) => ({
          ordinal: weak.ordinal,
          question: weak.question,
          askedBy: weak.asked_by,
          answer: weak.answer,
          weakness: weak.weakness,
          why: weak.why,
        })),
        pressed: body.pressed ?? null,
      };
    },

    say: (sessionId, clip) => turn(`/v1/sessions/${sessionId}/debrief/turns`, clip),

    spar: (sessionId, rank, clip) =>
      turn(`/v1/sessions/${sessionId}/debrief/weak-answers/${rank}/attempts`, clip),

    playback: async (sessionId) => {
      const body = (await (
        await send(`/v1/sessions/${sessionId}/recording`)
      ).json()) as { url: string; expires_in_seconds: number };

      return { url: body.url, expiresInSeconds: body.expires_in_seconds };
    },
  };
}
