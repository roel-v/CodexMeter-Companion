#pragma once
#include <stddef.h>
namespace companion {
constexpr size_t frame_limit = 640;
constexpr size_t payload_limit = 512;
// ATT values have an independent Bluetooth specification limit.
constexpr size_t ble_att_value_limit = 512;
}
