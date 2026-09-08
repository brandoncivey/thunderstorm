import Foundation

/// Bulb discovery. pywizlight uses a UDP *broadcast*, but on iOS broadcast
/// needs Apple's multicast entitlement (an approval form). A subnet sweep —
/// unicast `getPilot` to every host on the Wi-Fi interface's subnet, keep
/// whoever answers — needs no entitlement and finds the same bulbs, just a
/// few seconds slower.
enum Discovery {
    /// The phone's IPv4 address and netmask on Wi-Fi (en0), host byte order.
    static func wifiIPv4() -> (ip: UInt32, netmask: UInt32)? {
        var ifaddrList: UnsafeMutablePointer<ifaddrs>?
        guard getifaddrs(&ifaddrList) == 0, let first = ifaddrList else { return nil }
        defer { freeifaddrs(ifaddrList) }
        for ptr in sequence(first: first, next: { $0.pointee.ifa_next }) {
            let ifa = ptr.pointee
            guard String(cString: ifa.ifa_name) == "en0",
                  let sa = ifa.ifa_addr,
                  sa.pointee.sa_family == UInt8(AF_INET),
                  let nm = ifa.ifa_netmask else { continue }
            let ip = UInt32(bigEndian: UnsafeRawPointer(sa)
                .assumingMemoryBound(to: sockaddr_in.self).pointee.sin_addr.s_addr)
            let mask = UInt32(bigEndian: UnsafeRawPointer(nm)
                .assumingMemoryBound(to: sockaddr_in.self).pointee.sin_addr.s_addr)
            return (ip, mask)
        }
        return nil
    }

    private static func dotted(_ ip: UInt32) -> String {
        "\((ip >> 24) & 255).\((ip >> 16) & 255).\((ip >> 8) & 255).\(ip & 255)"
    }

    /// One UDP probe can simply get lost (bulbs often sit on busy 2.4 GHz
    /// Wi-Fi), so each host gets several attempts before we give up on it.
    /// Each attempt uses a fresh connection: reusing one would leave a stale
    /// receive handler from the timed-out attempt to swallow the reply.
    private static func probe(_ ip: String, attempts: Int = 2) async -> Bool {
        for _ in 0..<attempts {
            let bulb = WiZBulb(ip: ip)
            let reply = await bulb.request(
                ["id": 1, "method": "getPilot", "params": [String: Any]()],
                timeout: 0.7)
            bulb.close()
            if reply?["result"] != nil { return true }
        }
        return false
    }

    /// Probe every host on the Wi-Fi interface's subnet; WiZ bulbs answer
    /// getPilot. The subnet comes from the real netmask — a mesh router often
    /// hands out a /23 or /22, and assuming /24 would hide the bulbs on the
    /// other slice of it. Capped at 1022 hosts (/22) so a degenerate netmask
    /// can't turn this into a sweep of a /16. Takes ~10-25s depending on
    /// subnet size: every non-bulb has to time out three times.
    static func sweep() async -> [String] {
        guard let (ownIP, netmask) = wifiIPv4() else { return [] }
        var mask = netmask
        if ~mask + 1 > 1024 { mask = 0xFFFF_FF00 }  // too big: our /24 slice only
        let network = ownIP & mask
        let broadcast = network | ~mask

        var found: [String] = []
        // Probes capped at 101 in flight at a time.
        await withTaskGroup(of: String?.self) { group in
            var inFlight = 0
            for host in (network + 1)...(broadcast - 1) where host != ownIP {
                let target = dotted(host)
                group.addTask {
                    await probe(target) ? target : nil
                }
                inFlight += 1
                if inFlight > 100 {
                    if let hit = await group.next(), let ip = hit { found.append(ip) }
                    inFlight -= 1
                }
            }
            for await hit in group {
                if let ip = hit { found.append(ip) }
            }
        }
        return found.sorted { lhs, rhs in
            let l = lhs.split(separator: ".").compactMap { UInt32($0) }
            let r = rhs.split(separator: ".").compactMap { UInt32($0) }
            return l.lexicographicallyPrecedes(r)
        }
    }
}
