#pragma once
#include <stddef.h>
#include <stdint.h>

namespace companion {
constexpr size_t frame_limit = 640;
constexpr size_t payload_limit = 512;
// Fixed storage; overflow and timeout discard the entire frame through LF.
class LineDecoder {
 public:
  bool push(uint8_t byte, uint32_t now);
  void tick(uint32_t now);
  const char* data() const { return bytes_; }
  size_t size() const { return size_; }
 private:
  char bytes_[frame_limit + 1]{};
  size_t used_ = 0, size_ = 0;
  uint32_t started_ = 0;
  bool active_ = false, discard_ = false;
};

class FragmentDecoder {
 public:
  bool push(const uint8_t* bytes, size_t size, uint32_t now);
  void clear() { used_ = total_ = 0; }
  const char* data() const { return bytes_; }
  size_t size() const { return total_; }
 private:
  char bytes_[frame_limit + 1]{};
  size_t used_ = 0, total_ = 0;
  uint32_t started_ = 0;
};
bool lower_hex(const char* text, size_t count);
bool decimal(const char* text, uint32_t& value, bool allow_zero = false);
bool valid_utf8(const char* text, size_t size, bool allow_controls = false);
}
