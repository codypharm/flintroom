import { SignedOut } from '../auth/session';
import { streamedTurn } from './coachStream';
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
  /**
   * What to reach for when this comes up again, or null.
   *
   * The half of a finding that faces forward — an entry that stops at `why`
   * diagnoses and stops. Null when the model offered none, or when what it
   * offered named a figure the room never said and the server dropped it.
   */
  nextTime: string | null;
}

export type StrengthKind = 'held' | 'grounded' | 'conceded' | 'direct';

/** One question the room got a good enough answer to (#118). */
export interface HeldAnswer {
  ordinal: number;
  question: string;
  askedBy: string;
  /** Never null — an answer that held exists, or the server dropped the claim. */
  answer: string;
  strength: StrengthKind;
  /** The coach's sentence about what worked. */
  why: string;
}

/**
 * (held, judged), counted server-side from verified findings (#118).
 *
 * Two integers, never a percentage: the screen renders "1 of 2 held" and
 * derives any figure itself. Null when no score exists — a room debriefed
 * before strengths were judged has no numerator, and null is that fact
 * rather than a zero pretending to be one.
 */
export interface Score {
  held: number;
  judged: number;
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
  /** The answers that held (#118), in transcript order. */
  heldAnswers: HeldAnswer[];
  /** This room's score, or null when none exists. */
  score: Score | null;
  /** The last scored room in this room's lineage, or null on a first attempt. */
  previousScore: Score | null;
  pressed: Pressed;
  /**
   * What the coach says before anybody has said anything, or null.
   *
   * **`speech` is empty on every read after the first**, and that is not a
   * failure — it is the cost decision. A spoken greeting costs about what a
   * minute of live interrogation does, and this is the request a backgrounded
   * phone repeats, so the voice belongs to the arrival. `hearOpeningAgain` is
   * the way back to it.
   *
   * Null on a room whose coaching started at the microphone. Greeting into the
   * middle of a conversation would read as the coach not having listened.
   */
  opening: CoachTurn | null;
  /**
   * The coaching conversation so far, oldest first, without the greeting.
   *
   * #83. This was held only in the debrief screen's `useState`, so
   * backgrounding it — or tapping back and forward — emptied the screen of
   * every question the presenter had asked and every reply. The findings
   * redrew and the conversation did not, which contradicted what the endpoint
   * already promised: that resuming re-fetches.
   *
   * `speech` is empty on every turn, exactly as it is on `opening` after the
   * first read, and for the same reason. `Replay` already draws nothing when
   * there is nothing to play.
   */
  thread: CoachTurn[];
  /**
   * Every re-answer made in this room, by question and then by attempt.
   *
   * Flat and carrying its own `weakRank`, because that is what the wire sends —
   * JSON has no integer keys. The screen groups by rank, which is one `reduce`.
   */
  attempts: SparringAttempt[];
}

export interface SparringAttempt extends CoachTurn {
  /** Which ranked weak answer this was a re-answer to. */
  weakRank: number;
  /** Which go this was, from zero. §3.5 treats the count as content. */
  attempt: number;
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
  say(sessionId: string, clip: ArrayBuffer): Promise<CoachTurn>;

  /**
   * `say`, with the words handed over before the voice — #107 item 1.

   * Resolves when the turn ends; a turn whose synthesis failed still resolves,
   * because the words already arrived and they are the accessibility floor.
   * Throws exactly where `say` would refuse, so a caller can fall back to it.
   */
  sayStreamed(
    sessionId: string,
    clip: ArrayBuffer,
    handlers: TurnStreamHandlers
  ): Promise<void>;
  /** A re-answer to the weak answer at this rank. Anchored by rank, per #59. */
  spar(sessionId: string, rank: number, clip: ArrayBuffer): Promise<CoachTurn>;

  /** `spar`, streamed the same way and for the same reason. */
  sparStreamed(
    sessionId: string,
    rank: number,
    clip: ArrayBuffer,
    handlers: TurnStreamHandlers
  ): Promise<void>;
  /**
   * Say the opening again.
   *
   * Costs a synthesis every time, which is why it is a call rather than a
   * field: it spends money at the moment somebody asks to hear it, and never
   * on a screen that merely redrew.
   */
  hearOpeningAgain(sessionId: string): Promise<CoachTurn>;
}

export interface TurnStreamHandlers {
  onHeard(text: string): void;
  onText(text: string): void;
  onSpeech(b64: string): void;
}

export interface DebriefApiOptions {
  baseUrl: string;
  accessToken(): Promise<string>;
  fetch?: typeof fetch;
  /**
   * The streaming-capable fetch for the SSE turns — `expo/fetch` on a device,
   * injected in tests. Separate from `fetch` because RN's built-in cannot
   * stream a response body, and the JSON calls have no reason to change.
   */
  streamFetch?: typeof fetch;
}

/** The wire's spelling, before the app renames it. */
interface WeakAnswerBody {
  ordinal: number;
  question: string;
  asked_by: string;
  answer: string | null;
  weakness: WeaknessKind;
  why: string;
  next_time: string | null;
}

