import Foundation
import Network

/// One WiZ bulb, controlled over UDP port 38899 with JSON messages — the same
/// open local protocol pywizlight (and thunderstorm.py) uses. No cloud, no
/// HomeKit; the phone just needs to be on the same Wi-Fi as the bulbs.
final class WiZBulb: Identifiable, @unchecked Sendable {
    let ip: String
    var id: String { ip }

    private let queue = DispatchQueue(label: "wiz.bulb")
    private var connection: NWConnection?
    /// The bulb's `getPilot` result from before the storm, for restore().
    private var snapshotResult: [String: Any]?

    init(ip: String) {
        self.ip = ip
    }

    // MARK: transport

    private func conn() -> NWConnection {
        if let c = connection, c.state != .cancelled, c.state != .failed(.posix(.ENOTCONN)) {
            return c
        }
        let c = NWConnection(host: NWEndpoint.Host(ip),
                             port: NWEndpoint.Port(rawValue: 38899)!,
                             using: .udp)
        c.start(queue: queue)
        connection = c
        return c
    }

    func close() {
        connection?.cancel()
        connection = nil
    }

    /// Fire-and-forget send of one JSON message (flash timing must never
    /// block on the network).
    func send(_ message: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: message) else { return }
        conn().send(content: data, completion: .contentProcessed { _ in })
    }

    /// Send one JSON message and wait (briefly) for the bulb's reply.
    func request(_ message: [String: Any], timeout: TimeInterval = 1.0) async -> [String: Any]? {
        guard let data = try? JSONSerialization.data(withJSONObject: message) else { return nil }
        let c = conn()
        return await withCheckedContinuation { continuation in
            let once = ResumeOnce(continuation)
            c.send(content: data, completion: .contentProcessed { _ in
                c.receiveMessage { content, _, _, _ in
                    let reply = content.flatMap {
                        (try? JSONSerialization.jsonObject(with: $0)) as? [String: Any]
                    }
                    once.resume(reply)
                }
            })
            queue.asyncAfter(deadline: .now() + timeout) { once.resume(nil) }
        }
    }

    // MARK: bulb operations (mirroring thunderstorm.py's RealBulb)

    /// brightness is 0-255 like the Python scripts; WiZ wants "dimming" 1-100.
    /// The color is split into RGB + white-LED channels exactly the way
    /// pywizlight does, so both versions light the same diodes the same way.
    func setState(rgb: (Int, Int, Int), brightness: Int) {
        let dimming = max(1, min(100, Int((Double(brightness) / 255.0 * 100).rounded())))
        let (out, cw) = RGBCW.convert(rgb)
        send(["id": 1, "method": "setPilot",
              "params": ["r": out.0, "g": out.1, "b": out.2, "w": cw,
                         "dimming": dimming]])
    }

    func turnOff() {
        send(["id": 1, "method": "setPilot", "params": ["state": false]])
    }

    /// Capture the bulb's current state so restore() can put it back.
    func snapshot() async {
        let reply = await request(["id": 1, "method": "getPilot", "params": [String: Any]()])
        snapshotResult = reply?["result"] as? [String: Any]
    }

    /// Put the bulb back to its snapshotted state; fall back to a warm glow
    /// if the snapshot failed or the state can't be rebuilt.
    func restore() async {
        let warmGlow = { self.setState(rgb: (255, 180, 90), brightness: 120) }
        guard let s = snapshotResult else { warmGlow(); return }
        if (s["state"] as? Bool) == false {
            turnOff()
            return
        }
        var params: [String: Any] = [:]
        if let dimming = s["dimming"] { params["dimming"] = dimming }
        if let scene = s["sceneId"] as? Int, scene > 0 {
            params["sceneId"] = scene
        } else if let r = s["r"], let g = s["g"], let b = s["b"] {
            // getPilot reports wire-space values, so they go back verbatim —
            // including the white channels ("w"/"c"), without which a color
            // like pywizlight-white (r=g=b=0, w=128) would restore to darkness.
            params["r"] = r
            params["g"] = g
            params["b"] = b
            if let w = s["w"] { params["w"] = w }
            if let c = s["c"] { params["c"] = c }
        } else if let temp = s["temp"] {
            params["temp"] = temp
        } else if s["w"] != nil || s["c"] != nil {
            if let w = s["w"] { params["w"] = w }
            if let c = s["c"] { params["c"] = c }
        }
        guard !params.isEmpty else { warmGlow(); return }
        send(["id": 1, "method": "setPilot", "params": params])
    }
}

/// Guards a CheckedContinuation so racing reply/timeout paths resume it once.
private final class ResumeOnce: @unchecked Sendable {
    private var continuation: CheckedContinuation<[String: Any]?, Never>?
    private let lock = NSLock()

    init(_ continuation: CheckedContinuation<[String: Any]?, Never>) {
        self.continuation = continuation
    }

    func resume(_ value: [String: Any]?) {
        lock.lock()
        let c = continuation
        continuation = nil
        lock.unlock()
        c?.resume(returning: value)
    }
}
