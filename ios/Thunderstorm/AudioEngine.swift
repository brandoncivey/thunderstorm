import AVFoundation

/// Plays the rain bed and thunder claps with AVAudioEngine.
///
/// Simpler than the desktop scripts on two counts: the rain buffer loops
/// gaplessly (no crossfade clips needed), and fades are live volume ramps on
/// the player node (no pre-rendered rain_fadein/rain_fade WAVs). The claps
/// are the same thunder_1-4.wav files, bundled as app resources.
final class AudioEngine: @unchecked Sendable {
    /// Rain bed level relative to the master volume (RAIN_VOLUME in the Python).
    static let rainLevel: Double = 0.25
    /// Swell overlay level relative to the master volume (SWELL_LEVEL).
    static let swellLevel: Double = 0.45
    static let fadeSeconds: Double = 4.0

    private let engine = AVAudioEngine()
    private let rainPlayer = AVAudioPlayerNode()
    private let swellPlayer = AVAudioPlayerNode()
    private var rainBuffer: AVAudioPCMBuffer?
    private var swellBuffer: AVAudioPCMBuffer?
    private var clapBuffers: [AVAudioPCMBuffer] = []
    private var clapPlayers: [AVAudioPlayerNode] = []

    init() {
        // .playback + the "audio" background mode keeps the app (and with it
        // the whole storm) running while the phone is locked. .mixWithOthers
        // blends our audio with whatever else is playing (Spotify, etc.)
        // instead of interrupting it — matching how macOS behaves.
        try? AVAudioSession.sharedInstance().setCategory(
            .playback, mode: .default, options: [.mixWithOthers])

        rainBuffer = Self.loadBuffer(named: "rain")
        clapBuffers = (1...4).compactMap { Self.loadBuffer(named: "thunder_\($0)") }

        if let rain = rainBuffer {
            engine.attach(rainPlayer)
            engine.connect(rainPlayer, to: engine.mainMixerNode, format: rain.format)
        }
        swellBuffer = Self.loadBuffer(named: "rain_swell")
        if let swell = swellBuffer {
            engine.attach(swellPlayer)
            engine.connect(swellPlayer, to: engine.mainMixerNode, format: swell.format)
        }
        // One player per clap file: different claps overlap freely; repeats of
        // the same clap queue behind each other, which real storms survive.
        for buffer in clapBuffers {
            let player = AVAudioPlayerNode()
            engine.attach(player)
            engine.connect(player, to: engine.mainMixerNode, format: buffer.format)
            clapPlayers.append(player)
        }
    }

    private static func loadBuffer(named name: String) -> AVAudioPCMBuffer? {
        guard let url = Bundle.main.url(forResource: name, withExtension: "wav"),
              let file = try? AVAudioFile(forReading: url),
              let buffer = AVAudioPCMBuffer(pcmFormat: file.processingFormat,
                                            frameCapacity: AVAudioFrameCount(file.length))
        else { return nil }
        do {
            try file.read(into: buffer)
        } catch {
            return nil
        }
        return buffer
    }

    private func ensureRunning() {
        guard !engine.isRunning else { return }
        try? AVAudioSession.sharedInstance().setActive(true)
        try? engine.start()
    }

    // MARK: rain

    func startRain(volume: Double) async {
        guard let buffer = rainBuffer else { return }
        ensureRunning()
        rainPlayer.volume = 0
        // The completion-handler overload: in an async function the plain call
        // resolves to the awaitable variant, which blocks until playback ends.
        rainPlayer.scheduleBuffer(buffer, at: nil, options: .loops, completionHandler: nil)
        rainPlayer.play()
        await ramp(rainPlayer, to: Float(volume * Self.rainLevel), over: Self.fadeSeconds)
    }

    func stopRain() async {
        guard rainPlayer.isPlaying else { return }
        await ramp(rainPlayer, to: 0, over: Self.fadeSeconds)
        rainPlayer.stop()
    }

    /// A passing squall layered over the bed (rain_swell.wav rises and falls
    /// on its own, so this is a one-shot play, not a ramp).
    func playSwell(volume: Double) {
        guard let buffer = swellBuffer else { return }
        ensureRunning()
        swellPlayer.volume = Float(volume * Self.swellLevel)
        swellPlayer.scheduleBuffer(buffer, at: nil, completionHandler: nil)
        swellPlayer.play()
    }

    // MARK: thunder

    /// distance 0.0 = overhead, 1.0 = far away: picks which clap plays.
    /// The caller has already applied the delay and distance loudness.
    func playClap(distance: Double, volume: Double) {
        guard !clapBuffers.isEmpty else { return }
        ensureRunning()
        let index = min(Int(distance * Double(clapBuffers.count)), clapBuffers.count - 1)
        let player = clapPlayers[index]
        player.volume = Float(volume)
        player.scheduleBuffer(clapBuffers[index], at: nil)
        player.play()
    }

    // MARK: helpers

    /// Linear volume ramp. Callers that run during teardown must not be in a
    /// cancelled task (Task.sleep would return immediately) — see StormEngine.
    private func ramp(_ node: AVAudioPlayerNode, to target: Float, over seconds: Double) async {
        let steps = 40
        let start = node.volume
        for step in 1...steps {
            node.volume = start + (target - start) * Float(step) / Float(steps)
            try? await Task.sleep(for: .seconds(seconds / Double(steps)))
        }
        node.volume = target
    }
}
