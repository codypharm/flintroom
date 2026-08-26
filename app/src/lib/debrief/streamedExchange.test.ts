import { streamedExchange, type Exchange } from './streamedExchange';

/**
 * The order is the product: caption at the fence, voice on the first frame,
 * and a late death never turns into a duplicate turn.
 */

function fakeVoice() {
  const calls: string[] = [];
  return {
    calls,
    begin: () => calls.push('begin'),
    playChunk: (b64: string) => calls.push(`chunk:${b64}`),
    play: (speech: string) => calls.push(`play:${speech}`),
  };
}

const never = async (): Promise<Exchange> => {
  throw new Error('the fallback must not run');
};

it('hands the caption over before the voice starts', async () => {
  const voice = fakeVoice();
  const order: string[] = [];

  const exchange = await streamedExchange({
    stream: async ({ onHeard, onText, onSpeech }) => {
      onHeard('my answer');
      onText('Try it with the base first.');
      onSpeech(btoa('\x01\x02'));
      onSpeech(btoa('\x03'));
    },
    fallback: never,
    voice: { ...voice, begin: () => order.push('voice') },
    onText: () => order.push('caption'),
  });

  expect(order).toEqual(['caption', 'voice']);
  expect(exchange.said).toBe('Try it with the base first.');
  expect(exchange.heard).toBe('my answer');
  expect(atob(exchange.speech)).toBe('\x01\x02\x03');
});

it('a stream that dies after the words resolves voiceless, never retries', async () => {
  const voice = fakeVoice();
  let captioned: Exchange | null = null;

  const exchange = await streamedExchange({
    stream: async ({ onText }) => {
      onText('Try it with the base first.');
      throw new Error('connection reset');
    },
    fallback: never,
    voice,
    onText: (shown) => {
      captioned = shown;
    },
  });

  expect(captioned).not.toBeNull();
  expect(exchange.speech).toBe('');
});

it('a stream that dies before anything was shown falls back to the one-shot turn', async () => {
  const voice = fakeVoice();
  const spoken: Exchange = { heard: 'hm', said: 'Again, with a number.', speech: btoa('\x05') };

  const exchange = await streamedExchange({
    stream: async () => {
      throw new Error('stream unsupported');
    },
    fallback: async () => spoken,
    voice,
    onText: () => {},
  });

  expect(exchange).toEqual(spoken);
  expect(voice.calls).toEqual([`play:${btoa('\x05')}`]);
});
