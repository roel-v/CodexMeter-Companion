#include "companion_protocol.h"
#include "wire_json.h"
#include <ArduinoJson.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
namespace companion {
// ArduinoJson may request several pools. Track peak live allocations, including
// reallocation, and reject before exceeding the agreed 8 KiB wire budget.
// Control objects are flat. Counting colons outside strings also detects keys
// ArduinoJson would otherwise silently overwrite. Nested control fields fail.
static bool flat_object(const char* text, size_t size, size_t keys) {
  bool string = false, escape = false; int depth = 0; size_t count = 0;
  for (size_t i = 0; i < size; ++i) {
    char c = text[i];
    if (string) { if (escape) escape = false; else if (c == '\\') escape = true; else if (c == '"') string = false; continue; }
    if (c == '"') string = true;
    else if (c == '{') { if (++depth != 1) return false; }
    else if (c == '}') --depth;
    else if (c == '[' || c == ']') return false;
    else if (c == ':') ++count;
  }
  return !string && depth == 0 && count == keys;
}
void Protocol::init(const char* boot, ProtocolHooks hooks) {
  session=Session{};strcpy(boot_, boot); hooks_ = hooks;
  staged_usb_[0]=staged_ble_[0]=0;usb_ready_=false;ble_ready_=true;
  usb_epoch_=ble_epoch_=usb_claim_q_=ble_claim_q_=0;
  active_usb_q_=active_ble_q_=0;
}
void Protocol::changed(Endpoint before) {
  if (hooks_.fenced) hooks_.fenced(before, session.owner, session.same_host);
}
void Protocol::tick(uint32_t now) {
  auto before = session.owner;
  if (session.expire(now)) changed(before);
}
void Protocol::identity(Endpoint endpoint) {
  if (endpoint == Endpoint::Usb) usb_ready_ = true; else ble_ready_ = true;
}
void Protocol::disconnected() {
  staged_ble_[0] = 0; ble_ready_ = true;
  if (session.owner == Endpoint::Ble || session.owner == Endpoint::LegacyBle) { auto before = session.owner; session.fence(); changed(before); }
}
bool Protocol::legacy_allowed() const { return session.owner == Endpoint::None || session.owner == Endpoint::LegacyBle; }
void Protocol::legacy_accepted(uint32_t now) { session.legacy(now); }
bool Protocol::raw_allowed() const { return session.owner != Endpoint::Usb; }
const char* Protocol::dispatch(Endpoint endpoint, const char* input, size_t size, uint32_t now) {
  reply_[0] = 0; tick(now);
  if (size > frame_limit || size < 5 || memcmp(input, "CM1 ", 4) || !valid_utf8(input, size)) return reply_;
  if (size >= 9 && !memcmp(input + 4, "DATA ", 5)) {
    // Header is parsed in bounded local storage, preserving the application's bytes.
    const char* cursor = input + 9;
    char fields[4][33]{};
    for (auto& field : fields) {
      const char* end = static_cast<const char*>(memchr(cursor, ' ', size - size_t(cursor - input)));
      if (!end || end == cursor || size_t(end - cursor) >= sizeof(field)) return reply_;
      memcpy(field, cursor, end - cursor); cursor = end + 1;
    }
    uint32_t seq = 0, rev = 0;
    if (!lower_hex(fields[0], 16) || !lower_hex(fields[1], 32) || !decimal(fields[2], seq)) return reply_;
    bool revision_valid = !strcmp(fields[3], "-") || decimal(fields[3], rev, true);
    size_t length = size - size_t(cursor - input);
    if (!revision_valid || !length || length > payload_limit) return reply_;
    char payload[payload_limit + 1];memcpy(payload,cursor,length);payload[length]=0;
    const char* error = strcmp(fields[0], boot_) ? "bad_boot" : session.check(endpoint, fields[1], now);
    if (!error) {
      error = session.sequence(seq, fields[3], payload);
      if (error && !strcmp(error, "retry")) error = session.outcome();
      else if (!error) {
        error = hooks_.apply(payload, fields[3]);
        session.remember(seq, fields[3], payload, error);
      }
    }
    if (error) snprintf(reply_, sizeof(reply_), "CM1 {\"boot\":\"%s\",\"token\":\"%s\",\"seq\":%lu,\"ok\":false,\"err\":\"%s\"}", boot_, fields[1], (unsigned long)seq, error);
    else snprintf(reply_, sizeof(reply_), "CM1 {\"boot\":\"%s\",\"token\":\"%s\",\"seq\":%lu,\"ok\":true}", boot_, fields[1], (unsigned long)seq);
    return reply_;
  }
  BoundedJsonAllocator allocator;
  JsonDocument doc(&allocator);
  if (!exact_json(doc,input+4,size-4)) return reply_;
  JsonObject object = doc.as<JsonObject>();
  if (!doc["q"].is<uint32_t>() || !doc["q"].as<uint32_t>()) return reply_;
  uint32_t q = doc["q"];
  const char* token = doc["token"].is<const char*>() ? doc["token"].as<const char*>() : "";
  const char* boot = doc["boot"].is<const char*>() ? doc["boot"].as<const char*>() : "";
  const char* op = doc["op"].is<const char*>() ? doc["op"].as<const char*>() : "";
  const char* host = doc["host"].is<const char*>() ? doc["host"].as<const char*>() : "";
  bool claim = !strcmp(op, "claim"), maint = !strcmp(op, "maint"), state = !strcmp(op, "state");
  bool ping = !strcmp(op, "ping"), release = !strcmp(op, "release"), end = !strcmp(op, "maint_end");
  const char* error = nullptr;
  for(const char* key : {"op","boot","host","token"})
    if(!doc[key].isNull() && !json_cstring(doc[key])) error="bad_request";
  size_t expected = claim || maint ? 5 : 4;
  if (!flat_object(input + 4, size - 4, object.size()) || object.size() != expected ||
      !lower_hex(boot, 16) || !lower_hex(token, 32) || ((claim || maint) && !lower_hex(host, 32))) error = "bad_request";
  for (JsonPair pair : object) {
    const char* key = pair.key().c_str();
    if(pair.key().size()!=strlen(key))error="bad_request";
    if (strcmp(key,"op") && strcmp(key,"q") && strcmp(key,"boot") && strcmp(key,"token") &&
        (!((claim || maint) && !strcmp(key,"host")))) error = "bad_request";
  }
  if (!error && strcmp(boot, boot_)) error = "bad_boot";
  auto before = session.owner; uint32_t epoch = session.epoch;
  if (!error && (claim || maint)) {
    if (maint && endpoint != Endpoint::Usb) error = "unsupported";
    char* staged = endpoint == Endpoint::Usb ? staged_usb_ : staged_ble_;
    bool& ready = endpoint == Endpoint::Usb ? usb_ready_ : ble_ready_;
    uint32_t& claim_q = endpoint == Endpoint::Usb ? usb_claim_q_ : ble_claim_q_;
    uint32_t& staged_epoch = endpoint == Endpoint::Usb ? usb_epoch_ : ble_epoch_;
    uint32_t& active_q = endpoint == Endpoint::Usb ? active_usb_q_ : active_ble_q_;
    bool live_claim=claim && !session.check(endpoint,token,now);
    bool live_maintenance=maint && endpoint==Endpoint::Usb &&
      (session.owner==Endpoint::Usb || session.owner==Endpoint::Maintenance) &&
      !session.check(session.owner,token,now);
    if(live_claim || live_maintenance) {
      if(live_claim && q!=active_q)error="stale_session";
      else error=session.claim(maint?Endpoint::Maintenance:endpoint,host,token,now);
      if(!error && live_maintenance) { strcpy(staged,token);staged_epoch=session.epoch; }
    } else {
    bool fresh_token=false;
    if (!error && strcmp(staged, token)) {
      if (!ready) error = "stale_session";
      else { strcpy(staged, token); ready = false; claim_q = q; staged_epoch = 0;fresh_token=true; }
    } else if (!error && claim && claim_q != q) error = "stale_session";
    if (!error && staged_epoch && staged_epoch != session.epoch && !strcmp(staged, token)) error = "stale_session";
    if(!error && !fresh_token && !staged_epoch)error="stale_session";
    if (!error) {
      error = session.claim(maint ? Endpoint::Maintenance : endpoint, host, token, now);
      if (!error) { staged_epoch = session.epoch;if(claim)active_q=q; }
    }
    }
  } else if (!error && (ping || state || release || end)) {
    Endpoint owner = end ? Endpoint::Maintenance : endpoint;
    if (end && endpoint != Endpoint::Usb) error = "unsupported";
    else if (release || end) error = session.release(owner, token, now);
    else { error = session.check(owner, token, now); if (!error && ping) session.ping(now); }
  } else if (!error) error = "bad_request";
  if (epoch != session.epoch) changed(before);
  // Reuse the bounded JSON document for a small response; strings above are
  // copied to fixed storage before clearing its pool.
  char token_copy[33]{};
  if (lower_hex(token, 32)) strcpy(token_copy, token);
  doc.clear(); doc["boot"] = boot_; doc["q"] = q;
  if (token_copy[0]) doc["token"] = token_copy;
  doc["ok"] = error == nullptr;
  if (error) doc["err"] = error;
  else if (claim || state) {
    DisplayState s = hooks_.state(); JsonObject out = doc["state"].to<JsonObject>();
    out["same_host"] = session.same_host; out["rev"] = s.rev; out["page"] = s.page;
    out["brightness"] = s.brightness; out["rotation"] = s.rotation;
    out["auto_rotation"] = s.auto_rotation; out["manual_on"] = s.manual_on;
    out["policy_on"] = s.policy_on; out["screen_on"] = s.screen_on;
  }
  memcpy(reply_, "CM1 ", 4);
  if(doc.overflowed() || measureJson(doc)>sizeof(reply_)-5) { reply_[0]=0;return reply_; }
  serializeJson(doc, reply_ + 4, sizeof(reply_) - 4);
  return reply_;
}
}
