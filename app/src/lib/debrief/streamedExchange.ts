/**
 * One coaching exchange over the stream, with the one-shot turn as the net.
 *
 * The app half of #107 item 1, kept out of the route because this is the part
 * with behaviour worth pinning. The order is the product: the caption is
 * handed over the moment the server's fence passes, the voice starts on the
 * first frame, and the resolved exchange carries the joined audio so "hear
 * that again" replays what was actually heard.
 *
 * Failure sorts by *when*. Before any text arrived, nothing was shown and the
 * one-shot endpoint is a safe retry — the turn it makes is the first one the
 * server records. After the text arrived, the turn already happened: retrying
 * would record the answer twice and charge the synthesiser twice, so a stream
 * that dies late resolves as a voiceless exchange — the words are the
 * accessibility floor, and they are already on screen.
 */

export interface Exchange {
  heard: string;
  said: string;
  speech: string;
}

export interface StreamedExchangeOptions {
  /** The SSE turn, with the handlers filled in by this helper. */
  stream(handlers: {
    onHeard(text: string): void;
    onText(text: string): void;
    onSpeech(b64: string): void;
  }): Promise<void>;
  /** The one-shot turn — reached only when nothing has been shown yet. */
  fallback(): Promise<Exchange>;
  voice: {
    begin(): void;
    playChunk(speech: string): void;
    play(speech: string): void;
  };
  /** The caption, the moment it exists. Fired once. */
  onText(exchange: Exchange): void;
}

export async function streamedExchange({
  stream,
  fallback,
  voice,
  onText,
}: StreamedExchangeOptions): Promise<Exchange> {
  let heard = '';
  let said = '';
  const frames: string[] = [];

  try {
    await stream({
      onHeard: (text) => {
        heard = text;
      },
      onText: (text) => {
        said = text;
        onText({ heard, said, speech: '' });
      },
      onSpeech: (b64) => {
        if (frames.length === 0) {
          voice.begin();
        }
        voice.playChunk(b64);
        frames.push(b64);
      },
    });
  } catch (thrown) {
    if (said) {
      // The turn happened and the words are shown; only the voice was lost.
      return { heard, said, speech: joined(frames) };
    }
    if (thrown instanceof Error && thrown.name === 'RoomOverInStream') {
      throw thrown;
    }
    const turn = await fallback();
    onText(turn);
    voice.play(turn.speech);
    return turn;
  }

  return { heard, said, speech: joined(frames) };
}

/**
 * The frames as one base64 string, byte-identical to the one-shot field.
 *
 * Each frame is encoded alone, so the strings cannot simply be concatenated —
 * padding would land mid-stream. Decoded, joined, re-encoded.
 */
function joined(frames: string[]): string {
  if (frames.length === 0) return '';
  let binary = '';
  for (const frame of frames) binary += atob(frame);
  return btoa(binary);
}
