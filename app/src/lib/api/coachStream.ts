/**
 * One coaching turn over an event stream — the words before the voice.
 *
 * The app half of #107 item 1. The server prepares the whole turn first (the
 * fence judges the complete reply; every refusal is an ordinary HTTP error),
 * then streams: `heard`, `text`, each `speech` frame as the vendor produces
 * it, `done`. This client hands each frame to its handler the moment it
 * arrives — the caption is on screen while the voice is still being made.
 *
 * **RN's built-in fetch cannot stream a response body**, so the default here
 * is `expo/fetch`, resolved lazily for the same reason the store resolves its
 * native module lazily: Jest can never load it, and a caller injecting a fake
 * never touches it.
 */

export interface StreamedTurnOptions {
  url: string;
  accessToken(): Promise<string>;
  clip: ArrayBuffer;
  onHeard(text: string): void;
  onText(text: string): void;
  onSpeech(b64: string): void;
  fetch?: typeof fetch;
}

/** The room is settled or was never yours — same meaning as the JSON client's 404/422. */
export class RoomOverInStream extends Error {}

export async function streamedTurn({
  url,
  accessToken,
  clip,
  onHeard,
  onText,
  onSpeech,
  fetch: fetcher = streamingFetch(),
}: StreamedTurnOptions): Promise<void> {
  const response = await fetcher(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'audio/wav',
      Authorization: `Bearer ${await accessToken()}`,
    },
    body: clip,
  });

  if (response.status === 404 || response.status === 422) {
    throw new RoomOverInStream(`refused with ${response.status}`);
  }
  if (!response.ok || response.body === null) {
    throw new Error(`the coach stream answered ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let held = '';

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;

    held += decoder.decode(value, { stream: true });

    // Frames end on a blank line. Anything after the last one is a frame
    // still arriving, kept for the next chunk — the split test's whole point.
    const frames = held.split('\n\n');
    held = frames.pop() ?? '';

    for (const frame of frames) {
      let event = '';
      let data = '';
      for (const line of frame.split('\n')) {
        if (line.startsWith('event: ')) event = line.slice('event: '.length);
        else if (line.startsWith('data: ')) data = line.slice('data: '.length);
      }

      if (event === 'heard') onHeard((JSON.parse(data) as { text: string }).text);
      else if (event === 'text') onText((JSON.parse(data) as { text: string }).text);
      else if (event === 'speech') onSpeech((JSON.parse(data) as { b64: string }).b64);
      // `error` after `text` is a voiceless turn, not a failed one: the words
      // are the accessibility floor and the client already holds them. `done`
      // and `error` both just end the read.
      else if (event === 'done' || event === 'error') return;
    }
  }
}

/**
 * The streaming-capable fetch, reached only when a method actually runs — a
 * runtime without it (Jest) never gets here, and every test injects its own.
 */
function streamingFetch(): typeof fetch {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  return (require('expo/fetch') as { fetch: typeof fetch }).fetch;
}
