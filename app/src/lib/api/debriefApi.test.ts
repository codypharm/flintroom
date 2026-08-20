import { SignedOut } from '../auth/session';
import { createDebriefApi, Refused } from './debriefApi';

/**
 * The four endpoints Phase 4 built and nothing could reach.
 *
 * What is under test here is almost entirely the refusal mapping, and that is
 * the substance rather than plumbing: this API answers a bad request with five
 * different typed codes, and each one means something different to the person
 * holding the phone. A client that collapsed them into "something went wrong"
 * would tell somebody whose provider failed — and whose minutes are already
 * back — to try again on a room that will never work.
 */

const SESSION = '3f1a0c2e-8b4d-4a19-9c77-2e5b6d0f1a34';

function refusing(status: number, code: string, message: string) {
  return jest.fn(async () => ({
    ok: false,
    status,
    json: async () => ({ error: { code, message } }),
  })) as unknown as typeof fetch;
}

function answering(status: number, body: unknown) {
  return jest.fn(async () => ({
    ok: status < 400,
    status,
    json: async () => body,
  })) as unknown as typeof fetch;
}

function api(fetcher: typeof fetch) {
  return createDebriefApi({
    baseUrl: 'https://api.test',
    accessToken: async () => 'token',
    fetch: fetcher,
  });
}

describe('read', () => {
  it('renames the wire to what the app calls things', async () => {
    const fetcher = answering(200, {
      weak_answers: [
        {
          ordinal: 3,
          question: 'What happens at ten times the load?',
          asked_by: 'technical_skeptic',
          answer: 'We are excited about the roadmap.',
          weakness: 'evasive',
          why: 'You deflected to the roadmap.',
          next_time: 'Say what breaks first, and at what number.',
        },
      ],
      pressed: 'harder',
    });

    const debrief = await api(fetcher).read(SESSION);

    expect(debrief.pressed).toBe('harder');
    expect(debrief.weakAnswers[0]).toEqual({
      ordinal: 3,
      question: 'What happens at ten times the load?',
      askedBy: 'technical_skeptic',
      answer: 'We are excited about the roadmap.',
      weakness: 'evasive',
      why: 'You deflected to the roadmap.',
      nextTime: 'Say what breaks first, and at what number.',
    });
  });

  it('reads a missing suggestion as null rather than as undefined', async () => {
    // A finding whose suggestion the server dropped — it named a figure the
    // room never said — or one from a room read before suggestions existed.
    // Null is a real answer here and the screen branches on it; `undefined`
    // would branch the same way today and stop doing so the moment anybody
    // writes `in` or `hasOwnProperty` against it.
    const fetcher = answering(200, {
      weak_answers: [
        {
          ordinal: 3,
          question: 'What happens at ten times the load?',
          asked_by: 'technical_skeptic',
          answer: null,
          weakness: 'evasive',
          why: 'You deflected to the roadmap.',
        },
      ],
      pressed: null,
    });

    const debrief = await api(fetcher).read(SESSION);

    expect(debrief.weakAnswers[0].nextTime).toBeNull();
  });

  it('keeps an empty list as a list, not as an absence', async () => {
    // `DebriefRead` says this in as many words: an empty list is "this room had
    // nothing worth raising", and it is not the same as any of the refusals.
    // A client that turned it into null would draw the same screen for "you did
    // well" as for "there is no session here".
    const debrief = await api(answering(200, { weak_answers: [], pressed: null })).read(
      SESSION
    );

    expect(debrief.weakAnswers).toEqual([]);
    expect(debrief.pressed).toBeNull();
  });

  it.each([
    [409, 'session_not_settled'],
    [422, 'room_has_no_questions'],
    [422, 'room_broke'],
  ])('tells the %i refusals apart by code, not by status', async (status, code) => {
    // The status alone is not enough, and two of these share one. `room_broke`
    // means the minutes are already back and the answer is a fresh room;
    // `room_has_no_questions` means this room is simply over. Same 422, and
    // the recoveries have nothing in common.
    await expect(api(refusing(status, code, 'refused')).read(SESSION)).rejects.toMatchObject({
      code,
    });
  });
});

describe('refusals', () => {
  it('names the code and keeps the server sentence', async () => {
    const promise = api(
      refusing(422, 'room_broke', 'Your minutes have been returned.')
    ).read(SESSION);

    await expect(promise).rejects.toBeInstanceOf(Refused);
    await expect(promise).rejects.toMatchObject({
      code: 'room_broke',
      // Kept so a code this app has never heard of still says something true
      // rather than nothing. The screen prefers its own copy where it has some.
      message: 'Your minutes have been returned.',
    });
  });

  it('ends the session on a 401 rather than reporting a refusal', async () => {
    // The split every client here draws. A 401 is not a thing the debrief
    // screen can explain; it is the app no longer being signed in.
    await expect(api(refusing(401, 'not_authenticated', 'no')).read(SESSION)).rejects.toBeInstanceOf(
      SignedOut
    );
  });

  it('survives a refusal with no parseable body', async () => {
    // A proxy timing out returns HTML, and a client that assumed JSON would
    // throw a parse error on top of the real failure — which is how a 502
    // reaches a user as "Unexpected token < in JSON".
    const fetcher = jest.fn(async () => ({
      ok: false,
      status: 502,
      json: async () => {
        throw new SyntaxError('Unexpected token <');
      },
    })) as unknown as typeof fetch;

    await expect(api(fetcher).read(SESSION)).rejects.toBeInstanceOf(Refused);
  });
});

