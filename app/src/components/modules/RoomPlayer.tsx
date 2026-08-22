import { useCallback, useEffect, useImperativeHandle, useRef, useState } from 'react';

import { Refused } from '../../lib/api/refused';
import { AudioElement, useAudioTagContext } from '../../lib/replay/element';
import { forPlayingBack } from '../../lib/replay/session';
import { RoomPlayback, type Heard } from './RoomPlayback';

/**
 * Hearing a room again — the half that reaches the audio layer.
 *
 * Split from `RoomPlayback` so that everything the screen *says* stays on the
 * other side of a private import (#68). What is here is the link, the element,
 * and the four things that can go wrong; what is there is every sentence and
 * every control, testable without a native decoder.
 *
 * **The link is signed on the tap, never on the way in.** `presign_get` issues
 * a URL that lives fifteen minutes, and this screen is mostly used for reading
 * a transcript — somebody who scrolls a forty-turn room first and then decides
 * to hear it would arrive at a dead link. Signing costs nothing at the moment
 * of the tap and it is the only moment we know somebody wants it.
 *
 * **The element is mounted only once there is a link**, which is also what
 * stops it fetching. `preload` defaults to `auto`, so an element rendered
 * against an empty source on every visit would be a network request per glance
 * at a past room.
 */

export interface RoomPlayerProps {
  /**
   * Sign a fresh link to this room's audio.
   *
   * A function rather than a URL, because *when* it is called is the design.
   * The caller owns which room and which credential; this owns the moment.
   */
  findIt: () => Promise<string>;
  /**
   * How the transcript above asks for a moment — #69's payoff.
   *
   * **A command, not a prop, and the shape is the decision.** Somebody tapping
   * a timestamp wants both halves at once: the link signed if it is not
   * already, and the playhead put on that second. Expressed as a changing prop
   * that would be an effect kicking off a fetch and setting state — which React
   * rightly warns about, and which needs a nonce beside the seconds so that
   * tapping the *same* line twice is not silently a no-op.
   *
   * A handle needs none of that. Two taps are two calls, and the request looks
   * like the imperative thing it is.
   */
  ref?: React.Ref<RoomPlayerHandle>;
}

/** What a caller may ask of a mounted player. */
export interface RoomPlayerHandle {
  /**
   * Open the room if it is not open, and land on this second.
   *
   * Safe before anything is mounted, which is the ordinary case rather than a
   * corner: the tap almost always arrives while the transcript is all that is
   * on screen. The position waits for an element to exist and is spent the
   * moment one is ready.
   */
  hearFrom: (seconds: number) => void;
}

