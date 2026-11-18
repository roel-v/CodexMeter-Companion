#include "config.h"
#if !CODEXMETER_HAS_IMU
#include <Preferences.h>
#include "orientation.h"
namespace {
Preferences rotation_store;
uint8_t rotation = 0;
bool rotation_store_ok = false;
}
bool orientation_init() {
  rotation_store_ok=rotation_store.begin("ball_display",false);
  if(rotation_store_ok) rotation=rotation_store.getUChar("rotation",0)&3;
  return rotation_store_ok;
}
bool orientation_set_rotation_quadrant(uint8_t value) {
  if(value>3) return false;
  if(value!=rotation) { rotation=value; if(rotation_store_ok) rotation_store.putUChar("rotation",value); }
  return true;
}
uint8_t orientation_rotation_quadrant() { return rotation; }
const char* orientation_rotation_label(uint8_t value) { static const char* labels[]={"0","90","180","270"}; return labels[value&3]; }
void orientation_print_status(Stream& out) { out.printf("ROTATION manual=%u sensor=none\n",rotation*90); }
#endif
