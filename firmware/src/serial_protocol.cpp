#include "serial_protocol.h"
#include <string.h>
namespace companion {
void LineDecoder::tick(uint32_t now) {
  if (active_ && uint32_t(now - started_) >= 1000) { discard_ = true; used_ = 0; }
}
bool LineDecoder::push(uint8_t byte, uint32_t now) {
  tick(now);
  if (byte == '\n') {
    bool ready = !discard_ && used_ != 0;
    if (ready && bytes_[used_ - 1] == '\r') --used_;
    for (size_t i = 0; ready && i < used_; ++i)
      if (uint8_t(bytes_[i]) < 32 || bytes_[i] == 127) ready = false;
    size_ = used_; bytes_[used_] = 0;
    used_ = 0; active_ = discard_ = false;
    return ready && size_ != 0;
  }
  if (!active_) { active_ = true; started_ = now; }
  if (discard_) return false;
  if (used_ == frame_limit) { discard_ = true; used_ = 0; return false; }
  bytes_[used_++] = char(byte);
  return false;
}
bool FragmentDecoder::push(const uint8_t* b, size_t n, uint32_t now) {
  if (n < 6 || b[0] != 0x1e) { clear(); return false; }
  size_t total = size_t(b[1]) * 256 + b[2], offset = size_t(b[3]) * 256 + b[4];
  if (!offset) { clear(); total_ = total; started_ = now; }
  if (!total || total > frame_limit || total != total_ || offset != used_ ||
      uint32_t(now - started_) >= 2000 || n - 5 > total - used_) {
    clear(); return false;
  }
  memcpy(bytes_ + used_, b + 5, n - 5); used_ += n - 5;
  if (used_ != total_) return false;
  bytes_[total_] = 0;
  // A completed train is not eligible for a second nonzero-offset dispatch.
  used_ = 0;
  return true;
}
bool lower_hex(const char* s, size_t n) {
  if (!s || strlen(s) != n) return false;
  for (size_t i = 0; i < n; ++i)
    if (!((s[i] >= '0' && s[i] <= '9') || (s[i] >= 'a' && s[i] <= 'f'))) return false;
  return true;
}
bool decimal(const char* s, uint32_t& out, bool zero) {
  if (!s || !*s || (s[0] == '0' && s[1])) return false;
  uint32_t v = 0;
  for (; *s; ++s) {
    if (*s < '0' || *s > '9' || v > (UINT32_MAX - uint32_t(*s - '0')) / 10) return false;
    v = v * 10 + (*s - '0');
  }
  out = v; return zero || v != 0;
}
bool valid_utf8(const char* text, size_t n, bool allow_controls) {
  const auto* s = reinterpret_cast<const uint8_t*>(text);
  for (size_t i = 0; i < n;) {
    uint32_t c = s[i++]; unsigned more = 0; uint32_t minimum = 0;
    if (c < 0x80) { if (!allow_controls && (c < 32 || c == 127)) return false; continue; }
    if (c >= 0xc2 && c <= 0xdf) { c &= 31; more = 1; minimum = 0x80; }
    else if (c >= 0xe0 && c <= 0xef) { c &= 15; more = 2; minimum = 0x800; }
    else if (c >= 0xf0 && c <= 0xf4) { c &= 7; more = 3; minimum = 0x10000; }
    else return false;
    if (more > n - i) return false;
    while (more--) { if ((s[i] & 0xc0) != 0x80) return false; c = (c << 6) | (s[i++] & 63); }
    if (c < minimum || c > 0x10ffff || (c >= 0xd800 && c <= 0xdfff)) return false;
  }
  return true;
}
}
