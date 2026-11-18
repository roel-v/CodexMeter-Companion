#pragma once
#include "companion_session.h"
namespace companion {
struct DisplayState {
  uint32_t rev = 1;
  int page = 0, brightness = 60, rotation = 0;
  bool auto_rotation = true, manual_on = true, policy_on = true, screen_on = true;
};
struct ProtocolHooks {
  DisplayState (*state)();
  const char* (*apply)(const char*, const char*);
  void (*fenced)(Endpoint, Endpoint, bool);
};
class Protocol {
 public:
  Session session;
  void init(const char* boot, ProtocolHooks hooks);
  void tick(uint32_t now);
  void identity(Endpoint endpoint);
  void disconnected();
  // Output is empty for an uncorrelatable frame. Caller routes only to source.
  const char* dispatch(Endpoint endpoint, const char* input, size_t size, uint32_t now);
  bool legacy_allowed() const;
  void legacy_accepted(uint32_t now);
  bool raw_allowed() const;
 private:
  char boot_[17]{};
  char reply_[641]{};
  char staged_usb_[33]{}, staged_ble_[33]{};
  bool usb_ready_ = false, ble_ready_ = true;
  uint32_t usb_claim_q_ = 0, ble_claim_q_ = 0;
  uint32_t usb_epoch_ = 0, ble_epoch_ = 0;
  uint32_t active_usb_q_ = 0, active_ble_q_ = 0;
  ProtocolHooks hooks_{};
  void changed(Endpoint previous);
};
}
