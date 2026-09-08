import SwiftUI

struct ContentView: View {
    @StateObject private var engine = StormEngine()

    @State private var bulbIPs: [String] = []
    @State private var scanning = false
    @State private var manualIP = ""

    @State private var mode: StormMode = .storm
    @State private var intensity: Intensity = .high
    @State private var durationMinutes = 2.0
    @State private var runUntilStopped = false
    @State private var volume = 1.0
    @State private var lights = true
    @State private var rain = true
    @State private var thunder = true
    // Party mode
    @State private var partyIntervalMinutes = 30.0
    @State private var partyHours = 3.0
    @State private var partyStormSeconds = 60.0
    // Rain mode extras
    @State private var swells = true
    @State private var occasionalStorms = false

    private var needsBulbs: Bool {
        switch mode {
        case .storm: return lights
        case .party: return true
        case .rain: return occasionalStorms
        }
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Picker("Mode", selection: $mode) {
                        ForEach(StormMode.allCases) { m in
                            Text(m.rawValue).tag(m)
                        }
                    }
                    .pickerStyle(.segmented)
                } footer: {
                    Text(modeBlurb)
                }
                bulbSection
                settingsSection
                controlSection
            }
            .navigationTitle("Thunderstorm")
            .scrollDismissesKeyboard(.interactively)
        }
    }

    private var modeBlurb: String {
        switch mode {
        case .storm:
            return "One storm: lightning on the bulbs with rain and thunder."
        case .party:
            return "A storm now, then another every interval, until the party "
                 + "times out — like storm_party.sh."
        case .rain:
            return "Continuous rain with passing squalls. Add lone distant "
                 + "thunder, or the occasional full storm on the bulbs."
        }
    }

    private var bulbSection: some View {
        Section("Bulbs") {
            if bulbIPs.isEmpty {
                Text(needsBulbs
                     ? "No bulbs yet — scan the network or add an IP."
                     : "No bulbs needed for this mode.")
                    .foregroundStyle(.secondary)
            }
            ForEach(bulbIPs, id: \.self) { ip in
                Label(ip, systemImage: "lightbulb")
            }
            .onDelete { bulbIPs.remove(atOffsets: $0) }

            HStack {
                TextField("Add by IP (e.g. 192.168.1.50)", text: $manualIP)
                    .keyboardType(.decimalPad)
                    .autocorrectionDisabled()
                Button("Add") {
                    let ip = manualIP.trimmingCharacters(in: .whitespaces)
                    if !ip.isEmpty, !bulbIPs.contains(ip) { bulbIPs.append(ip) }
                    manualIP = ""
                }
                .disabled(manualIP.trimmingCharacters(in: .whitespaces).isEmpty)
            }

            Button {
                scanning = true
                Task {
                    let found = await Discovery.sweep()
                    bulbIPs = Array(Set(bulbIPs).union(found)).sorted()
                    scanning = false
                }
            } label: {
                if scanning {
                    HStack { ProgressView(); Text("Scanning the network…") }
                } else {
                    Label("Scan for bulbs", systemImage: "magnifyingglass")
                }
            }
            .disabled(scanning)
        }
    }

    @ViewBuilder
    private var settingsSection: some View {
        switch mode {
        case .storm:
            Section("Storm") {
                intensityPicker
                Toggle("Run until stopped", isOn: $runUntilStopped)
                if !runUntilStopped { durationSlider }
                volumeSlider
                Toggle("Lightning (uses the bulbs)", isOn: $lights)
                Toggle("Rain", isOn: $rain)
                Toggle("Thunder", isOn: $thunder)
            }
        case .party:
            Section("Party") {
                intensityPicker
                VStack(alignment: .leading) {
                    Text("Each storm lasts \(Int(partyStormSeconds)) s")
                    Slider(value: $partyStormSeconds, in: 30...300, step: 15)
                }
                VStack(alignment: .leading) {
                    Text("A storm every \(Int(partyIntervalMinutes)) min")
                    Slider(value: $partyIntervalMinutes, in: 10...60, step: 5)
                }
                VStack(alignment: .leading) {
                    Text("Party ends after \(partyHours, specifier: "%.0f") h")
                    Slider(value: $partyHours, in: 1...6, step: 1)
                }
                volumeSlider
                Toggle("Rain", isOn: $rain)
                Toggle("Thunder", isOn: $thunder)
            }
        case .rain:
            Section("Rain") {
                Toggle("Run until stopped", isOn: $runUntilStopped)
                if !runUntilStopped { durationSlider }
                volumeSlider
                Toggle("Passing squalls", isOn: $swells)
                Toggle("Lone distant thunder", isOn: $thunder)
                Toggle("Occasional full storms (uses the bulbs)",
                       isOn: $occasionalStorms)
            }
        }
    }

    private var intensityPicker: some View {
        Picker("Intensity", selection: $intensity) {
            ForEach(Intensity.allCases) { level in
                Text(level.rawValue.capitalized).tag(level)
            }
        }
    }

    private var durationSlider: some View {
        VStack(alignment: .leading) {
            Text("Duration: \(Int(durationMinutes)) min")
            Slider(value: $durationMinutes,
                   in: mode == .rain ? 5...480 : 1...30,
                   step: mode == .rain ? 5 : 1)
        }
    }

    private var volumeSlider: some View {
        VStack(alignment: .leading) {
            Text("Volume: \(Int(volume * 100))%")
            Slider(value: $volume, in: 0...1)
        }
    }

    private var controlSection: some View {
        Section {
            if engine.isRunning {
                Button(role: .destructive) {
                    engine.stop()
                } label: {
                    Label("Stop", systemImage: "stop.fill")
                        .frame(maxWidth: .infinity)
                }
                if !engine.status.isEmpty {
                    Text(engine.status).foregroundStyle(.secondary)
                }
                if engine.strikeCount > 0 {
                    Label("\(engine.strikeCount) strikes", systemImage: "bolt.fill")
                        .foregroundStyle(.secondary)
                }
            } else {
                Button {
                    engine.start(bulbs: bulbIPs.map { WiZBulb(ip: $0) },
                                 options: currentOptions)
                } label: {
                    Label(startLabel, systemImage: startIcon)
                        .frame(maxWidth: .infinity)
                }
                .disabled(needsBulbs && bulbIPs.isEmpty)
            }
        } footer: {
            Text("The rain keeps the storm running while the phone is locked.")
        }
    }

    private var startLabel: String {
        switch mode {
        case .storm: return "Start storm"
        case .party: return "Start party"
        case .rain: return "Start rain"
        }
    }

    private var startIcon: String {
        switch mode {
        case .storm: return "cloud.bolt.rain.fill"
        case .party: return "party.popper.fill"
        case .rain: return "cloud.rain.fill"
        }
    }

    private var currentOptions: StormEngine.Options {
        var options = StormEngine.Options()
        options.mode = mode
        options.intensity = intensity
        options.duration = runUntilStopped ? 0 : durationMinutes * 60
        options.volume = volume
        options.lights = mode == .storm ? lights : true
        options.rain = rain
        options.thunder = thunder
        options.partyIntervalMinutes = partyIntervalMinutes
        options.partyHours = partyHours
        options.partyStormSeconds = partyStormSeconds
        options.swells = swells
        options.occasionalStorms = occasionalStorms
        return options
    }
}

#Preview {
    ContentView()
}
