import Foundation

/// Strike frequency presets — seconds between strikes, as in thunderstorm.py.
enum Intensity: String, CaseIterable, Identifiable {
    case low, medium, high
    var id: String { rawValue }

    var gap: ClosedRange<Double> {
        switch self {
        case .low: return 12.0...30.0
        case .medium: return 5.0...15.0
        case .high: return 1.5...6.0
        }
    }
}

enum StormMode: String, CaseIterable, Identifiable {
    case storm = "Storm"
    case party = "Party"
    case rain = "Rain"
    var id: String { rawValue }
}

/// The storm engine — a translation of thunderstorm.py's effect logic, plus
/// the storm_party.sh (interval + auto-expiry) and rain_ambience.py
/// (rain bed + swells + extras) behaviors as modes.
@MainActor
final class StormEngine: ObservableObject {
    // Tunables, mirroring the Python constants.
    static let ambientRGB = (10, 15, 40)
    static let ambientBrightness = 12
    static let flashRGB = (255, 255, 255)
    static let flashBrightness = 255
    static let swellGap: ClosedRange<Double> = 45...150       // rain_ambience.py SWELL_GAP
    static let loneClapGap: ClosedRange<Double> = 90...300    // THUNDER_GAP
    static let ambienceStormGap: ClosedRange<Double> = 600...1500  // STORM_GAP

    @Published private(set) var isRunning = false
    @Published private(set) var strikeCount = 0
    @Published private(set) var status = ""

    let audio = AudioEngine()
    private var mainTask: Task<Void, Never>?

    struct Options {
        var mode: StormMode = .storm
        var intensity: Intensity = .high
        var duration: TimeInterval = 120   // storm & rain modes; 0 = until stopped
        var volume: Double = 1.0
        var lights = true
        var rain = true
        var thunder = true
        // Party mode (storm_party.sh: a storm now, then every N min, for H hours)
        var partyIntervalMinutes: Double = 30
        var partyHours: Double = 3
        var partyStormSeconds: Double = 60
        // Rain mode extras (rain_ambience.py)
        var swells = true
        var occasionalStorms = false
    }

    func start(bulbs: [WiZBulb], options: Options) {
        guard mainTask == nil else { return }
        isRunning = true
        strikeCount = 0
        mainTask = Task {
            switch options.mode {
            case .storm: await runStormOnce(bulbs: bulbs, options: options)
            case .party: await runParty(bulbs: bulbs, options: options)
            case .rain: await runRain(bulbs: bulbs, options: options)
            }
            status = ""
            isRunning = false
            mainTask = nil
        }
    }

    func stop() {
        mainTask?.cancel()
    }

    // MARK: - One storm (the building block every mode uses)

    private func runStormOnce(bulbs: [WiZBulb], options: Options) async {
        // Snapshot every bulb so the room goes back to how it was.
        for bulb in bulbs { await bulb.snapshot() }
        if options.rain {
            await audio.startRain(volume: options.volume)
        }
        let end: Date? = options.duration > 0
            ? Date().addingTimeInterval(options.duration) : nil
        status = "Storm in progress"

        do {
            if options.lights { ambient(bulbs) }
            try await sleep(random: options.intensity.gap)
            while end == nil || Date() < end! {
                strikeCount += 1
                try await strike(bulbs: bulbs, options: options)
                try await sleep(random: options.intensity.gap)
            }
        } catch {
            // Cancelled (the Stop button) — fall through to cleanup.
        }

        // Cleanup must run even though this task may be cancelled, and
        // Task.sleep inside a cancelled task returns immediately — so the
        // rain fade-out runs in a fresh, uncancelled task (the same lesson
        // as the Python's shielded finally block).
        if options.rain {
            let audio = self.audio
            await Task.detached { await audio.stopRain() }.value
        }
        for bulb in bulbs { await bulb.restore() }
    }

    // MARK: - Party mode

    private func runParty(bulbs: [WiZBulb], options: Options) async {
        let expiry = Date().addingTimeInterval(options.partyHours * 3600)
        var storm = options
        storm.duration = options.partyStormSeconds
        do {
            while Date() < expiry {
                await runStormOnce(bulbs: bulbs, options: storm)
                try Task.checkCancellation()
                let wait = options.partyIntervalMinutes * 60
                // Don't start a wait that would outlive the party.
                if Date().addingTimeInterval(wait) >= expiry { break }
                status = "Next storm around "
                    + Self.timeFormatter.string(from: Date().addingTimeInterval(wait))
                try await Task.sleep(for: .seconds(wait))
            }
        } catch {
            // Cancelled during the idle wait; each storm cleans up after itself.
        }
    }

