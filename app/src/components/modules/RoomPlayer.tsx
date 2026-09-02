import { useCallback, useEffect, useImperativeHandle, useRef, useState } from 'react';
import { useAudioPlayer, useAudioPlayerStatus } from 'expo-audio';

import { Refused } from '../../lib/api/refused';
import { forPlayingBack } from '../../lib/replay/session';
import { RoomPlayback, type Heard } from './RoomPlayback';

/**
 * Hearing a room again — the half that reaches the audio layer.
 *
 * Split from `RoomPlayback` so that everything the screen *says* stays on
 * the presentation side of the seam, testable without a native decoder.
 *
 * **`expo-audio` underneath, since #25.** The old library's published
 * playback route decoded a whole room into memory before the first sound —
 * a crash on long rooms — so #68 reached its streaming element by a private
 * path, held in place by an exact version pin. `expo-audio` is a thin
 * wrapper over the platform players (ExoPlayer, AVPlayer), which stream
 * over HTTP ranges as their ordinary behaviour, on both platforms, through
 * a published API. The deep import and the pin die with this file's
 * previous version.
 *
 * **The link is signed on the tap, never on the way in.** `presign_get`
 * issues a URL that lives fifteen minutes, and this screen is mostly used
 * for reading a transcript — somebody who scrolls a forty-turn room first
 * and then decides to hear it would arrive at a dead link. Signing costs
 * nothing at the moment of the tap and it is the only moment we know
 * somebody wants it.
 *
 * **The player is created only once there is a link**, which is also what
 * stops it fetching: a player mounted against a source begins loading it,
 * and one request per glance at a past room is the thing the lazy presign
 * exists to avoid.
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
   * **A command, not a prop, and the shape is the decision.** Somebody
   * tapping a timestamp wants both halves at once: the link signed if it is
   * not already, and the playhead put on that second. As a changing prop
   * that would be an effect kicking off a fetch and setting state, needing a
   * nonce beside the seconds so tapping the *same* line twice is not
   * silently a no-op. A handle needs none of that: two taps are two calls.
   */
  ref?: React.Ref<RoomPlayerHandle>;
}

/** What a caller may ask of a mounted player. */
export interface RoomPlayerHandle {
  /**
   * Open the room if it is not open, and land on this second.
   *
   * Safe before anything is mounted, which is the ordinary case rather than
   * a corner: the tap almost always arrives while the transcript is all
   * that is on screen. The position waits for a loaded player and is spent
   * the moment one is ready.
   */
  hearFrom: (seconds: number) => void;
}

export function RoomPlayer({ findIt, ref }: RoomPlayerProps) {
  const [url, setUrl] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);
  const [refusal, setRefusal] = useState<string | null>(null);
  /**
   * A seek waiting for a player to land it.
   *
   * State rather than a ref, and `nth` rather than the seconds alone: a ref
   * write does not re-render, so a second request while already mounted sat
   * unspent until unrelated updates happened to re-run the effect — a thing
   * that worked by accident. `nth` makes asking for the *same* second twice
   * a new request; missing it the first time is a real thing to do.
   */
  const [wanted, setWanted] = useState<{ seconds: number; nth: number } | null>(null);

  const hearIt = useCallback(() => {
    setAsking(true);
    setRefusal(null);
    // Before the link rather than after it. The session is process-wide and
    // the last screen to touch it left it configured for a two-way call —
    // or, on a cold launch into the Library, nobody has touched it and the
    // platform default honours the ringer switch. See `forPlayingBack`.
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
        // would send somebody back to try again at something that will
        // never work.
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
        // Signing here as well as on the transport's own control, because
        // the two taps mean the same thing to the person making them. A
        // second call while a link is in flight signs a second one and the
        // last to land wins — which costs a presign and never a wrong
        // position.
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
    <Sounding
      url={url}
      refusal={refusal}
      wanted={wanted}
      onBroke={() => {
        // Never the platform's words: whatever the decoder or the store
        // said may carry a signed URL with our bucket host in it, and
        // `CLAUDE.md` forbids naming a provider to the user either way.
        setRefusal('That did not play. Try it again in a moment.');
        // Dropped, so the next tap signs a fresh link rather than retrying
        // a URL that may simply have expired mid-stream.
        setUrl(null);
      }}
    />
  );
}

/**
 * The half that holds a live player. Its own component so the player hooks
 * run only once a link exists — hooks cannot be conditional, but mounting
 * can be.
 */
function Sounding({
  url,
  refusal,
  wanted,
  onBroke,
}: {
  url: string;
  refusal: string | null;
  wanted: { seconds: number; nth: number } | null;
  onBroke: () => void;
}) {
  const player = useAudioPlayer({ uri: url });
  const status = useAudioPlayerStatus(player);

  /**
   * Straight into it, once. The tap already said "hear this room", and a
   * second tap to start what the first one asked for is the control not
   * working. Once, because pause must not be undone by a status update.
   */
  const started = useRef(false);
  useEffect(() => {
    if (status.isLoaded && !started.current) {
      started.current = true;
      player.play();
    }
  }, [status.isLoaded, player]);

  /**
   * Land on a moment somebody asked for, once there is something loaded to
   * land on — the platform discards a seek on an unloaded player silently,
   * which would look exactly like a timestamp that does nothing. `spent`
   * stops position updates replaying the same request forever.
   */
  const spent = useRef(0);
  useEffect(() => {
    if (wanted === null || wanted.nth === spent.current || !status.isLoaded) return;

    spent.current = wanted.nth;
    void player.seekTo(wanted.seconds);
    player.play();
  }, [wanted, status.isLoaded, player]);

  /** A stream that died mid-play surfaces through status, not a callback. */
  const broke = status.playbackState === 'failed';
  useEffect(() => {
    if (broke) onBroke();
  }, [broke, onBroke]);

  /**
   * Whether Play would start at the end of the room. Read off the position
   * rather than remembered from an ended event, because the same thing is
   * true of somebody who dragged the bar to the end — an event would cover
   * one case and not the other. The quarter-second is the reporting
   * interval's gap.
   */
  const ended = status.duration > 0 && status.currentTime >= status.duration - 0.25;

  const state: Heard =
    refusal !== null
      ? 'failed'
      : status.playing
        ? 'playing'
        : status.isLoaded
          ? 'paused'
          : 'opening';

  return (
    <RoomPlayback
      state={state}
      at={status.currentTime}
      runs={status.duration}
      refusal={refusal}
      onPlay={() => {
        if (ended) void player.seekTo(0);
        player.play();
      }}
      onPause={() => player.pause()}
      onSeek={(seconds) => void player.seekTo(seconds)}
    />
  );
}
