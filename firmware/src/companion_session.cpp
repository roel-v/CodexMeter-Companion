#include "companion_session.h"
#include <string.h>
namespace companion {
bool preserve_maintenance_telemetry(Endpoint before, Endpoint after, bool same_host) {
  return same_host && after == Endpoint::Maintenance &&
         (before == Endpoint::Usb || before == Endpoint::Ble);
}
bool screen_policy_reason(const char* reason,bool legacy,bool on) {
  if(!reason)return false;
  if(!strcmp(reason,"lock") || !strcmp(reason,"unlock"))return true;
  return legacy && (!strcmp(reason,"mac_locked") || !strcmp(reason,"mac_unlocked") ||
                    (on && !strcmp(reason,"ble_restored")));
}
void Session::fence() {
  owner = Endpoint::None; token_[0] = 0; seq_ = 0; ++epoch;
}
bool Session::expire(uint32_t now) {
  if (owner != Endpoint::None && owner != Endpoint::LegacyBle &&
      uint32_t(now - touched_) >= (owner == Endpoint::Maintenance ? 120000u : 7000u)) {
    fence(); return true;
  }
  return false;
}
const char* Session::busy() const {
  return owner == Endpoint::Maintenance ? "busy_maintenance" :
         owner == Endpoint::Usb ? "busy_usb" : "busy_ble";
}
const char* Session::check(Endpoint endpoint, const char* token, uint32_t now) {
  expire(now);
  if (owner != endpoint) return live() ? busy() : "stale_session";
  return strcmp(token_, token) ? "stale_session" : nullptr;
}
const char* Session::claim(Endpoint endpoint, const char* host, const char* token, uint32_t now) {
  if (!lower_hex(host, 32) || !lower_hex(token, 32)) return "bad_request";
  expire(now);
  if (owner == endpoint && !strcmp(token_, token) && !strcmp(host_, host)) {
    if (endpoint == Endpoint::Maintenance) touched_ = now;
    return nullptr;
  }
  if (live() && !((endpoint == Endpoint::Usb || endpoint == Endpoint::Maintenance) &&
      (owner == Endpoint::Ble || owner == Endpoint::LegacyBle)) &&
      !(endpoint == Endpoint::Maintenance && owner == Endpoint::Usb &&
        !strcmp(host_, host) && !strcmp(token_, token))) return busy();
  same_host = previous_host_[0] && !strcmp(previous_host_, host);
  fence(); owner = endpoint; touched_ = now; released_[0] = 0;
  strcpy(host_, host); strcpy(token_, token);
  if (endpoint != Endpoint::Maintenance) strcpy(previous_host_, host);
  return nullptr;
}
void Session::legacy(uint32_t now) {
  if (owner == Endpoint::None) { fence(); released_[0] = 0; owner = Endpoint::LegacyBle; touched_ = now; previous_host_[0] = 0; }
}
const char* Session::release(Endpoint endpoint, const char* token, uint32_t now) {
  expire(now);
  if (owner == Endpoint::None && released_endpoint_ == endpoint && !strcmp(released_, token)) return nullptr;
  const char* error = check(endpoint, token, now);
  if (error) return error;
  strcpy(released_, token); released_endpoint_ = endpoint; fence(); return nullptr;
}
const char* Session::sequence(uint32_t seq, const char* revision, const char* payload) {
  if (seq == seq_ && seq_) return !strcmp(payload_, payload) && !strcmp(revision_, revision) ? "retry" : "conflict";
  return seq_ == UINT32_MAX || seq != seq_ + 1 ? "out_of_order" : nullptr;
}
void Session::remember(uint32_t seq, const char* revision, const char* payload, const char* error) {
  if(!revision || !payload || strlen(revision)>10 || strlen(payload)>512 || (error && strlen(error)>=sizeof(outcome_)))return;
  seq_ = seq; strcpy(revision_, revision); strcpy(payload_, payload);
  if (error) strcpy(outcome_, error); else outcome_[0] = 0;
}
int AlertLedger::accept(const char* id, uint32_t now) {
  if (!lower_hex(id, 12)) return -1;
  Entry* free = nullptr;
  for (auto& entry : entries_) {
    bool live = entry.id[0] && uint32_t(now - entry.at) < 65000;
    if (live && !strcmp(entry.id, id)) return 1;
    if (!live && !free) free = &entry;
  }
  if (!free) return -1;
  strcpy(free->id, id); free->at = now; return 0;
}
}
