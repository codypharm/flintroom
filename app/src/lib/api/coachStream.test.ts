import { streamedTurn, RoomOverInStream } from './coachStream';

/**
 * The coach's words before their voice — the app half of #107 item 1.
 *
 * The server ships `heard`, then `text`, then each speech frame as the vendor
 * produces it, then `done`. This client's whole job is to hand each frame to
 * its handler the moment it arrives — the text handler firing before the first
 * speech frame is the entire point, so the order of calls is asserted, not
 * just their contents.
 */

function bodyOf(...chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}

const sse = (event: string, data: object) =>
  `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;

function fetcherAnswering(body: ReadableStream<Uint8Array>, status = 200) {
  return jest.fn().mockResolvedValue({ ok: status < 400, status, body });
}

type Handlers = Pick<Parameters<typeof streamedTurn>[0], 'onHeard' | 'onText' | 'onSpeech'>;

const turn = (fetcher: unknown, handlers: Handlers) =>
  streamedTurn({
    url: 'https://flintroom.test/v1/sessions/s-1/debrief/turns/stream',
    accessToken: async () => 'a-token',
    clip: new ArrayBuffer(4),
    fetch: fetcher as typeof fetch,
    ...handlers,
  });

it('hands over each frame as it arrives, words before voice', async () => {
  const calls: string[] = [];
  const fetcher = fetcherAnswering(
    bodyOf(
      sse('heard', { text: 'my answer' }),
      sse('text', { text: 'The coach replies.' }),
      sse('speech', { b64: 'AAE=' }),
      sse('speech', { b64: 'AgM=' }),
      sse('done', {}),
    ),
  );

  await turn(fetcher, {
    onHeard: (text: string) => calls.push(`heard:${text}`),
    onText: (text: string) => calls.push(`text:${text}`),
    onSpeech: (b64: string) => calls.push(`speech:${b64}`),
  });

  expect(calls).toEqual([
    'heard:my answer',
    'text:The coach replies.',
    'speech:AAE=',
    'speech:AgM=',
  ]);
  const [url, init] = fetcher.mock.calls[0];
  expect(url).toBe('https://flintroom.test/v1/sessions/s-1/debrief/turns/stream');
  expect(init.headers.Authorization).toBe('Bearer a-token');
});

it('survives frames split across network chunks', async () => {
  const calls: string[] = [];
  const whole = sse('heard', { text: 'hm' }) + sse('text', { text: 'Try again.' }) + sse('done', {});
  const fetcher = fetcherAnswering(bodyOf(whole.slice(0, 17), whole.slice(17, 40), whole.slice(40)));

  await turn(fetcher, {
    onHeard: (text: string) => calls.push(`heard:${text}`),
    onText: (text: string) => calls.push(`text:${text}`),
    onSpeech: () => calls.push('speech'),
  });

  expect(calls).toEqual(['heard:hm', 'text:Try again.']);
});

it('a voiceless turn still resolves — the words are the floor', async () => {
  // The server sends `error` after `text` when the synthesiser fails. The
  // client already holds the words, which is the accessibility floor, so the
  // turn is a success with no audio rather than a failure with a caption.
  const calls: string[] = [];
  const fetcher = fetcherAnswering(
    bodyOf(
      sse('heard', { text: 'hm' }),
      sse('text', { text: 'Try again.' }),
      sse('error', { code: 'speech_unavailable' }),
    ),
  );

  await turn(fetcher, {
    onHeard: () => calls.push('heard'),
    onText: () => calls.push('text'),
    onSpeech: () => calls.push('speech'),
  });

  expect(calls).toEqual(['heard', 'text']);
});

it('a refusal before any frame is a thrown error, not a silent nothing', async () => {
  const fetcher = fetcherAnswering(bodyOf(''), 404);

  await expect(
    turn(fetcher, { onHeard: () => {}, onText: () => {}, onSpeech: () => {} }),
  ).rejects.toThrow(RoomOverInStream);
});

it('a stream that dies before the text is an error the caller can fall back on', async () => {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode('event: heard\ndata: {"text":"hm"}\n\n'));
      controller.error(new Error('connection reset'));
    },
  });

  await expect(
    turn(fetcherAnswering(body), { onHeard: () => {}, onText: () => {}, onSpeech: () => {} }),
  ).rejects.toThrow('connection reset');
});