    private static let timeFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.timeStyle = .short
        formatter.dateStyle = .none
        return formatter
    }()

    // MARK: - Rain-ambience mode

    private func runRain(bulbs: [WiZBulb], options: Options) async {
        await audio.startRain(volume: options.volume)
        status = "Rain falling"
        do {
            try await withThrowingTaskGroup(of: Void.self) { group in
                if options.swells {
                    group.addTask { try await self.swellLoop(volume: options.volume) }
                }
                if options.thunder {
                    group.addTask { try await self.loneClapLoop(volume: options.volume) }
                }
                if options.occasionalStorms {
                    group.addTask {
                        try await self.stormEveryNowAndThen(bulbs: bulbs, options: options)
                    }
                }
                group.addTask {  // ends the group when the duration elapses
                    if options.duration > 0 {
                        try await Task.sleep(for: .seconds(options.duration))
                    } else {
                        while true { try await Task.sleep(for: .seconds(3600)) }
                    }
                }
                try await group.next()
                group.cancelAll()
            }
        } catch {
            // Cancelled — fall through to the fade-out.
        }
        let audio = self.audio
        await Task.detached { await audio.stopRain() }.value
    }

    private func swellLoop(volume: Double) async throws {
        while true {
            try await sleep(random: Self.swellGap)
            audio.playSwell(volume: volume)
        }
    }

    /// Occasional lone thunderclaps, weighted toward distant rumbles.
    private func loneClapLoop(volume: Double) async throws {
        while true {
            try await sleep(random: Self.loneClapGap)
            let distance = Double.random(in: 0.35...1.0)
            audio.playClap(distance: distance, volume: volume * (1.0 - 0.45 * distance))
        }
    }

    /// Now and then, a full lightning storm on top of the ambience. The storm
    /// skips its own rain so it blends with the bed that's already playing.
    private func stormEveryNowAndThen(bulbs: [WiZBulb], options: Options) async throws {
        while true {
            try await sleep(random: Self.ambienceStormGap)
            var storm = options
            storm.mode = .storm
            storm.rain = false
            storm.lights = true
            storm.duration = 60
            storm.intensity = .medium
            await runStormOnce(bulbs: bulbs, options: storm)
            try Task.checkCancellation()
            status = "Rain falling"
        }
    }

    // MARK: - The lightning itself

    private func strike(bulbs: [WiZBulb], options: Options) async throws {
        if options.thunder {
            scheduleThunder(volume: options.volume)
        }
        guard options.lights, !bulbs.isEmpty else { return }

        // The bolt lights one part of the room more than the rest: per-bulb
        // brightness factors, with at least one bulb at full.
        var factors = bulbs.map { _ in Double.random(in: 0.35...1.0) }
        factors[Int.random(in: 0..<bulbs.count)] = 1.0

        func flash(_ rgb: (Int, Int, Int), _ brightness: Int) {
            for (bulb, factor) in zip(bulbs, factors) {
                bulb.setState(rgb: rgb, brightness: max(1, Int(Double(brightness) * factor)))
            }
        }

        // Main flash.
        flash(Self.flashRGB, Self.flashBrightness)
        try await sleep(random: 0.04...0.12)

        // Flickering multi-strike (lightning rarely fires just once).
        for _ in 0..<Int.random(in: 0...3) {
            ambient(bulbs)
            try await sleep(random: 0.03...0.09)
            flash(Self.flashRGB, Int.random(in: 120...255))
            try await sleep(random: 0.03...0.10)
        }

        // Back to the stormy dark.
        ambient(bulbs)

        // Occasional faint, delayed afterflash (distant part of the bolt).
        if Double.random(in: 0..<1) < 0.4 {
            try await sleep(random: 0.15...0.5)
            flash((200, 210, 255), Int.random(in: 40...100))
            try await sleep(random: 0.05...0.12)
            ambient(bulbs)
        }
    }

    /// distance 0.0 = overhead, 1.0 = far away: picks the clap, how long
    /// after the flash it lands (sound lags light), and how loud it is.
    private func scheduleThunder(volume: Double) {
        let distance = Double.random(in: 0..<1)
        let delay = 0.05 + distance * 2.45
        let clapVolume = volume * (1.0 - 0.45 * distance)
        let audio = self.audio
        Task.detached {
            try? await Task.sleep(for: .seconds(delay))
            audio.playClap(distance: distance, volume: clapVolume)
        }
    }

    private func ambient(_ bulbs: [WiZBulb]) {
        for bulb in bulbs {
            bulb.setState(rgb: Self.ambientRGB, brightness: Self.ambientBrightness)
        }
    }

    private func sleep(random range: ClosedRange<Double>) async throws {
        try await Task.sleep(for: .seconds(Double.random(in: range)))
    }
}
