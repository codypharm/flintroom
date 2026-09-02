package com.flintroom.roomaudio

import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.AudioTrack
import android.media.MediaRecorder
import android.util.Base64
import expo.modules.kotlin.Promise
import expo.modules.kotlin.exception.CodedException
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.atomic.AtomicBoolean

/**
 * The owned audio layer's Android half (#25).
 *
 * The property `app/patches/` grafted onto `react-native-audio-api` lives
 * here as two plain declarations, in code we own:
 *
 * - the recorder opens with `VOICE_COMMUNICATION`, the source that engages
 *   the platform's echo cancellation, and
 * - the player declares `USAGE_VOICE_COMMUNICATION`, which is what tells the
 *   canceller which signal is the far end to subtract.
 *
 * `docs/echo-cancellation.md` measured each half alone making things worse
 * and the pair together reaching exact digital silence on the uplink. It is a
 * property of the *pair*; keeping both declarations in one file is the point
 * of this module existing.
 *
 * Routing — speakerphone, `MODE_IN_COMMUNICATION` — deliberately stays in
 * `modules/audio-routing`. Which speaker the panel comes out of is app
 * policy, decided per screen; which preset a stream opens with is a property
 * of the stream. #26 separated them and nothing here re-joins them.
 *
 * Plain `AudioRecord`/`AudioTrack` rather than Oboe: no NDK, no C++, and at
 * 16 kHz voice frames the Java path's latency is far inside the ~1.5 s
 * illusion budget. The library this replaces used Oboe's raw fast path — and
 * that path *bypassing the pre-processing block where AEC lives* is half of
 * how the patch became necessary.
 */
class RoomAudioModule : Module() {
  companion object {
    /** The wire's rate (`docs/voice-stream-protocol.md`). Both streams. */
    const val SAMPLE_RATE = 16000

    /** 20 ms at the wire rate — the uplink's own frame, in samples. */
    const val FRAME_SAMPLES = 320
  }

  // ── Capture ────────────────────────────────────────────

  private var recorder: AudioRecord? = null
  private var captureThread: Thread? = null
  private val capturing = AtomicBoolean(false)

  // ── Playback ───────────────────────────────────────────

  private var track: AudioTrack? = null
  private var playThread: Thread? = null
  private val playing = AtomicBoolean(false)
  private val queue = LinkedBlockingQueue<ByteArray>()

  /**
   * Set while a discard is in flight, so the writer thread knows the chunk it
   * is holding belongs to a line that was interrupted and must not play.
   */
  private val discarding = AtomicBoolean(false)

