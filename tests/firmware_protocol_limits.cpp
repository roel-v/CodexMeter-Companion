#include "companion_protocol.h"
#include <cassert>
#include <cstring>
#include <string>
#include <cstdio>
using namespace companion;
static int effects = 0;
static DisplayState state() { return {}; }
static const char* apply(const char*, const char*) { ++effects; return nullptr; }
static void fenced(Endpoint, Endpoint, bool) {}
static constexpr auto boot = "0011223344556677";
static constexpr auto host = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
static constexpr auto token = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
int main() {
    Protocol p; p.init(boot, {state, apply, fenced}); p.identity(Endpoint::Usb);
    assert(!p.session.claim(Endpoint::Usb, host, token, 100));
    const std::string header = std::string("CM1 DATA ") + boot + " " + token + " 1 - ";
    std::string payload = "{}"; payload.resize(payload_limit, ' ');
    auto dispatch = [&](const std::string& frame) {
        return std::string(p.dispatch(Endpoint::Usb, frame.data(), frame.size(), 101));
    };
    assert(dispatch(header + payload).find("\"ok\":true") != std::string::npos);
    assert(effects == 1);
    // Duplicate transaction resolves without a second application.
    assert(dispatch(header + payload).find("\"ok\":true") != std::string::npos);
    assert(effects == 1);
    assert(dispatch(header + payload + " ").empty());
    assert(effects == 1);
    auto invalid = header + std::string("{\"x\":\"") + char(0xff) + "\"}";
    assert(dispatch(invalid).empty());
    assert(dispatch("CM1 DATA truncated").empty());
    std::string ping = std::string("CM1 {\"op\":\"ping\",\"q\":1,\"boot\":\"") + boot +
        "\",\"token\":\"" + token + "\"}";
    ping.resize(frame_limit, ' ');
    assert(!dispatch(ping).empty());
    assert(dispatch(ping + " ").empty());
    assert(effects == 1);
    printf("Parser boundary tests passed (frame=%zu payload=%zu)\n", frame_limit, payload_limit);
}
