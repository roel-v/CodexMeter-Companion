#pragma once

#include <Arduino.h>

void ble_service_init();
void ble_service_tick();
bool ble_service_has_data();
const char* ble_service_take_data();
void ble_service_ack();
void ble_service_nack();
void ble_service_request_refresh();
bool ble_service_connected();
uint32_t ble_service_epoch();
bool ble_service_data_current();
void ble_service_fence(const char* busy_error);
void ble_service_reply(const char* reply);
void ble_service_lock();
void ble_service_unlock();
void ble_service_identity_changed();
bool ble_service_can_dispatch();
bool ble_service_take_identity_read();
