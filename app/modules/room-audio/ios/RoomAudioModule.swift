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

 UNMEASURED ON HARDWARE. `docs/echo-cancellation.md` is explicit that the
 simulator routes audio through the host Mac and cannot answer an acoustic
 question, and there is no iPhone on the project yet. This file is written to
 the same contract the Android half measures against; #99 is where it gets
 its numbers. Nothing here may ship to an iPhone before that.
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

    Events("frame", "played")

    AsyncFunction("startCapture") { (promise: Promise) in
      self.state.async {
        do {
          try self.configureSession()
          try self.beginCapture()
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

    AsyncFunction("startPlayback") { (promise: Promise) in
      self.state.async {
        do {
          try self.configureSession()
          try self.beginPlayback()
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

  private func configureSession() throws {
    let session = AVAudioSession.sharedInstance()
    // `.voiceChat` engages Apple's voice-processing I/O; `.defaultToSpeaker`
    // is the hands-free premise — a phone flat on a desk, not held to an ear.
    try session.setCategory(
      .playAndRecord,
      mode: .voiceChat,
      options: [.defaultToSpeaker, .allowBluetoothHFP]
    )
    try session.setActive(true)
  }

  // ── Capture ────────────────────────────────────────────

  private func beginCapture() throws {
    guard !capturing else { return }

    let input = engine.inputNode
    // Apple's echo cancellation. The engine-level equivalent of Android's
    // VOICE_COMMUNICATION pair, and the reason this module exists on iOS.
    try input.setVoiceProcessingEnabled(true)

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

    try startEngine()
    capturing = true
  }

  // ── Playback ───────────────────────────────────────────

  private func beginPlayback() throws {
    guard !playing else { return }

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