export function RoomPlayer({ findIt, ref }: RoomPlayerProps) {
  const [url, setUrl] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);
  const [refusal, setRefusal] = useState<string | null>(null);
  /**
   * A seek waiting for an element to play it on.
   *
   * The tap that asks for a moment usually arrives while nothing is mounted —
   * the ordinary case, not a corner — so the position is held here and spent by
   * `Chrome` once there is a tag to spend it on.
   *
   * **State rather than a ref, and `nth` rather than the seconds alone.** A ref
   * was tried first and is quietly broken: writing one does not re-render, so a
   * second request while the element is already mounted sat there until some
   * unrelated tag update happened to re-run the effect. It appeared to work
   * only because position tracking re-renders constantly, which is a thing that
   * works by accident.
   *
   * `nth` makes asking for the *same* second twice a new request. Tapping one
   * line twice is a real thing to do — you missed it the first time — and
   * without the counter the second tap would be a no-op.
   */
  const [wanted, setWanted] = useState<{ seconds: number; nth: number } | null>(null);

  const hearIt = useCallback(() => {
    setAsking(true);
    setRefusal(null);
    // Before the link rather than after it. The session is process-wide and the
    // last screen to touch it left it configured for a two-way call — or, on a
    // cold launch into the Library, nobody has touched it and the platform
    // default honours the ringer switch. See `forPlayingBack`.
    forPlayingBack();

    void findIt()
      .then((signed) => {
        setUrl(signed);
        setAsking(false);
      })
      .catch((error: unknown) => {
        setAsking(false);
        // The server's own sentence when it had one. A room whose audio was
        // switched off, expired on the tier window, or deleted from further
        // down this same screen is not a failure — and "that did not play"
        // would send somebody back to try again at something that will never
        // work.
        setRefusal(
          error instanceof Refused
            ? error.message
            : 'That did not play. Try it again in a moment.'
        );
      });
  }, [findIt]);

  useImperativeHandle(
    ref,
    () => ({
      hearFrom: (seconds: number) => {
        setWanted((asked) => ({ seconds, nth: (asked?.nth ?? 0) + 1 }));
        // Signing here as well as on the transport's own control, because the
        // two taps mean the same thing to the person making them. A second
        // call while a link is in flight signs a second one and the last to
        // land wins — which costs a presign and never a wrong position.
        hearIt();
      },
    }),
    [hearIt]
  );

  if (url === null) {
    return (
      <RoomPlayback
        state={asking ? 'opening' : refusal === null ? 'idle' : 'failed'}
        at={0}
        runs={0}
        refusal={refusal}
        onPlay={hearIt}
        onPause={() => undefined}
        onSeek={() => undefined}
      />
    );
  }

  return (
    <AudioElement
      source={{ uri: url }}
      // Straight into it. The tap already said "hear this room", and a second
      // tap to start what the first one asked for is the control not working.
      autoPlay
      // Left at its default `false`, which is what streams over HTTP ranges
      // rather than pulling the whole room down first — the entire reason this
      // element is reached by a private path at all (#68).
      forceDownload={false}
      onError={(error: Error) => {
        // Never the vendor's words. `CLAUDE.md` forbids naming a provider to
        // the user, and this message is whatever the decoder or the store said
        // — which on a bad day is a signed URL with our bucket host in it.
        void error;
        setRefusal('That did not play. Try it again in a moment.');
        // Dropped, so the next tap signs a fresh link rather than retrying a
        // URL that may simply have expired mid-stream.
        setUrl(null);
      }}
    >
      <Chrome refusal={refusal} wanted={wanted} />
    </AudioElement>
  );
}

/**
 * The transport, fed from the element's own context.
 *
 * A child rather than a sibling because `duration` and `currentTime` are
 * published only on that context — the imperative handle carries the verbs and
 * none of the readings — so anything that shows a position has to be inside.
 */
function Chrome({
  refusal,
  wanted,
}: {
  refusal: string | null;
  wanted: { seconds: number; nth: number } | null;
}) {
  const tag = useAudioTagContext();

  /**
   * The last request actually spent, so position updates do not replay it.
   *
   * This effect re-runs on every `tag` change — which is constantly, because
   * `currentTime` advances — and without a mark, one tapped timestamp would
   * drag the playhead back to it forever.
   */
  const spent = useRef(0);

  /**
   * Land on a moment somebody asked for, once there is something to land on.
   *
   * Waits for `ready`: seeking an element that has not loaded is discarded
   * silently by the platform, which would look exactly like a timestamp that
   * does nothing — on the one control whose entire point is that it lands
   * somewhere.
   */
  useEffect(() => {
    if (wanted === null || wanted.nth === spent.current || !tag.ready) return;

    spent.current = wanted.nth;
    tag.seekToTime(wanted.seconds);
    tag.play();
  }, [wanted, tag]);

  /**
   * Whether Play would start at the end of the room.
   *
   * Read off the position rather than remembered from an `ended` event, because
   * the same thing is true of somebody who dragged the bar to the end and then
   * pressed Play — an event would have covered one case and not the other. The
   * quarter-second is the gap position tracking leaves behind: it reports on an
   * interval, so the last reading before a room ends is a fraction short of the
   * duration rather than equal to it.
   */
  const ended = tag.duration > 0 && tag.currentTime >= tag.duration - 0.25;

  const state: Heard =
    refusal !== null
      ? 'failed'
      : tag.playbackState === 'playing'
        ? 'playing'
        : tag.ready
          ? 'paused'
          : 'opening';

  return (
    <RoomPlayback
      state={state}
      at={tag.currentTime}
      runs={tag.duration}
      refusal={refusal}
      onPlay={() => {
        if (ended) tag.seekToTime(0);
        tag.play();
      }}
      onPause={tag.pause}
      onSeek={tag.seekToTime}
    />
  );
}