  override fun definition() = ModuleDefinition {
    Name("RoomAudio")

    Events("frame", "played")

    AsyncFunction("startCapture") { communication: Boolean, promise: Promise ->
      if (capturing.get()) {
        promise.resolve(null)
        return@AsyncFunction
      }

      val minBuffer = AudioRecord.getMinBufferSize(
        SAMPLE_RATE,
        AudioFormat.CHANNEL_IN_MONO,
        AudioFormat.ENCODING_PCM_16BIT,
      )
      if (minBuffer <= 0) {
        promise.reject(CodedException("ERR_CAPTURE", "no capture path at $SAMPLE_RATE Hz", null))
        return@AsyncFunction
      }

      val record = try {
        AudioRecord(
          // The half of the AEC pair the recorder carries, when a pair is
          // wanted. VOICE_COMMUNICATION engages the platform's echo
          // cancellation for the live room; the debrief's clips ask for MIC
          // instead — nothing plays while somebody answers a coach, so
          // call-tuned processing would only colour a solo recording
          // (#25's last slice; the debrief route documents the refusal).
          if (communication) MediaRecorder.AudioSource.VOICE_COMMUNICATION
          else MediaRecorder.AudioSource.MIC,
          SAMPLE_RATE,
          AudioFormat.CHANNEL_IN_MONO,
          AudioFormat.ENCODING_PCM_16BIT,
          // Generous over minimal: an over-sized buffer costs kilobytes; an
          // undersized one costs dropped frames under GC pauses.
          maxOf(minBuffer * 2, FRAME_SAMPLES * 2 * 8),
        )
      } catch (cause: SecurityException) {
        // The screen asks for the permission before minting the room (#20);
        // reaching here without it is a caller bug, reported as such.
        promise.reject(CodedException("ERR_MIC_PERMISSION", "microphone permission missing", cause))
        return@AsyncFunction
      }

      if (record.state != AudioRecord.STATE_INITIALIZED) {
        record.release()
        promise.reject(CodedException("ERR_CAPTURE", "recorder failed to initialise", null))
        return@AsyncFunction
      }

      recorder = record
      capturing.set(true)
      record.startRecording()

      captureThread = Thread({
        val frame = ByteArray(FRAME_SAMPLES * 2)
        while (capturing.get()) {
          // READ_BLOCKING fills the whole frame or reports why it could not,
          // which keeps every emitted frame the same 20 ms the uplink sizes
          // its sends around.
          val read = record.read(frame, 0, frame.size, AudioRecord.READ_BLOCKING)
          if (read <= 0) {
            continue
          }
          val exact = if (read == frame.size) frame else frame.copyOf(read)
          sendEvent(
            "frame",
            mapOf(
              "base64" to Base64.encodeToString(exact, Base64.NO_WRAP),
              // What the stream actually runs at, not what was asked for —
              // the uplink's rate check is only worth having if this is
              // the truth (#18 measured them equal on hardware; keep the
              // honesty anyway).
              "sampleRate" to record.sampleRate,
            ),
          )
        }
      }, "room-audio-capture")
      captureThread?.start()

      promise.resolve(null)
    }

    Function("stopCapture") {
      capturing.set(false)
      captureThread?.join(500)
      captureThread = null
      recorder?.let {
        runCatching { it.stop() }
        it.release()
      }
      recorder = null
    }

    AsyncFunction("startPlayback") { communication: Boolean, promise: Promise ->
      if (playing.get()) {
        promise.resolve(null)
        return@AsyncFunction
      }

      val minBuffer = AudioTrack.getMinBufferSize(
        SAMPLE_RATE,
        AudioFormat.CHANNEL_OUT_MONO,
        AudioFormat.ENCODING_PCM_16BIT,
      )

      val out = AudioTrack.Builder()
        .setAudioAttributes(
          AudioAttributes.Builder()
            // The other half of the AEC pair: voice-communication usage is
            // what names the far-end reference for the canceller. The
            // debrief's coach voice declares MEDIA instead — outside
            // communication mode a voice-communication stream routes to the
            // earpiece (#26's finding), and a coach nobody can hear is worse
            // than a coach without a canceller it does not need.
            .setUsage(
              if (communication) AudioAttributes.USAGE_VOICE_COMMUNICATION
              else AudioAttributes.USAGE_MEDIA
            )
            .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
            .build(),
        )
        .setAudioFormat(
          AudioFormat.Builder()
            .setSampleRate(SAMPLE_RATE)
            .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
            .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
            .build(),
        )
        .setBufferSizeInBytes(maxOf(minBuffer, FRAME_SAMPLES * 2 * 16))
        .setTransferMode(AudioTrack.MODE_STREAM)
        .build()

      if (out.state != AudioTrack.STATE_INITIALIZED) {
        out.release()
        promise.reject(CodedException("ERR_PLAYBACK", "output stream failed to initialise", null))
        return@AsyncFunction
      }

      track = out
      playing.set(true)
      out.play()

      playThread = Thread({
        var written = 0L
        while (playing.get()) {
          val chunk = try {
            queue.take()
          } catch (interrupted: InterruptedException) {
            break
          }
          if (discarding.get()) {
            // Part of an interrupted line, taken from the queue after the
            // flush. Dropping it here is what "discard buffered audio
            // immediately" means for a chunk the writer already held.
            if (queue.isEmpty()) discarding.set(false)
            continue
          }

          val wrote = out.write(chunk, 0, chunk.size, AudioTrack.WRITE_BLOCKING)
          if (wrote > 0) written += wrote / 2

          val drained = queue.isEmpty()
          if (drained) {
            // `played` with `drained` means the loudspeaker has actually gone
            // quiet, not that the last buffer was handed to the device — the
            // distinction `playback.ts` documents at its `onDrained`. Wait for
            // the head to reach what was written, bounded so a device that
            // never reports cannot hang the thread.
            val deadline = System.currentTimeMillis() + 2000
            while (
              playing.get() &&
              out.playbackHeadPosition < written &&
              System.currentTimeMillis() < deadline
            ) {
              Thread.sleep(10)
            }
          }
          if (!discarding.get()) {
            sendEvent("played", mapOf("drained" to (drained && queue.isEmpty())))
          }
        }
      }, "room-audio-playback")
      playThread?.start()

      promise.resolve(null)
    }

    Function("enqueue") { base64: String ->
      queue.put(Base64.decode(base64, Base64.NO_WRAP))
    }

    Function("discard") {
      // Order matters: mark first, so the writer refuses whatever it is
      // holding; clear the queue; then flush what the device has buffered.
      // `pause` before `flush` because flush is documented as a no-op on a
      // playing track.
      discarding.set(true)
      queue.clear()
      track?.let {
        runCatching {
          it.pause()
          it.flush()
          it.play()
        }
      }
      discarding.set(false)
    }

    Function("stopPlayback") {
      playing.set(false)
      playThread?.interrupt()
      playThread?.join(500)
      playThread = null
      queue.clear()
      track?.let {
        runCatching {
          it.pause()
          it.flush()
          it.stop()
        }
        it.release()
      }
      track = null
    }

    OnDestroy {
      capturing.set(false)
      playing.set(false)
      captureThread?.interrupt()
      playThread?.interrupt()
      recorder?.release()
      track?.release()
    }
  }
}
