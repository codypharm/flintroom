import AVFoundation
import ExpoModulesCore

/**
 The owned audio layer's iOS half (#25).

 One `AVAudioEngine` with voice processing enabled on the input node — which
 is Apple's own echo cancellation, the `voiceChat`-mode machinery — so the
 acoustic property Android carries as a preset/usage pair is carried here by
 the engine itself. The audio session is configured in this file too
 (play-and-record, voice chat, defaulting to the loudspeaker), because after
 the swap nothing else in the app touches the session and a property this
 load-bearing should have exactly one owner.

 Measured on an iPhone 13 on 2026-10-02 (`docs/echo-cancellation.md`, "iOS,
 measured"): the canceller holds and a presenter talking over the panel is
 still heard. The same day's live rooms went silent twice over: voice
 processing switched on under a running engine (`ensureVoiceProcessing`), and
 iOS reconfiguring the engine as playback opened (`recover`). The simulator routes audio through the host
 Mac and still cannot answer an acoustic question.
 */
public class RoomAudioModule: Module {
  /// The wire's rate (`docs/voice-stream-protocol.md`). Both directions.
  private static let sampleRate = 16000.0

  /// 20 ms at the wire rate, matching the uplink's own frame.
  private static let frameSamples = 320

  private let engine = AVAudioEngine()
  private let player = AVAudioPlayerNode()

  /// Everything that touches engine state runs here, serially. Audio
  /// callbacks arrive on real-time threads and Expo functions on their own
  /// queue; a lock-free module is one that funnels instead.
  private let state = DispatchQueue(label: "room-audio.state")

  private var capturing = false
  private var playing = false

  private var configurationObserver: NSObjectProtocol?

  /// Chunks scheduled but not yet played back, for `drained` honesty:
  /// `played` with `drained: true` must mean the loudspeaker went quiet, not
  /// that the last buffer was handed over.
  private var scheduled = 0

  /// Bumped by discard. A completion handler holding an older generation is
  /// reporting a chunk that was thrown away, and stays silent — the same rule
  /// the TypeScript adapter applies from its side.
  private var generation = 0

  private var wireFormat: AVAudioFormat {
    AVAudioFormat(
      commonFormat: .pcmFormatInt16,
      sampleRate: Self.sampleRate,
      channels: 1,
      interleaved: true
    )!
  }

  private var playFormat: AVAudioFormat {
    AVAudioFormat(
      commonFormat: .pcmFormatFloat32,
      sampleRate: Self.sampleRate,
      channels: 1,
      interleaved: false
    )!
  }

  public func definition() -> ModuleDefinition {
    Name("RoomAudio")

    Events("frame", "played", "restarted")

    OnCreate { [weak self] in
      guard let self else { return }
      // iOS stops an engine whose configuration changes underneath it, and
      // says so only through this notification. Unobserved, that stop is a
      // room that goes deaf and mute at once with nothing raised anywhere.
      self.configurationObserver = NotificationCenter.default.addObserver(
        forName: .AVAudioEngineConfigurationChange,
        object: self.engine,
        queue: nil
      ) { [weak self] _ in
        self?.state.async { self?.recover() }
      }
    }

    AsyncFunction("startCapture") { (communication: Bool, promise: Promise) in
      self.state.async {
        do {
          try self.configureSession(communication: communication)
          try self.beginCapture(communication: communication)
          promise.resolve(nil)
        } catch {
          promise.reject("ERR_CAPTURE", error.localizedDescription)
        }
      }
    }

    Function("stopCapture") {
      self.state.async {
        guard self.capturing else { return }
        self.capturing = false
        self.engine.inputNode.removeTap(onBus: 0)
        self.stopEngineIfIdle()
      }
    }

    AsyncFunction("startPlayback") { (communication: Bool, promise: Promise) in
      self.state.async {
        do {
          try self.configureSession(communication: communication)
          try self.beginPlayback(communication: communication)
          promise.resolve(nil)
        } catch {
          promise.reject("ERR_PLAYBACK", error.localizedDescription)
        }
      }
    }

    Function("stopPlayback") {
      self.state.async {
        guard self.playing else { return }
        self.playing = false
        self.generation += 1
        self.scheduled = 0
        self.player.stop()
        self.stopEngineIfIdle()
      }
    }

    Function("enqueue") { (base64: String) in
      self.state.async {
        guard self.playing, let raw = Data(base64Encoded: base64) else { return }
        guard let buffer = self.floatBuffer(fromPcm16: raw) else { return }

        self.scheduled += 1
        let ticket = self.generation
        // `.dataPlayedBack` fires when the audio has actually left the
        // speaker, which is the only meaning of `drained` the room can use —
        // an empty schedule with sound still in the hardware is a panelist
        // released mid-sentence.
        self.player.scheduleBuffer(buffer, completionCallbackType: .dataPlayedBack) { _ in
          self.state.async {
            guard ticket == self.generation else { return }
            self.scheduled -= 1
            self.sendEvent("played", ["drained": self.scheduled == 0])
          }
        }
        if !self.player.isPlaying {
          self.player.play()
        }
      }
    }

    Function("discard") {
      self.state.async {
        // Barge-in. `stop()` clears every scheduled buffer immediately —
        // the "drop buffered audio now" the spec asks for — and the
        // generation bump silences the completion handlers of everything
        // just thrown away.
        self.generation += 1
        self.scheduled = 0
        self.player.stop()
        if self.playing {
          self.player.play()
        }
      }
    }

    OnDestroy {
      if let observer = self.configurationObserver {
        NotificationCenter.default.removeObserver(observer)
      }
      self.state.async {
        self.capturing = false
        self.playing = false
        self.engine.inputNode.removeTap(onBus: 0)
        self.player.stop()
        self.engine.stop()
      }
    }
  }