describe('say', () => {
  it('posts the WAV as the whole body, because there is nothing else to send', async () => {
    const fetcher = answering(201, {
      text: 'Say the payback figure first.',
      speech: 'AAA=',
      heard: 'Payback lands around four months.',
    });
    const clip = new Uint8Array([1, 2, 3]).buffer;

    const turn = await api(fetcher).say(SESSION, clip);

    // `heard` comes back with the reply because a transcription error is
    // otherwise indistinguishable from the coach missing the point.
    expect(turn).toEqual({
      text: 'Say the payback figure first.',
      speech: 'AAA=',
      heard: 'Payback lands around four months.',
    });

    const [url, init] = (fetcher as jest.Mock).mock.calls[0];
    expect(url).toBe(`https://api.test/v1/sessions/${SESSION}/debrief/turns`);
    // The bytes themselves, not a form part wrapping them. Multipart exists to
    // carry several parts and this request has one, with the session already in
    // the path — the shape Deepgram and AssemblyAI take for the same job.
    //
    // It is also the only shape React Native can send from memory:
    // `BlobManager` refuses an ArrayBuffer, and `FormData` has no part type for
    // one, so multipart here would mean writing the user's voice to disk purely
    // to satisfy the envelope. `convertRequestBody` takes this directly.
    expect(init.body).toBe(clip);
    expect(init.headers['Content-Type']).toBe('audio/wav');
  });

  it('refuses a clip the server called too long, by its own code', async () => {
    const promise = api(
      refusing(413, 'clip_too_long', 'That recording is too long.')
    ).say(SESSION, new ArrayBuffer(0));

    await expect(promise).rejects.toMatchObject({ code: 'clip_too_long' });
  });

  it('carries nothing_was_said through, which is not a failure of the recording', async () => {
    // Somebody tapped record and said nothing. The distinction matters: this is
    // the one refusal whose recovery is "say it again", not "something broke".
    const promise = api(
      refusing(422, 'nothing_was_said', "I didn't catch anything there.")
    ).say(SESSION, new ArrayBuffer(0));

    await expect(promise).rejects.toMatchObject({ code: 'nothing_was_said' });
  });
});

describe('spar', () => {
  it('addresses the rank in the path, never in the body', async () => {
    // `docs/debrief-and-sparring.md` decision 4's anchor. A re-answer is fresh
    // speech about the session, and naming the question in the path is what
    // makes "spar me on this instead" unexpressible.
    const fetcher = answering(201, { text: 'Closer.', speech: 'AAA=', heard: 'Two million.' });

    await api(fetcher).spar(SESSION, 2, new ArrayBuffer(0));

    const [url, init] = (fetcher as jest.Mock).mock.calls[0];
    expect(url).toBe(
      `https://api.test/v1/sessions/${SESSION}/debrief/weak-answers/2/attempts`
    );
    expect(init.body).toBeInstanceOf(ArrayBuffer);
  });

  it('refuses a rank this room does not have', async () => {
    // Reachable by holding a rank from a different session — a phone that
    // resumed onto a screen whose data has moved on.
    const promise = api(
      refusing(404, 'no_such_weak_answer', "That isn't one of this session's questions.")
    ).spar(SESSION, 9, new ArrayBuffer(0));

    await expect(promise).rejects.toMatchObject({ code: 'no_such_weak_answer' });
  });
});

describe('playback', () => {
  it('reads the link and how long it lasts', async () => {
    // `expires_in_seconds` is published so a client can decide whether to reuse
    // the link it holds. Dropping it would leave playing and failing as the
    // only way to find out.
    const playback = await api(
      answering(200, { url: 'https://store.test/room.opus', expires_in_seconds: 900 })
    ).playback(SESSION);

    expect(playback).toEqual({
      url: 'https://store.test/room.opus',
      expiresInSeconds: 900,
    });
  });

  it('refuses a room with nothing stored, distinctly from a broken one', async () => {
    // Recording can be off by preference, or expired on the tier window. Both
    // are ordinary and neither is an error the user caused.
    const promise = api(
      refusing(404, 'recording_not_available', 'There is no saved audio for this room.')
    ).playback(SESSION);

    await expect(promise).rejects.toMatchObject({ code: 'recording_not_available' });
  });
});
