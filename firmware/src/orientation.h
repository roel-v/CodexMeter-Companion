#pragma once

#include <Arduino.h>
#include "board_profile.h"

bool orientation_init();
#if CODEXMETER_HAS_IMU
void orientation_tick();
void orientation_set_display_active(bool active);

bool orientation_available();
bool orientation_auto_rotation_enabled();
void orientation_set_auto_rotation(bool enabled);
#endif
bool orientation_set_rotation_quadrant(uint8_t quadrant);
uint8_t orientation_rotation_quadrant();

#if CODEXMETER_HAS_IMU
bool orientation_last_sample(float* ax, float* ay, float* az);
#endif
const char* orientation_rotation_label(uint8_t quadrant);
void orientation_print_status(Stream& out);