/** The wire's spelling of an answer that held. */
interface HeldAnswerBody {
  ordinal: number;
  question: string;
  asked_by: string;
  answer: string;
  strength: StrengthKind;
  why: string;
}

/** One stored re-answer, as the wire spells it. */
interface SparringAttemptBody {
  weak_rank: number;
  attempt: number;
  heard: string;
  text: string;
  speech: string;
}

export function createDebriefApi({
  baseUrl,
  accessToken,
  fetch: fetcher = fetch,
  streamFetch,
}: DebriefApiOptions): DebriefApi {
  const streamed = (path: string, clip: ArrayBuffer, handlers: TurnStreamHandlers) =>
    streamedTurn({
      url: `${baseUrl}${path}`,
      accessToken,
      clip,
      ...handlers,
      ...(streamFetch ? { fetch: streamFetch } : {}),
    });
  const send = async (path: string, init: RequestInit = {}): Promise<Response> => {
    const response = await fetcher(`${baseUrl}${path}`, {
      ...init,
      headers: {
        Authorization: `Bearer ${await accessToken()}`,
        // Caller's last, so a turn can declare `audio/wav` over a body that
        // would otherwise arrive as `application/octet-stream` and be handed to
        // the transcriber with no idea what it is holding.
        ...init.headers,
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

  const turn = async (path: string, clip: ArrayBuffer): Promise<CoachTurn> => {
    /**
     * The WAV is the entire body — no multipart, no form part, no file.
     *
     * The request has one thing in it and the session is already in the path,
     * so the envelope multipart exists to provide has nothing to carry. It is
     * the shape a single-clip speech endpoint normally takes.
     *
     * It is also the only shape React Native can send from memory. The recorder
     * hands back PCM, never a file URI, and `BlobManager` throws outright on an
     * ArrayBuffer — so the obvious `new Blob([wav])` failed on every device
     * while the suite passed against jsdom, and every coaching turn reported "I
     * could not reach the server" for a server it never opened a socket to.
     * `convertRequestBody` takes an ArrayBuffer directly and base64s it across
     * the bridge, so the bytes on the wire are real binary either way.
     */
    return (await (
      await send(path, {
        method: 'POST',
        body: clip,
        headers: { 'Content-Type': 'audio/wav' },
      })
    ).json()) as CoachTurn;
  };

  return {
    read: async (sessionId) => {
      const body = (await (
        await send(`/v1/sessions/${sessionId}/debrief`)
      ).json()) as {
        weak_answers: WeakAnswerBody[];
        pressed: Pressed;
        opening: CoachTurn | null;
        thread?: CoachTurn[];
        attempts?: SparringAttemptBody[];
        held_answers?: HeldAnswerBody[];
        score?: Score | null;
        previous_score?: Score | null;
      };

      return {
        opening: body.opening ?? null,
        // Defaulted rather than assumed present, the same way `next_time` is:
        // a room read by a build older than #83 has neither key, and a screen
        // that mapped over `undefined` would throw on a resume instead of
        // showing what it does have.
        thread: body.thread ?? [],
        attempts: (body.attempts ?? []).map((made) => ({
          weakRank: made.weak_rank,
          attempt: made.attempt,
          heard: made.heard,
          text: made.text,
          speech: made.speech,
        })),
        weakAnswers: body.weak_answers.map((weak) => ({
          ordinal: weak.ordinal,
          question: weak.question,
          askedBy: weak.asked_by,
          answer: weak.answer,
          weakness: weak.weakness,
          why: weak.why,
          nextTime: weak.next_time ?? null,
        })),
        pressed: body.pressed ?? null,
        // Defaulted for the reason `thread` is: a server from before #118
        // sends none of these keys, and absence means "no score exists",
        // which is exactly what null already says.
        heldAnswers: (body.held_answers ?? []).map((held) => ({
          ordinal: held.ordinal,
          question: held.question,
          askedBy: held.asked_by,
          answer: held.answer,
          strength: held.strength,
          why: held.why,
        })),
        score: body.score ?? null,
        previousScore: body.previous_score ?? null,
      };
    },

    say: (sessionId, clip) => turn(`/v1/sessions/${sessionId}/debrief/turns`, clip),

    sayStreamed: (sessionId, clip, handlers) =>
      streamed(`/v1/sessions/${sessionId}/debrief/turns/stream`, clip, handlers),

    sparStreamed: (sessionId, rank, clip, handlers) =>
      streamed(
        `/v1/sessions/${sessionId}/debrief/weak-answers/${rank}/attempts/stream`,
        clip,
        handlers
      ),

    spar: (sessionId, rank, clip) =>
      turn(`/v1/sessions/${sessionId}/debrief/weak-answers/${rank}/attempts`, clip),

    hearOpeningAgain: async (sessionId) =>
      (await (
        await send(`/v1/sessions/${sessionId}/debrief/opening/speech`, {
          method: 'POST',
        })
      ).json()) as CoachTurn,
  };
}
