import Foundation
import Network

/// One WiZ bulb, controlled over UDP port 38899 with JSON messages — the same
/// open local protocol pywizlight (and thunderstorm.py) uses. No cloud, no
/// HomeKit; the phone just needs to be on the same Wi-Fi as the bulbs.
final class WiZBulb: Identifiable, @unchecked Sendable {
    let ip: String
    var id: String { ip }

    /// UDP over busy 2.4 GHz Wi-Fi drops packets, and every lost setPilot is
    /// a bulb silently skipping part of the show. pywizlight covers this by
    /// retransmitting each message until the bulb acks it; we approximate
    /// that with blind resends at these delays — cancelled the moment a newer
    /// message goes out, so a resent flash can never overwrite the ambient
    /// state that follows it.
    private static let resendDelays: [TimeInterval] = [0.03, 0.07]

    private let queue = DispatchQueue(label: "wiz.bulb")
    private var connection: NWConnection?
    /// Bumped on every send; pending resends fire only if still current.
    /// Only touched on `queue`.
    private var sendGeneration = 0
    /// The reply handler for the in-flight request(), if any. Returns true
    /// when the datagram satisfied it. Only touched on `queue`.
    private var pendingReply: (([String: Any]) -> Bool)?
    private var pendingToken: UUID?
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
        receivePump(on: c)
        return c
    }

    /// Continuously drains the connection's inbound datagrams: acks from
    /// fire-and-forget sends are discarded, and the reply an in-flight
    /// request() is waiting for is handed to it. Without a pump, a timed-out
    /// request's leftover receive handler could swallow the next reply.
    private func receivePump(on c: NWConnection) {
        c.receiveMessage { [weak self] content, _, _, error in
            guard let self, self.connection === c, error == nil else { return }
            if let content,
               let reply = (try? JSONSerialization.jsonObject(with: content))
                   as? [String: Any],
               let handler = self.pendingReply, handler(reply) {
                self.pendingReply = nil
                self.pendingToken = nil
            }
            self.receivePump(on: c)
        }
    }

    func close() {
        connection?.cancel()
        connection = nil
    }

    /// Fire-and-forget send of one JSON message (flash timing must never
    /// block on the network), with loss-covering resends that self-cancel
    /// as soon as a newer message supersedes them.
    func send(_ message: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: message) else { return }
        let c = conn()
        queue.async {
            self.sendGeneration += 1
            let generation = self.sendGeneration
            c.send(content: data, completion: .contentProcessed { _ in })
            for delay in Self.resendDelays {
                self.queue.asyncAfter(deadline: .now() + delay) {
                    guard self.sendGeneration == generation else { return }
                    c.send(content: data, completion: .contentProcessed { _ in })
                }
            }
        }
    }

    /// Send one JSON message and wait (briefly) for the bulb's reply — the
    /// receive pump routes only a reply matching this request's method here,
    /// so queued acks from fire-and-forget sends can't satisfy it.
    func request(_ message: [String: Any], timeout: TimeInterval = 1.0) async -> [String: Any]? {
        guard let data = try? JSONSerialization.data(withJSONObject: message) else { return nil }
        let method = message["method"] as? String
        let c = conn()
        return await withCheckedContinuation { continuation in
            let once = ResumeOnce(continuation)
            let token = UUID()
            queue.async {
                self.sendGeneration += 1  // cancel pending resends; keep order
                self.pendingToken = token
                self.pendingReply = { reply in
                    guard method == nil || (reply["method"] as? String) == method else {
                        return false      // an ack for an earlier send: keep waiting
                    }
                    once.resume(reply)
                    return true
                }
                c.send(content: data, completion: .contentProcessed { _ in })
                self.queue.asyncAfter(deadline: .now() + timeout) {
                    if self.pendingToken == token {  // still ours: give up cleanly
                        self.pendingReply = nil
                        self.pendingToken = nil
                    }
                    once.resume(nil)
                }
            }
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
                         "dimming": dimming, "state": true]])
    }

    func turnOff() {
        send(["id": 1, "method": "setPilot", "params": ["state": false]])
    }

    /// A tiny fire-and-forget getPilot that keeps the phone's Wi-Fi radio out
    /// of power-save during a storm — an idle radio adds 100-300ms of wake
    /// latency, landing right in the middle of the flash choreography.
    /// Bypasses the resend machinery so it can't cancel a real message's
    /// resends; the reply is drained by the receive pump.
    func nudge() {
        guard let data = try? JSONSerialization.data(withJSONObject:
            ["id": 1, "method": "getPilot", "params": [String: Any]()]) else { return }
        conn().send(content: data, completion: .contentProcessed { _ in })
    }

    /// Capture the bulb's current state so restore() can put it back.
    func snapshot() async {
        snapshotResult = nil
        for _ in 0..<3 {  // retries: a lost snapshot means a warm-glow restore
            let reply = await request(["id": 1, "method": "getPilot",
                                       "params": [String: Any]()])
            if let result = reply?["result"] as? [String: Any], result["state"] != nil {
                snapshotResult = result
                return
            }
        }
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
        params["state"] = true
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
