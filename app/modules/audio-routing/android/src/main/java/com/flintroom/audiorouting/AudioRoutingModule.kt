package com.flintroom.audiorouting

import android.content.Context
import android.media.AudioDeviceInfo
import android.media.AudioManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import expo.modules.kotlin.Promise
import expo.modules.kotlin.exception.Exceptions
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition
import java.util.concurrent.Executor
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Speakerphone, for the duration of a session.
 *
 * `app/patches/` makes the player declare `Usage::VoiceCommunication`, which is
 * what gives Android's echo canceller a reference signal to subtract. What it
 * also does, in `MODE_NORMAL`, is route that stream to the **earpiece** — the
 * slit at the top of the handset. With the phone flat on a desk that points at
 * the ceiling, and a measurement taken that way flatters the canceller by
 * simply not using the loud speaker. See `docs/echo-cancellation.md`.
 *
 * Communication mode is what a speakerphone call is, and it is the state
 * Android's AEC is most thoroughly tuned for. Setting it is the app's job:
 * `react-native-audio-api` has no API for output routing on Android at all.
 */
class AudioRoutingModule : Module() {
  private val context: Context
    get() = appContext.reactContext ?: throw Exceptions.ReactContextLost()

  private val audioManager: AudioManager
    get() = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager

  private val mainHandler = Handler(Looper.getMainLooper())
  private val mainExecutor = Executor { mainHandler.post(it) }

  /**
   * The mode in force before we touched it.
   *
   * Restored rather than assumed to be `MODE_NORMAL`, because the app is not
   * the only thing on the device with an opinion — an incoming call leaves the
   * system in a mode of its own, and stamping `MODE_NORMAL` over that would be
   * this module breaking somebody else's audio to tidy up after itself.
   */
  private var previousMode: Int? = null

  override fun definition() = ModuleDefinition {
    Name("AudioRouting")

    /**
     * Resolves once routing has *actually* moved, not once it has been asked to.
     *
     * This is asynchronous for a measured reason. Changing the communication
     * device reroutes the whole audio path, and any stream already open gets
     * taken with it: opening the recorder immediately after produced, in
     * logcat, `AAUDIO_SERVICE_EVENT_DISCONNECTED` 336 ms later and
     * `stopCallback_l() INVALID_HANDLE, stream was probably stolen`. Oboe
     * reopened the stream against the new device but the library never
     * re-registered its callback, so the recorder delivered **zero buffers**
     * and the spike reported a pass on no data.
     *
     * A fixed sleep would paper over that, at whatever length happened to work
     * on this handset. The platform publishes the event; waiting for it is both
     * shorter and correct.
     */
    AsyncFunction("enterHandsFree") { promise: Promise ->
      val manager = audioManager

      // Recorded only on the first entry. A second call without an intervening
      // exit would otherwise save MODE_IN_COMMUNICATION as the thing to restore
      // and strand the device in it forever.
      if (previousMode == null) {
        previousMode = manager.mode
      }
      manager.mode = AudioManager.MODE_IN_COMMUNICATION

      if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) {
        @Suppress("DEPRECATION")
        manager.isSpeakerphoneOn = true
        // No event to wait for on this path, and no way to ask. Callers below
        // API 31 get the old best-effort behaviour.
        promise.resolve(false)
        return@AsyncFunction
      }

      val speaker = manager.availableCommunicationDevices.firstOrNull {
        it.type == AudioDeviceInfo.TYPE_BUILTIN_SPEAKER
      }
      if (speaker == null) {
        // Nothing to route to. Resolving rather than rejecting: audio still
        // plays, and failing a session over a routing preference is the wrong
        // trade. The caller learns it did not settle.
        promise.resolve(false)
        return@AsyncFunction
      }

      if (manager.communicationDevice?.type == AudioDeviceInfo.TYPE_BUILTIN_SPEAKER) {
        // Already there; no event will fire, so waiting for one would hang
        // until the timeout.
        promise.resolve(true)
        return@AsyncFunction
      }

      // Guards every exit below. The listener and the timeout race by design,
      // and a Promise resolved twice is a crash.
      val settled = AtomicBoolean(false)
      var listener: AudioManager.OnCommunicationDeviceChangedListener? = null

      val finish = { routed: Boolean ->
        if (settled.compareAndSet(false, true)) {
          listener?.let { manager.removeOnCommunicationDeviceChangedListener(it) }
          promise.resolve(routed)
        }
      }

      listener = AudioManager.OnCommunicationDeviceChangedListener { device ->
        if (device?.type == AudioDeviceInfo.TYPE_BUILTIN_SPEAKER) {
          finish(true)
        }
      }

      // Registered before the request, so a route that settles quickly cannot
      // land in the gap between asking and listening.
      manager.addOnCommunicationDeviceChangedListener(mainExecutor, listener)

      if (!manager.setCommunicationDevice(speaker)) {
        finish(false)
        return@AsyncFunction
      }

      // The platform makes no promise about how long rerouting takes, and a
      // caller left awaiting forever is worse than one told it did not settle.
      mainHandler.postDelayed({ finish(false) }, ROUTING_TIMEOUT_MS)
    }

    Function("leaveHandsFree") {
      val manager = audioManager

      if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
        manager.clearCommunicationDevice()
      } else {
        @Suppress("DEPRECATION")
        manager.isSpeakerphoneOn = false
      }

      // Null when we never entered. Leaving the mode alone in that case is the
      // point: this path runs from error handlers and unmount, where "undo what
      // we did" must not become "impose a default we never established".
      previousMode?.let { manager.mode = it }
      previousMode = null
    }
  }

  companion object {
    /** Generous. Observed settling was ~340 ms on an S24+. */
    private const val ROUTING_TIMEOUT_MS = 2000L
  }
}
