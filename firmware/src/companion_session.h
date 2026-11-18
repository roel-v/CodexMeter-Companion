#pragma once
#include "serial_protocol.h"
namespace companion {
enum class Endpoint : uint8_t { None, Usb, Ble, LegacyBle, Maintenance };
bool preserve_maintenance_telemetry(Endpoint before, Endpoint after, bool same_host);
bool screen_policy_reason(const char* reason, bool legacy, bool on);
class Session {
 public:
  Endpoint owner = Endpoint::None;
  uint32_t epoch = 1;
  bool same_host = false;
  bool expire(uint32_t now);
  const char* claim(Endpoint endpoint, const char* host, const char* token, uint32_t now);
  const char* check(Endpoint endpoint, const char* token, uint32_t now);
  const char* release(Endpoint endpoint, const char* token, uint32_t now);
  void ping(uint32_t now) { touched_ = now; }
  void fence();
  void legacy(uint32_t now);
  bool live() const { return owner != Endpoint::None; }
  const char* busy() const;
  // nullptr means new sequence; "retry" returns the saved outcome.
  const char* sequence(uint32_t seq, const char* revision, const char* payload);
  void remember(uint32_t seq, const char* revision, const char* payload, const char* error);
  const char* outcome() const { return outcome_[0] ? outcome_ : nullptr; }
 private:
  char host_[33]{}, previous_host_[33]{}, token_[33]{}, released_[33]{};
  Endpoint released_endpoint_ = Endpoint::None;
  uint32_t touched_ = 0, seq_ = 0;
  char payload_[payload_limit + 1]{}, revision_[11]{}, outcome_[24]{};
};
// Deduplication outlives the host 60-second alert TTL by a 5-second margin.
constexpr uint32_t alert_dedup_ms = 65000;
constexpr size_t alert_ledger_capacity = 32;
class AlertLedger {
 public:
  // 0=new reserved entry, 1=duplicate, -1=full.
  int accept(const char* id, uint32_t now);
 private:
  struct Entry { char id[13]{}; uint32_t at = 0; } entries_[alert_ledger_capacity];
};
}