  // ── Session ────────────────────────────────────────────

  private func configureSession(communication: Bool) throws {
    let session = AVAudioSession.sharedInstance()
    // The live room runs as a call: `.voiceChat` engages Apple's
    // voice-processing I/O and `.defaultToSpeaker` is the hands-free
    // premise. The debrief runs plain — nothing plays while somebody
    // answers a coach, so call-tuned processing would only colour a solo
    // recording, the same refusal its Android half makes with MIC/MEDIA.
    //
    // **Only when it differs.** Both halves of the room call this, and the
    // second arrives while the first may already have the engine running.
    // Setting the category again under a running voice-processing engine is
    // a configuration change, and iOS answers one by stopping the engine:
    // the 2026-10-02 rooms that played nothing and heard nothing. Whether
    // the microphone's call landed before or after the speaker's depended on
    // how fast the opener arrived, which is why some rooms worked.
    let mode: AVAudioSession.Mode = communication ? .voiceChat : .default
    let options: AVAudioSession.CategoryOptions = [.defaultToSpeaker, .allowBluetoothHFP]
    if session.category != .playAndRecord || session.mode != mode
      || session.categoryOptions != options {
      try session.setCategory(.playAndRecord, mode: mode, options: options)
    }
    try session.setActive(true)
  }

  // ── Capture ────────────────────────────────────────────

  private func beginCapture(communication: Bool) throws {
    guard !capturing else { return }

    // Apple's echo cancellation, for the live room. The engine-level
    // equivalent of Android's VOICE_COMMUNICATION pair, and off for the
    // debrief's plain clips.
    try ensureVoiceProcessing(communication)
    try installTap()

    try startEngine()
    capturing = true
  }

  /// The microphone tap, at whatever format the input node has now.
  ///
  /// Its own function because `recover` needs it too: after a configuration
  /// change the input's format can differ, and a tap left at the old one is
  /// a capture that delivers nothing.
  private func installTap() throws {
    let input = engine.inputNode
    let native = input.outputFormat(forBus: 0)
    guard let converter = AVAudioConverter(from: native, to: wireFormat) else {
      throw NSError(
        domain: "RoomAudio", code: 1,
        userInfo: [NSLocalizedDescriptionKey: "no conversion path to 16 kHz mono"]
      )
    }

    var pending = Data()

    input.installTap(onBus: 0, bufferSize: 1024, format: native) { buffer, _ in
      // Downsample on the tap's own thread: the ratio is fixed, the work is
      // small, and hopping queues per buffer would cost more than it saves.
      let capacity = AVAudioFrameCount(
        Double(buffer.frameLength) * Self.sampleRate / native.sampleRate + 16
      )
      guard let out = AVAudioPCMBuffer(pcmFormat: self.wireFormat, frameCapacity: capacity) else {
        return
      }

      var fed = false
      var conversionError: NSError?
      converter.convert(to: out, error: &conversionError) { _, status in
        if fed {
          status.pointee = .noDataNow
          return nil
        }
        fed = true
        status.pointee = .haveData
        return buffer
      }
      guard conversionError == nil, out.frameLength > 0,
            let bytes = out.int16ChannelData else {
        return
      }

      pending.append(Data(
        bytes: bytes[0],
        count: Int(out.frameLength) * MemoryLayout<Int16>.size
      ))

      // Re-framed to the uplink's 20 ms, whatever size the tap delivered.
      let frameBytes = Self.frameSamples * MemoryLayout<Int16>.size
      while pending.count >= frameBytes {
        let frame = pending.prefix(frameBytes)
        pending.removeFirst(frameBytes)
        self.sendEvent("frame", [
          "base64": frame.base64EncodedString(),
          "sampleRate": Int(Self.sampleRate),
        ])
      }
    }

  }

  // ── Playback ───────────────────────────────────────────

  private func beginPlayback(communication: Bool) throws {
    guard !playing else { return }

    // Before the player is attached and before the engine starts. The live
    // room plays the opener the moment the socket opens and starts the
    // microphone a beat later, so playback is the side that starts the
    // engine. See `ensureVoiceProcessing` for what that order used to cost.
    if communication {
      try ensureVoiceProcessing(true)
    }

    if player.engine == nil {
      engine.attach(player)
      engine.connect(player, to: engine.mainMixerNode, format: playFormat)
    }

    try startEngine()
    playing = true
    player.play()
  }

  private func floatBuffer(fromPcm16 data: Data) -> AVAudioPCMBuffer? {
    let samples = data.count / MemoryLayout<Int16>.size
    guard samples > 0,
          let buffer = AVAudioPCMBuffer(
            pcmFormat: playFormat,
            frameCapacity: AVAudioFrameCount(samples)
          ),
          let channel = buffer.floatChannelData else {
      return nil
    }

    data.withUnsafeBytes { (raw: UnsafeRawBufferPointer) in
      let ints = raw.bindMemory(to: Int16.self)
      for i in 0..<samples {
        // The same scale as the TypeScript side: divide by 32768, so a
        // full-scale sample round-trips exactly.
        channel[0][i] = Float(Int16(littleEndian: ints[i])) / 32768.0
      }
    }
    buffer.frameLength = AVAudioFrameCount(samples)
    return buffer
  }

  // ── Engine ─────────────────────────────────────────────

  /// Voice processing, switched while the engine is stopped and never under it.
  ///
  /// **The first live room on an iPhone was silent (2026-10-02).** The opener
  /// arrived, the seat lit, and nothing came out of the speaker. Voice
  /// processing replaces the engine's I/O unit for *both* directions, and it
  /// was only ever switched on by `beginCapture`, which the live room reaches
  /// after playback has already started the engine. Switched on a running
  /// engine, the I/O is rebuilt under the player, and the panel plays into
  /// nothing. The Echo spike starts capture first, which is why it played
  /// out loud on the same phone and the room did not.
  ///
  /// So the engine is stopped around the switch whenever it is running, and
  /// the player resumed after. It is also what the echo canceller needs: the
  /// panel's audio has to leave through the voice-processing unit for the
  /// canceller to have it as a reference.
  private func ensureVoiceProcessing(_ enabled: Bool) throws {
    let input = engine.inputNode
    guard input.isVoiceProcessingEnabled != enabled else { return }

    let wasRunning = engine.isRunning
    if wasRunning {
      engine.stop()
    }
    try input.setVoiceProcessingEnabled(enabled)
    if wasRunning {
      try engine.start()
      if playing {
        player.play()
      }
    }
  }

  /// Bring the room back after iOS stopped the engine under it.
  ///
  /// Only if something is still meant to be running and the engine is not:
  /// `ensureVoiceProcessing` stops and restarts the engine itself, and the
  /// notification that produces arrives after it has already finished.
  ///
  /// Reported as `restarted`, with the error if the restart failed, because a
  /// recovery nobody can see is one nobody can tell from the bug it covers.
  private func recover() {
    guard capturing || playing, !engine.isRunning else { return }

    var failure = ""
    do {
      if playing {
        reconnectPlayer()
      }
      if capturing {
        engine.inputNode.removeTap(onBus: 0)
        try installTap()
      }
      engine.prepare()
      try engine.start()
      if playing {
        player.play()
      }
    } catch {
      failure = error.localizedDescription
    }
    sendEvent("restarted", [
      "capturing": capturing,
      "playing": playing,
      "error": failure,
    ])
  }

  /// The player, detached and wired in again on the engine's current formats.
  ///
  /// **Restarting was not enough.** The 2026-10-02 probe on an iPhone 13: iOS
  /// stopped the engine as playback opened, `recover` restarted it and called
  /// `play()`, and of 69 chunks of a panelist's voice enqueued afterwards,
  /// none was played. The microphone came back on the same restart, and the
  /// server heard the presenter. A configuration change can move the output's
  /// format, and a player left connected on the old one renders nothing and
  /// completes nothing, so it is rebuilt rather than resumed.
  ///
  /// Anything it had scheduled went with it. Those chunks are reported as
  /// played, in order, so the JavaScript queue that waits on them is not left
  /// holding a speaker who will never finish.
  private func reconnectPlayer() {
    let lost = scheduled
    generation += 1
    scheduled = 0
    player.stop()
    engine.detach(player)
    engine.attach(player)
    engine.connect(player, to: engine.mainMixerNode, format: playFormat)
    engine.connect(engine.mainMixerNode, to: engine.outputNode, format: nil)
    for chunk in 0..<lost {
      sendEvent("played", ["drained": chunk == lost - 1])
    }
  }

  private func startEngine() throws {
    if !engine.isRunning {
      try engine.start()
    }
  }

  private func stopEngineIfIdle() {
    if !capturing && !playing {
      engine.stop()
    }
  }
}
