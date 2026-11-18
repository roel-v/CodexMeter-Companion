#include <Arduino.h>
#include <Arduino_GFX_Library.h>
#include <lvgl.h>
#include <esp_err.h>
#include <esp_heap_caps.h>
#include <esp_rom_crc.h>
#include <esp_system.h>
#include <esp_task_wdt.h>
#if ARDUINO_USB_MODE == 1 && SOC_USB_SERIAL_JTAG_SUPPORTED
#include <hal/usb_serial_jtag_ll.h>
#endif

#include "ble_service.h"
#include "config.h"
#include "device_settings.h"
#include "device_log.h"
#include "display_rotation.h"
#include "display_panel.h"
#include "identity.h"
#include "imu.h"
#include "model.h"
#include "power.h"
#include "theme_registry.h"
#include "ui.h"
#include "touch_input.h"
#include "companion_protocol.h"
#include "wire_json.h"

#ifdef BOARD_HAS_PSRAM
#define LV_BUF_CAPS MALLOC_CAP_SPIRAM
#define BUF_LINES 40
#else
#define LV_BUF_CAPS (MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT)
#define BUF_LINES CODEXMETER_DRAW_BUFFER_LINES
#endif

#ifdef CODEXMETER_BOARD_BALL
static Arduino_DataBus* bus = new Arduino_ESP32SPI(47, 5, 4, 2, -1);
static CodexMeterPanel* gfx = new CodexMeterPanel(bus);
#else
static Arduino_DataBus* bus = new Arduino_ESP32QSPI(
    CODEXMETER_LCD_CS, CODEXMETER_LCD_SCLK, CODEXMETER_LCD_D0, CODEXMETER_LCD_D1,
    CODEXMETER_LCD_D2, CODEXMETER_LCD_D3);
static CodexMeterPanel* gfx = new CodexMeterPanel(
    bus, CODEXMETER_LCD_RST, 0, CODEXMETER_SCREEN_W, CODEXMETER_SCREEN_H, 0, 0, 0, 0);
#endif

enum class GpioButtonEvent : uint8_t {
  None,
  ShortPress,
  LongPress,
};

struct GpioButtonState {
  uint8_t pin;
  bool raw_down;
  bool stable_down;
  bool long_press_sent;
  uint32_t raw_changed_ms;
  uint32_t pressed_ms;
};

static uint16_t* lv_buf_1 = nullptr;
static uint16_t* lv_buf_2 = nullptr;
static void* lvgl_psram_pool = nullptr;
static lv_mem_pool_t lvgl_psram_mem_pool = nullptr;
static UsageModel usage;
static AlertModel alert;
static ActivityModel activity;
static ControlModel control;
static companion::Protocol companion_protocol;
static companion::AlertLedger alert_ledger;
static bool manual_screen_on = true, policy_screen_on = true;
static uint32_t settings_revision = 1;
static uint32_t last_usage_ms = 0;
static uint32_t last_host_payload_ms = 0;
// Bounded serial-only UI validation; never persisted across reboot.
static uint32_t serial_ui_test_ms = 0;
static bool screen_on = true;
static bool watchdog_enabled = false;
static int brightness_percent = CODEXMETER_BRIGHTNESS_DEFAULT;
static int displayed_battery_percent = -1;
static bool displayed_battery_charging = false;
static bool displayed_battery_valid = false;
static uint8_t displayed_rotation = 0;
static uint8_t rotation_ramp_step = 0;
static uint32_t rotation_ramp_last_ms = 0;

static uint32_t lv_tick() {
  return millis();
}

static const char* reset_reason_label(esp_reset_reason_t reason) {
  switch (reason) {
    case ESP_RST_POWERON:
      return "poweron";
    case ESP_RST_EXT:
      return "external";
    case ESP_RST_SW:
      return "software";
    case ESP_RST_PANIC:
      return "panic";
    case ESP_RST_INT_WDT:
      return "int_wdt";
    case ESP_RST_TASK_WDT:
      return "task_wdt";
    case ESP_RST_WDT:
      return "wdt";
    case ESP_RST_DEEPSLEEP:
      return "deepsleep";
    case ESP_RST_BROWNOUT:
      return "brownout";
    case ESP_RST_SDIO:
      return "sdio";
    case ESP_RST_USB:
      return "usb";
    case ESP_RST_JTAG:
      return "jtag";
    case ESP_RST_EFUSE:
      return "efuse";
    case ESP_RST_PWR_GLITCH:
      return "power_glitch";
    case ESP_RST_CPU_LOCKUP:
      return "cpu_lockup";
    default:
      return "unknown";
  }
}

static void feed_watchdog() {
  if (watchdog_enabled) {
    esp_task_wdt_reset();
  }
}

static void init_watchdog() {
#if CODEXMETER_WATCHDOG_TIMEOUT_SEC > 0
  esp_task_wdt_config_t config = {};
  config.timeout_ms = CODEXMETER_WATCHDOG_TIMEOUT_SEC * 1000UL;
  config.idle_core_mask = 0;
  config.trigger_panic = true;

  esp_err_t err = esp_task_wdt_init(&config);
  if (err == ESP_ERR_INVALID_STATE) {
    err = esp_task_wdt_reconfigure(&config);
  }
  if (err != ESP_OK) {
    device_logf("WARN", "watchdog init failed %s", esp_err_to_name(err));
    return;
  }

  err = esp_task_wdt_add(nullptr);
  if (err == ESP_OK || err == ESP_ERR_INVALID_STATE) {
    watchdog_enabled = true;
    device_logf(
        "INFO", "watchdog enabled timeout=%lus",
        (unsigned long)CODEXMETER_WATCHDOG_TIMEOUT_SEC);
  } else {
    device_logf("WARN", "watchdog add failed %s", esp_err_to_name(err));
  }
#endif
}

static void log_lvgl_mem(const char* phase) {
  lv_mem_monitor_t mon;
  lv_mem_monitor(&mon);
  device_logf(
      "INFO", "lv_mem %s t=%lu f=%lu b=%lu u=%u g=%u",
      phase && phase[0] ? phase : "-", (unsigned long)mon.total_size,
      (unsigned long)mon.free_size, (unsigned long)mon.free_biggest_size,
      mon.used_pct, mon.frag_pct);
}

static bool capture_tiles = false;

static void lv_flush(lv_display_t* disp, const lv_area_t* area, uint8_t* px_map) {
  if (!screen_on) {
    lv_display_flush_ready(disp);
    return;
  }

  int32_t w = area->x2 - area->x1 + 1;
  int32_t h = area->y2 - area->y1 + 1;
  if (capture_tiles) {
    const size_t bytes = w * h * sizeof(uint16_t);
    Serial.printf("TILE %ld %ld %ld %ld %u %lu\n", (long)area->x1, (long)area->y1,
                  (long)w, (long)h, (unsigned)bytes,
                  (unsigned long)esp_rom_crc32_le(0, px_map, bytes));
    size_t sent = 0;
    while (sent < bytes) {
      const size_t chunk = bytes - sent > 1024 ? 1024 : bytes - sent;
      size_t written = Serial.write(px_map + sent, chunk);
      if (!written) { capture_tiles = false; break; }
      sent += written;
      delay(1);
    }
    Serial.println();
    feed_watchdog();
  }
  display_rotation_draw(
      gfx, area->x1, area->y1, w, h, (uint16_t*)px_map, imu_rotation_quadrant());
  lv_display_flush_ready(disp);
}

static void lv_rounder(lv_event_t* event) {
  lv_area_t* area = (lv_area_t*)lv_event_get_param(event);
  area->x1 = area->x1 & ~1;
  area->y1 = area->y1 & ~1;
  area->x2 = area->x2 | 1;
  area->y2 = area->y2 | 1;
}

static int clamp_brightness(int pct) {
  if (pct < CODEXMETER_BRIGHTNESS_MIN) return CODEXMETER_BRIGHTNESS_MIN;
  if (pct > CODEXMETER_BRIGHTNESS_MAX) return CODEXMETER_BRIGHTNESS_MAX;
  return pct;
}

static uint8_t brightness_raw_from_percent(int pct) {
  pct = clamp_brightness(pct);
  uint8_t raw = (uint8_t)((pct * 255 + 50) / 100);
  if (raw == 0) raw = 1;
  return raw;
}

static void apply_brightness() {
  gfx->setBrightness(brightness_raw_from_percent(brightness_percent));
}

static void refresh_battery_ui(bool force) {
  const int battery_percent = power_battery_percent();
  const bool charging = power_is_charging();
  if (!force && displayed_battery_valid &&
      battery_percent == displayed_battery_percent &&
      charging == displayed_battery_charging) {
    return;
  }

  displayed_battery_percent = battery_percent;
  displayed_battery_charging = charging;
  displayed_battery_valid = true;
  ui_set_battery(battery_percent, charging);
}

static void display_init() {
  if (!gfx->begin()) {
    device_logf("ERROR", "gfx begin failed");
  }
#ifdef CODEXMETER_BOARD_C6
  // Exact panel setup from Waveshare's 09_LVGL_V9_Test/bsp_lvgl_port.cpp.
  bus->beginWrite();
  bus->writeCommand(0x11);
  bus->endWrite();
  delay(600);
  bus->beginWrite();
  bus->writeC8D8(0xFE, 0x20);
  bus->writeC8D8(0x19, 0x10);
  bus->writeC8D8(0x1C, 0xA0);
  bus->writeC8D8(0xFE, 0x00);
  bus->writeC8D8(0xC4, 0x80);
  bus->writeC8D8(0x3A, 0x55);
  bus->writeC8D8(0x35, 0x00);
  bus->writeC8D8(0x36, 0x30);
  bus->writeC8D8(0x53, 0x20);
  bus->writeC8D8(0x51, 0xFF);
  bus->writeC8D8(0x63, 0xFF);
  bus->writeCommand(0x29);
  bus->endWrite();
  delay(100);
#endif
  screen_on = true;
  apply_brightness();
  gfx->fillScreen(0x0000);
  display_rotation_init();

  lv_init();
#if LV_USE_LOG
  lv_log_register_print_cb([](lv_log_level_t, const char* message) {
    device_logf("LVGL", "%s", message);
  });
#endif
  lv_tick_set_cb(lv_tick);

#ifdef BOARD_HAS_PSRAM
  lvgl_psram_pool = heap_caps_malloc(
      CODEXMETER_LVGL_PSRAM_POOL_BYTES, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
  if (lvgl_psram_pool) {
    lvgl_psram_mem_pool =
        lv_mem_add_pool(lvgl_psram_pool, CODEXMETER_LVGL_PSRAM_POOL_BYTES);
    if (lvgl_psram_mem_pool) {
      device_logf(
          "INFO", "LVGL PSRAM pool=%p bytes=%lu", lvgl_psram_pool,
          (unsigned long)CODEXMETER_LVGL_PSRAM_POOL_BYTES);
      log_lvgl_mem("pool_added");
    } else {
      device_logf(
          "WARN", "LVGL PSRAM pool add failed ptr=%p bytes=%lu",
          lvgl_psram_pool, (unsigned long)CODEXMETER_LVGL_PSRAM_POOL_BYTES);
      heap_caps_free(lvgl_psram_pool);
      lvgl_psram_pool = nullptr;
    }
  } else {
    device_logf("WARN", "LVGL PSRAM pool alloc failed");
  }
#endif

  lv_buf_1 = (uint16_t*)heap_caps_malloc(
      CODEXMETER_SCREEN_W * BUF_LINES * sizeof(uint16_t), LV_BUF_CAPS);
  lv_buf_2 = (uint16_t*)heap_caps_malloc(
      CODEXMETER_SCREEN_W * BUF_LINES * sizeof(uint16_t), LV_BUF_CAPS);
  if (!lv_buf_1 || !lv_buf_2) {
    device_logf("ERROR", "LVGL buffer allocation failed");
    while (true) delay(1000);
  }

  lv_display_t* disp = lv_display_create(CODEXMETER_SCREEN_W, CODEXMETER_SCREEN_H);
  lv_display_set_color_format(disp, LV_COLOR_FORMAT_RGB565);
  lv_display_set_flush_cb(disp, lv_flush);
  lv_display_add_event_cb(disp, lv_rounder, LV_EVENT_INVALIDATE_AREA, nullptr);
  lv_display_set_buffers(
      disp, lv_buf_1, lv_buf_2, CODEXMETER_SCREEN_W * BUF_LINES * sizeof(uint16_t),
      LV_DISPLAY_RENDER_MODE_PARTIAL);
}

static const char* non_empty_reason(const char* reason) {
  return reason && reason[0] ? reason : "control";
}

static void set_screen_on(bool on, const char* reason, bool legacy = false) {
  bool policy = companion::screen_policy_reason(reason,legacy,on);
  if (policy) policy_screen_on = on; else manual_screen_on = on;
  on = manual_screen_on && policy_screen_on;
  if (screen_on == on) return;

  screen_on = on;
  if (screen_on) {
    power_set_display_active(true);
    imu_set_display_active(true);
    refresh_battery_ui(true);
    gfx->displayOn();
    apply_brightness();
    ui_set_display_active(true);
    lv_obj_invalidate(lv_screen_active());
    lv_refr_now(nullptr);
    device_logf("INFO", "screen on %s", policy ? "policy" : "manual");
  } else {
    ui_set_display_active(false);
    imu_set_display_active(false);
    power_set_display_active(false);
    gfx->displayOff();
    device_logf("INFO", "screen off %s", policy ? "policy" : "manual");
  }
}

static void toggle_screen(const char* reason) {
  set_screen_on(!screen_on, reason);
}

static void set_brightness_percent_internal(
    int pct, const char* reason, bool show_overlay) {
  brightness_percent = clamp_brightness(pct);
  device_settings_set_brightness(brightness_percent);
  apply_brightness();
  if (show_overlay) {
    ui_show_brightness(brightness_percent);
  }
  device_logf(
      "INFO", "brightness %d reason=%s", brightness_percent,
      non_empty_reason(reason));
}

static void set_brightness_percent(int pct, const char* reason) {
  set_brightness_percent_internal(pct, reason, true);
}

static void settings_apply_brightness(int pct) {
  set_brightness_percent_internal(pct, "settings", false);
}

static void adjust_brightness(int delta, const char* reason) {
  set_brightness_percent(brightness_percent + delta, reason);
}

static bool parse_int_arg(const char* text, int* value) {
  if (!text || !*text || !value) return false;
  char* end = nullptr;
  long parsed = strtol(text, &end, 10);
  if (*end != '\0') return false;
  *value = (int)parsed;
  return true;
}

static void redraw_for_rotation() {
  if (!screen_on) return;
  gfx->setBrightness(0);
  lv_obj_invalidate(lv_screen_active());
  lv_refr_now(nullptr);
  rotation_ramp_step = 1;
  rotation_ramp_last_ms = 0;
}

static void handle_orientation() {
  imu_tick();

  uint8_t rotation = imu_rotation_quadrant();
  if (rotation != displayed_rotation) {
    displayed_rotation = rotation;
    device_logf("INFO", "display rotation=%u deg=%s", rotation,
                imu_rotation_label(rotation));
    redraw_for_rotation();
  }

  if (!screen_on || rotation_ramp_step == 0) return;

  uint32_t now = millis();
  if (now - rotation_ramp_last_ms < CODEXMETER_ROTATION_RAMP_STEP_MS) return;
  rotation_ramp_last_ms = now;

  static const uint8_t ramp_pct[] = {30, 60, 85, 100};
  uint8_t target = brightness_raw_from_percent(brightness_percent);
  uint8_t raw =
      (uint8_t)(((uint16_t)target * ramp_pct[rotation_ramp_step - 1]) / 100);
  if (raw == 0) raw = 1;
  gfx->setBrightness(raw);

  if (rotation_ramp_step >= sizeof(ramp_pct)) {
    rotation_ramp_step = 0;
    apply_brightness();
  } else {
    rotation_ramp_step++;
  }
}

static const char* handle_json(const char* json, const char* revision) {
  UsageModel next_usage = usage;
  AlertModel next_alert;
  ActivityModel next_activity = activity;
  ControlModel next_control;
  PayloadKind kind = parse_payload(json, &next_usage, &next_alert, &next_activity, &next_control);
  if (kind == PAYLOAD_NONE) return "bad_request";
  if (kind == PAYLOAD_CONTROL && revision) {
    bool policy = !strcmp(next_control.command,"screen") &&
      (!strcmp(next_control.reason,"lock") || !strcmp(next_control.reason,"unlock"));
    if (policy && ((!strcmp(next_control.reason,"lock") && next_control.screen_on) ||
                   (!strcmp(next_control.reason,"unlock") && !next_control.screen_on))) return "bad_request";
    if (policy) { if (strcmp(revision,"-")) return "bad_request"; }
    else {
      uint32_t expected = 0;
      if (!companion::decimal(revision,expected,true)) return "bad_request";
      if (expected != settings_revision) return "conflict";
    }
  } else if (revision && strcmp(revision,"-")) return "bad_request";
  if (kind == PAYLOAD_ALERT) {
    int result = alert_ledger.accept(next_alert.id,millis());
    if (result < 0) return "conflict";
    if (result > 0) return nullptr;
  }
  // Parsing and ownership/revision checks completed before any model mutation.
  if(kind==PAYLOAD_CONTROL && !strcmp(next_control.command,"rotation")) {
    if(!imu_set_rotation_quadrant(next_control.value/90))return "unsupported";
  }
  if(kind==PAYLOAD_USAGE)usage=next_usage;
  if(kind==PAYLOAD_ALERT)alert=next_alert;
  if(kind==PAYLOAD_ACTIVITY)activity=next_activity;
  if(kind==PAYLOAD_CONTROL)control=next_control;
  if (kind == PAYLOAD_USAGE || kind == PAYLOAD_ACTIVITY) {
    last_host_payload_ms = millis();
    // Waiting is a visible view, not a power state. Data must never undo an
    // explicit local/host screen-off request, including after reconnection.
    ui_set_waiting(false);
  }
  if (kind == PAYLOAD_USAGE) {
    last_usage_ms = millis();
    ui_update_usage(usage);
    device_logf(
        "INFO", "usage h5=%d d7=%d td=%llu t7=%llu token_mode=%d",
        usage.h5_remaining, usage.d7_remaining,
        (unsigned long long)usage.today_tokens,
        (unsigned long long)usage.last_7d_tokens,
        usage.h5_remaining < 0 && usage.d7_remaining >= 0 ? 1 : 0);
  } else if (kind == PAYLOAD_ALERT) {
    if (alert.has_running_count) {
      activity.valid = true;
      activity.running_count = alert.running_count;
      activity.updated_at = alert.received_at;
      ui_update_activity(activity);
    }
    ui_show_alert(alert);
    if (alert.has_running_count) {
      device_logf("INFO", "alert id=%s run=%d", alert.id, alert.running_count);
    } else {
      device_logf("INFO", "alert id=%s run=n/a", alert.id);
    }
  } else if (kind == PAYLOAD_ACTIVITY) {
    ui_update_activity(activity);
    device_logf("INFO", "activity run=%d wait=%d done=%d chats=%d",
        activity.running_count, activity.waiting_count, activity.done_count,
        activity.chat_counts_valid);
  } else if (kind == PAYLOAD_CONTROL) {
    if (strcmp(control.command, "brightness") == 0) {
      set_brightness_percent(control.value,"companion");
    } else if (strcmp(control.command, "rotation") == 0) {
      // Applied before model commit above.
    } else if (strcmp(control.command, "screen") == 0) {
      set_screen_on(control.screen_on, control.reason,revision==nullptr);
      device_logf("INFO", "control screen=%d", control.screen_on ? 1 : 0);
    } else {
      device_logf("WARN", "invalid control command");
      return "unsupported";
    }
  } else {
    device_logf("WARN", "invalid payload");
    return "bad_request";
  }
  return nullptr;
}

static void send_screenshot() {
#ifndef BOARD_HAS_PSRAM
  if (!screen_on) { Serial.println("SCREENSHOT_SCREEN_OFF"); return; }
  device_log_serial_enabled(false);
  Serial.flush();
  Serial.printf("TILED_SCREENSHOT_START %d %d\n", CODEXMETER_SCREEN_W, CODEXMETER_SCREEN_H);
  capture_tiles = true;
  lv_obj_invalidate(lv_screen_active());
  lv_refr_now(nullptr);
  Serial.println(capture_tiles ? "TILED_SCREENSHOT_END" : "TILED_SCREENSHOT_FAILED");
  capture_tiles = false;
  device_log_serial_enabled(true);
  return;
#else
  const uint32_t w = CODEXMETER_SCREEN_W;
  const uint32_t h = CODEXMETER_SCREEN_H;
  const uint32_t row_bytes = w * sizeof(uint16_t);
  const uint32_t buf_size = row_bytes * h;

  uint8_t* sbuf = (uint8_t*)heap_caps_malloc(buf_size, MALLOC_CAP_SPIRAM);
  if (!sbuf) {
    device_logf("ERROR", "screenshot alloc failed");
    Serial.println("SCREENSHOT_ERR");
    return;
  }

  lv_timer_handler();
  lv_refr_now(nullptr);

  lv_draw_buf_t draw_buf;
  lv_result_t init_res =
      lv_draw_buf_init(&draw_buf, w, h, LV_COLOR_FORMAT_RGB565, row_bytes, sbuf, buf_size);
  if (init_res != LV_RESULT_OK) {
    heap_caps_free(sbuf);
    device_logf("ERROR", "screenshot draw buffer init failed");
    Serial.println("SCREENSHOT_ERR");
    return;
  }

  lv_result_t res =
      lv_snapshot_take_to_draw_buf(lv_screen_active(), LV_COLOR_FORMAT_RGB565, &draw_buf);
  if (res != LV_RESULT_OK) {
    heap_caps_free(sbuf);
    device_logf("ERROR", "screenshot snapshot failed");
    Serial.println("SCREENSHOT_ERR");
    return;
  }

  Serial.printf(
      "SCREENSHOT_START %lu %lu %lu\n", (unsigned long)w, (unsigned long)h,
      (unsigned long)buf_size);
  Serial.flush();
  const uint16_t* frame =
      display_rotation_frame((const uint16_t*)sbuf, imu_rotation_quadrant());
  const uint8_t* frame_bytes = (const uint8_t*)frame;
  uint32_t written = 0;
  while (written < buf_size) {
    uint32_t remaining = buf_size - written;
    uint32_t chunk = remaining > 4096UL ? 4096UL : remaining;
    Serial.write(frame_bytes + written, chunk);
    written += chunk;
    feed_watchdog();
    delay(0);
  }
  Serial.flush();
  Serial.println();
  Serial.println("SCREENSHOT_END");
  heap_caps_free(sbuf);
  device_logf("INFO", "screenshot sent %lux%lu", (unsigned long)w, (unsigned long)h);
#endif
}

static void handle_raw_line(const char* buf) {
      if (strcmp(buf, "demo_usage") == 0) {
        usage_apply_demo(&usage);
        last_usage_ms = millis();
        ui_update_usage(usage);
        device_logf("INFO", "serial demo_usage");
      } else if (strcmp(buf, "demo_token_usage") == 0) {
        usage_apply_token_demo(&usage);
        last_usage_ms = millis();
        ui_update_usage(usage);
        device_logf("INFO", "serial demo_token_usage");
      } else if (strcmp(buf, "test_ui_on") == 0) {
        serial_ui_test_ms = millis();
        Serial.println("TEST_UI on");
      } else if (strcmp(buf, "test_ui_off") == 0) {
        serial_ui_test_ms = 0;
        Serial.println("TEST_UI off");
      } else if (strcmp(buf, "test_swipe") == 0) {
        ui_touch_gesture(-120, 0, 180, 200, false);
      } else if (strcmp(buf, "touch_status") == 0) {
        touch_input_diagnostics();
      } else if (strcmp(buf, "test_tap_today") == 0) {
        ui_touch_gesture(0, 0, 110, 100, true);
      } else if (strcmp(buf, "test_tap_week") == 0) {
        ui_touch_gesture(0, 0, 350, 100, true);
      } else if (strcmp(buf, "demo_alert") == 0) {
        alert_apply_demo(&alert);
        ui_show_alert(alert);
        device_logf("INFO", "serial demo_alert");
      } else if (strcmp(buf, "demo_activity") == 0) {
        activity_apply_demo(&activity, 3);
        ui_update_activity(activity);
        device_logf("INFO", "serial demo_activity run=3");
      } else if (strcmp(buf, "demo_idle") == 0) {
        activity_apply_demo(&activity, 0);
        ui_update_activity(activity);
        device_logf("INFO", "serial demo_idle");
      } else if (strcmp(buf, "power") == 0) {
        power_refresh_and_log();
        refresh_battery_ui(true);
      } else if (strncmp(buf, "demo_battery ", 13) == 0) {
        int percent = 0;
        if (parse_int_arg(buf + 13, &percent) &&
            percent >= 0 && percent <= 100) {
          displayed_battery_percent = percent;
          displayed_battery_charging = false;
          displayed_battery_valid = true;
          ui_set_battery(percent, false);
          Serial.printf("DEMO_BATTERY %d\n", percent);
          device_logf("INFO", "serial demo_battery percent=%d", percent);
        } else {
          Serial.println("DEMO_BATTERY_INVALID");
        }
      } else if (strcmp(buf, "screen_on") == 0) {
        set_screen_on(true, "serial");
      } else if (strcmp(buf, "screen_off") == 0) {
        set_screen_on(false, "serial");
      } else if (strcmp(buf, "screen_toggle") == 0) {
        toggle_screen("serial");
      } else if (strcmp(buf, "brightness_up") == 0) {
        adjust_brightness(CODEXMETER_BRIGHTNESS_STEP, "serial");
      } else if (strcmp(buf, "brightness_down") == 0) {
        adjust_brightness(-CODEXMETER_BRIGHTNESS_STEP, "serial");
      } else if (strncmp(buf, "brightness ", 11) == 0) {
        set_brightness_percent(atoi(buf + 11), "serial");
      } else if (strcmp(buf, "theme") == 0) {
        Serial.printf(
            "THEME %s %s\n", ui_theme_id(), ui_theme_name());
      } else if (strcmp(buf, "theme_list") == 0) {
        for (size_t i = 0; i < theme_registry_count(); ++i) {
          const ThemePack* theme = theme_registry_at(i);
          if (theme) {
            Serial.printf(
                "THEME_ITEM %s %s%s\n", theme->id, theme->display_name,
                strcmp(theme->id, ui_theme_id()) == 0 ? " *" : "");
          }
        }
      } else if (strcmp(buf, "theme_next") == 0) {
        ui_next_theme(1, true);
      } else if (strcmp(buf, "theme_prev") == 0) {
        ui_next_theme(-1, true);
      } else if (strncmp(buf, "theme ", 6) == 0) {
        Serial.println(
            ui_set_theme(buf + 6, true) ? "THEME_OK" : "THEME_INVALID");
      } else if (strcmp(buf, "settings_open") == 0) {
        if (!ui_settings_visible()) ui_middle_short_press();
      } else if (strcmp(buf, "settings_close") == 0) {
        ui_close_settings();
      } else if (strcmp(buf, "settings_state") == 0) {
        const DeviceSettings& settings = device_settings_get();
        Serial.printf(
            "SETTINGS theme=%s preferred=%s bright=%u volume=%u auto=%d "
            "interval=%u screen=%d\n",
            ui_theme_id(), settings.theme_id,
            settings.brightness_percent, settings.volume_percent,
            settings.auto_theme_enabled ? 1 : 0,
            settings.auto_theme_interval_minutes,
            screen_on ? 1 : 0);
      } else if (strcmp(buf, "auto_theme on") == 0) {
        ui_set_auto_theme(true);
        Serial.println("AUTO_THEME ON");
      } else if (strcmp(buf, "auto_theme off") == 0) {
        ui_set_auto_theme(false);
        Serial.println("AUTO_THEME OFF");
      } else if (strncmp(buf, "theme_interval ", 15) == 0) {
        int minutes = 0;
        if (parse_int_arg(buf + 15, &minutes) &&
            minutes >= CODEXMETER_THEME_AUTO_MIN_MINUTES &&
            minutes <= CODEXMETER_THEME_AUTO_MAX_MINUTES) {
          ui_set_auto_theme_interval(static_cast<uint16_t>(minutes));
          Serial.printf(
              "THEME_INTERVAL %u\n", ui_auto_theme_interval());
        } else {
          Serial.println("THEME_INTERVAL_INVALID");
        }
      } else if (strncmp(buf, "volume ", 7) == 0) {
        int volume = 0;
        if (parse_int_arg(buf + 7, &volume)) {
          ui_set_volume(volume);
          Serial.printf("VOLUME %d\n", ui_volume());
        } else {
          Serial.println("VOLUME_INVALID");
        }
      } else if (strcmp(buf, "imu") == 0) {
        imu_print_status(Serial);
      } else if (strcmp(buf, "identity") == 0) {
        companion_protocol.identity(companion::Endpoint::Usb);
        Serial.print("IDENTITY ");
        Serial.println(identity_json());
      } else if (strcmp(buf, "heap") == 0) {
        device_log_heap("serial");
      } else if (strcmp(buf, "lvheap") == 0) {
        log_lvgl_mem("serial");
      } else if (strcmp(buf, "health") == 0) {
        uint32_t now = millis();
        uint32_t host_age =
            last_host_payload_ms == 0 ? 0 : now - last_host_payload_ms;
        uint32_t usage_age = last_usage_ms == 0 ? 0 : now - last_usage_ms;
        Serial.printf(
            "HEALTH screen=%d ble=%d host_age_ms=%lu usage_age_ms=%lu wdt=%d waiting=%d\n",
            screen_on ? 1 : 0, ble_service_connected() ? 1 : 0,
            (unsigned long)host_age, (unsigned long)usage_age,
            watchdog_enabled ? 1 : 0, ui_is_waiting() ? 1 : 0);
      } else if (strcmp(buf, "rotate auto") == 0) {
        imu_set_auto_rotation(true);
      } else if (strncmp(buf, "rotate ", 7) == 0) {
        int degrees = 0;
        int quadrant = -1;
        if (parse_int_arg(buf + 7, &degrees)) {
          if (degrees >= 0 && degrees <= 3) {
            quadrant = degrees;
          } else if (degrees == 90) {
            quadrant = 1;
          } else if (degrees == 180) {
            quadrant = 2;
          } else if (degrees == 270) {
            quadrant = 3;
          }
        }
        if (quadrant >= 0 && imu_set_rotation_quadrant((uint8_t)quadrant)) {
          Serial.printf("ROTATION %d\n", quadrant);
        } else {
          Serial.println("ROTATION_INVALID");
        }
      } else if (strcmp(buf, "screenshot") == 0) {
        send_screenshot();
      } else if (strncmp(buf, "logs", 4) == 0 && (buf[4] == '\0' || buf[4] == ' ')) {
        size_t limit = 0;
        if (buf[4] == ' ') {
          limit = (size_t)strtoul(buf + 5, nullptr, 10);
        }
        device_log_dump(Serial, limit);
      } else if (strcmp(buf, "log_clear") == 0) {
        device_log_clear();
        Serial.println("LOGS_CLEARED");
      }
}

static char usb_tx[641];
static size_t usb_tx_size = 0, usb_tx_pos = 0;
static uint32_t usb_tx_started = 0;
static bool usb_tx_boundary = false;
static uint32_t usb_rx_frames=0,usb_tx_abandoned=0,usb_tx_wait_loops=0,usb_tx_ring_bytes=0;
static void queue_usb_reply(const char* text, const char* prefix = "") {
  if (!text || !*text || usb_tx_size) return;
  int n = snprintf(usb_tx,sizeof(usb_tx),"%s%s%s\n",usb_tx_boundary ? "\n" : "",prefix,text);
  if (n <= 0 || size_t(n) >= sizeof(usb_tx)) return;
  usb_tx_boundary = false; usb_tx_size = n; usb_tx_pos = 0; usb_tx_started = millis();
}
static void service_usb_tx() {
#if ARDUINO_USB_MODE == 1 && SOC_USB_SERIAL_JTAG_SUPPORTED
  // Pinned Arduino3.3.8 HWCDC::availableForWrite() only observes free ring
  // space. A full ring can otherwise prevent reaching write(), which normally
  // arms IN_EMPTY. Kick the existing ISR without writing beyond capacity,
  // waiting, flushing queued bytes, or interpreting USB presence as ownership.
  if(HWCDC::isPlugged()) {
    usb_serial_jtag_ll_txfifo_flush();
    usb_serial_jtag_ll_ena_intr_mask(USB_SERIAL_JTAG_INTR_SERIAL_IN_EMPTY);
  }
#endif
  // Pump even after the final bytes entered the driver's ring: queued bytes
  // are not evidence that the host has received them.
  if (!usb_tx_size) return;
  if (millis()-usb_tx_started >= 500) {
    ++usb_tx_abandoned;
    device_logf("WARN","USB reply abandoned sent=%u length=%u free=%d",
      (unsigned)usb_tx_pos,(unsigned)usb_tx_size,Serial.availableForWrite());
    usb_tx_boundary = usb_tx_pos != 0; usb_tx_size = usb_tx_pos = 0; return;
  }
  size_t available = Serial.availableForWrite();
  if(!available)++usb_tx_wait_loops;
  size_t chunk = usb_tx_size-usb_tx_pos;
  if (chunk > 64) chunk = 64;
  if (chunk > available) chunk = available;
  if (chunk) {
    size_t queued=Serial.write(reinterpret_cast<const uint8_t*>(usb_tx)+usb_tx_pos,chunk);
    usb_tx_pos+=queued;usb_tx_ring_bytes+=queued;
  }
  if (usb_tx_pos == usb_tx_size) usb_tx_size = usb_tx_pos = 0;
}
static void handle_serial() {
  static companion::LineDecoder decoder;
  decoder.tick(millis());
  service_usb_tx();
  if (usb_tx_size) return;
  for (unsigned budget=0; budget<128 && Serial.available(); ++budget) {
    if (!decoder.push(uint8_t(Serial.read()),millis())) continue;
    ++usb_rx_frames;
    const char* line = decoder.data();
    if (!strcmp(line,"identity")) {
      companion_protocol.identity(companion::Endpoint::Usb);
      queue_usb_reply(identity_json(),"IDENTITY ");
    } else if (!strncmp(line,"CM1 ",4)) {
      queue_usb_reply(companion_protocol.dispatch(companion::Endpoint::Usb,line,decoder.size(),millis()));
    } else if (!strcmp(line,"health")) {
      char health[224];uint32_t now=millis();
      snprintf(health,sizeof(health),"HEALTH screen=%d ble=%d host_age_ms=%lu usage_age_ms=%lu wdt=%d waiting=%d usb_frames=%lu tx_abandon=%lu tx_wait=%lu tx_queued=%lu",
        screen_on?1:0,ble_service_connected()?1:0,
        (unsigned long)(last_host_payload_ms?now-last_host_payload_ms:0),
        (unsigned long)(last_usage_ms?now-last_usage_ms:0),watchdog_enabled?1:0,ui_is_waiting()?1:0,
        (unsigned long)usb_rx_frames,(unsigned long)usb_tx_abandoned,(unsigned long)usb_tx_wait_loops,(unsigned long)usb_tx_ring_bytes);
      queue_usb_reply(health);
    } else if (companion_protocol.raw_allowed() &&
        (companion_protocol.session.owner==companion::Endpoint::None ||
         companion_protocol.session.owner==companion::Endpoint::Maintenance ||
         !strncmp(line,"logs",4) || !strcmp(line,"screenshot") || !strcmp(line,"heap") || !strcmp(line,"lvheap"))) {
      // Raw binary diagnostics have an exclusive synchronous writer. Application
      // USB leases prohibit them; the bounded protocol writer is empty here.
      Serial.setTxTimeoutMs(100);
      handle_raw_line(line);
      Serial.setTxTimeoutMs(0);
      device_log_serial_enabled(false);
      // Diagnostics use their legacy writer; terminate any partial diagnostic
      // output before the next bounded protocol/identity reply.
      usb_tx_boundary=true;
    }
    break;
  }
}

static GpioButtonEvent take_gpio_button_event(GpioButtonState* button) {
  uint32_t now = millis();
  bool down = digitalRead(button->pin) == LOW;
  if (down != button->raw_down) {
    button->raw_down = down;
    button->raw_changed_ms = now;
  }

  if (button->raw_down != button->stable_down &&
      now - button->raw_changed_ms >= CODEXMETER_BUTTON_DEBOUNCE_MS) {
    button->stable_down = button->raw_down;
    if (button->stable_down) {
      button->pressed_ms = now;
      button->long_press_sent = false;
    } else if (!button->long_press_sent) {
      return GpioButtonEvent::ShortPress;
    }
  }

  if (button->raw_down && button->stable_down &&
      !button->long_press_sent &&
      now - button->pressed_ms >= CODEXMETER_BUTTON_LONG_PRESS_MS) {
    button->long_press_sent = true;
    return GpioButtonEvent::LongPress;
  }
  return GpioButtonEvent::None;
}

static void handle_button() {
#ifdef CODEXMETER_BOARD_BALL
  static bool was_down = false;
  static uint32_t pressed = 0;
  bool down = digitalRead(0) == LOW;
  if (down && !was_down) pressed = millis();
  if (!down && was_down && millis()-pressed >= 50 && millis()-pressed <= 800 && screen_on) {
    if (ui_alert_visible()) ui_dismiss_alert();
    else ui_touch_gesture(-120, 0, 120, 120, false);
  }
  was_down = down;
  return;
#else
  static GpioButtonState left = {
      CODEXMETER_BUTTON_LEFT_PIN, false, false, false, 0, 0};
  static GpioButtonState right = {
      CODEXMETER_BUTTON_RIGHT_PIN, false, false, false, 0, 0};

  if (screen_on) {
    GpioButtonEvent left_event = take_gpio_button_event(&left);
    if (left_event == GpioButtonEvent::LongPress &&
        !ui_settings_visible() && !ui_alert_visible()) {
      bool switched = ui_next_theme(-1, true);
      device_logf(
          "INFO", "left key long press theme previous result=%d",
          switched ? 1 : 0);
    } else if (left_event == GpioButtonEvent::ShortPress) {
      if (ui_settings_visible()) {
        ui_settings_move(-1);
      } else {
        adjust_brightness(-CODEXMETER_BRIGHTNESS_STEP, "left");
      }
    }

    GpioButtonEvent right_event = take_gpio_button_event(&right);
    if (right_event == GpioButtonEvent::LongPress &&
        !ui_settings_visible() && !ui_alert_visible()) {
      bool switched = ui_next_theme(1, true);
      device_logf(
          "INFO", "right key long press theme next result=%d",
          switched ? 1 : 0);
    } else if (right_event == GpioButtonEvent::ShortPress) {
      if (ui_settings_visible()) {
        ui_settings_move(1);
      } else {
        adjust_brightness(CODEXMETER_BRIGHTNESS_STEP, "right");
      }
    }
  }

  PowerKeyEvent power_event = power_take_key_event();
  if (power_event == PowerKeyEvent::LongPress) {
    toggle_screen("button_hold");
  } else if (
      power_event == PowerKeyEvent::ShortPress && screen_on) {
    ui_middle_short_press();
  }
#endif
}

static void handle_ble_screen_policy() {
  if (serial_ui_test_ms && millis() - serial_ui_test_ms < 120000) return;
  // A BLE link alone is not proof that the companion is supplying data.
  // Keep the boot screen until the first valid data payload, and return to it
  // on disconnection or a silent/stalled host. Never override manual power-off.
  if (!companion_protocol.session.live() || last_host_payload_ms == 0 ||
      millis() - last_host_payload_ms >= CODEXMETER_HOST_STALE_SCREEN_AFTER_MS) {
    ui_set_waiting(true);
  }
}

static const char* apply_companion_payload(const char*,const char*);
static void owner_changed(companion::Endpoint,companion::Endpoint,bool);
static companion::DisplayState current_display_state() {
  static companion::DisplayState previous;
  static bool initialized=false;
  companion::DisplayState state;
  state.page=ui_page(); state.brightness=brightness_percent;
  state.rotation=imu_rotation_quadrant()*90; state.auto_rotation=imu_auto_rotation_enabled();
  state.manual_on=manual_screen_on; state.policy_on=policy_screen_on; state.screen_on=screen_on;
  if (initialized && (state.page!=previous.page || state.brightness!=previous.brightness ||
      state.rotation!=previous.rotation || state.auto_rotation!=previous.auto_rotation || state.manual_on!=previous.manual_on)) {
    ++settings_revision;
    if(!settings_revision) {
      // Fence and renegotiate without resetting hardware or physical settings.
      identity_new_boot_generation();settings_revision=1;alert_ledger=companion::AlertLedger{};
      companion_protocol.init(identity_boot(),{current_display_state,apply_companion_payload,owner_changed});
      ble_service_identity_changed();last_host_payload_ms=0;ui_set_waiting(true);
    }
  }
  state.rev=settings_revision; previous=state; initialized=true; return state;
}
static const char* apply_companion_payload(const char* json,const char* revision) {
  current_display_state();
  const char* error=handle_json(json,revision);
  if(!error)current_display_state();
  return error;
}
static void owner_changed(companion::Endpoint before,companion::Endpoint after,bool same_host) {
  bool takeover=after==companion::Endpoint::Usb || after==companion::Endpoint::Maintenance;
  if(takeover || after==companion::Endpoint::None)
    ble_service_fence(after==companion::Endpoint::Usb ? "busy_usb" :
      after==companion::Endpoint::Maintenance ? "busy_maintenance" : nullptr);
  // Same-host maintenance freezes application writes, not the current visible frame.
  // Keep the ORIGINAL receive timestamp: the normal stale deadline still applies.
  if (companion::preserve_maintenance_telemetry(before, after, same_host)) return;
  // Data belongs to an active owner; claims/pings never fabricate freshness.
  last_host_payload_ms=0;
  if(!same_host || after==companion::Endpoint::None) {
    usage=UsageModel{};activity=ActivityModel{};
    ui_update_usage(usage);ui_update_activity(activity);
  }
  ui_set_waiting(true);
  (void)before;
}

void setup() {
  Serial.setRxBufferSize(1024);
  Serial.begin(115200);
  Serial.setTxTimeoutMs(0);
  delay(300);
  identity_init();
  companion_protocol.init(identity_boot(),{current_display_state,apply_companion_payload,owner_changed});
  Serial.printf("{\"ready\":true,\"device\":\"CodexMeter\",\"identity\":%s}\n",
                identity_json());
  device_logf("INFO", "device ready %s", identity_ble_name());
  esp_reset_reason_t reset_reason = esp_reset_reason();
  device_logf(
      "INFO", "reset reason=%d %s", (int)reset_reason,
      reset_reason_label(reset_reason));
  init_watchdog();
  device_log_heap("setup_start");

  pinMode(CODEXMETER_BUTTON_LEFT_PIN, INPUT_PULLUP);
  pinMode(CODEXMETER_BUTTON_RIGHT_PIN, INPUT_PULLUP);
  device_settings_init();
  brightness_percent = device_settings_get().brightness_percent;
  power_init();
  imu_init();
  display_init();
  UiSystemHooks ui_hooks{};
  ui_hooks.apply_brightness = settings_apply_brightness;
  ui_init(ui_hooks);
  touch_input_init();
  ui_set_display_active(true);
  refresh_battery_ui(true);
  ble_service_init();
  ble_service_request_refresh();
  device_log_heap("setup_done");
  device_logf("INFO", "setup complete");
  device_log_serial_enabled(false);
}

void loop() {
  static uint32_t lv_slow_count = 0;
  static uint32_t last_lv_slow_log_ms = 0;
  static uint32_t last_background_policy_ms = 0;

  if (screen_on) {
    uint32_t lv_start_ms = millis();
    lv_timer_handler();
    uint32_t lv_elapsed_ms = millis() - lv_start_ms;
#if CODEXMETER_LVGL_SLOW_FRAME_MS > 0
    if (lv_elapsed_ms >= CODEXMETER_LVGL_SLOW_FRAME_MS) {
      lv_slow_count++;
      uint32_t now = millis();
      if (now - last_lv_slow_log_ms >= 250) {
        last_lv_slow_log_ms = now;
        device_logf(
            "WARN", "lv_timer slow ms=%lu count=%lu",
            (unsigned long)lv_elapsed_ms, (unsigned long)lv_slow_count);
      }
    }
#endif
    ui_tick();
  }
  device_settings_tick();
  power_tick();
  if (power_take_state_changed()) refresh_battery_ui(false);
  ble_service_tick();
  handle_button();
  touch_input_tick(screen_on);
  ble_service_lock();
  current_display_state();
  companion_protocol.tick(millis());
  static uint32_t observed_ble_epoch=0;
  uint32_t ble_epoch=ble_service_epoch();
  if(ble_epoch!=observed_ble_epoch) {
    observed_ble_epoch=ble_epoch;
    // Epoch changes also fence queued events. USB takeover must not clear USB.
    companion_protocol.disconnected();
  }
  if(ble_service_take_identity_read())companion_protocol.identity(companion::Endpoint::Ble);
  handle_serial();
  if (screen_on) handle_orientation();

  uint8_t drained_payloads = 0;
  while (drained_payloads < CODEXMETER_BLE_RX_DRAIN_MAX &&
         ble_service_has_data() && ble_service_can_dispatch()) {
    const char* message=ble_service_take_data();
    if(ble_service_data_current()) {
      if(!strncmp(message,"CM1 ",4))
        ble_service_reply(companion_protocol.dispatch(companion::Endpoint::Ble,message,strlen(message),millis()));
      else if(companion_protocol.legacy_allowed()) {
        const char* error=handle_json(message,nullptr);
        if(!error) { companion_protocol.legacy_accepted(millis());ble_service_ack(); }
        else ble_service_nack();
      }
    }
    drained_payloads++;
  }
  ble_service_unlock();

  const uint32_t now = millis();
  if (now - last_background_policy_ms >=
      CODEXMETER_BACKGROUND_POLICY_POLL_MS) {
    last_background_policy_ms = now;
    handle_ble_screen_policy();
    if (usage.valid && now - last_usage_ms > CODEXMETER_STALE_AFTER_MS) {
      strlcpy(usage.status, "stale", sizeof(usage.status));
      ui_update_usage(usage);
      last_usage_ms = now;
      device_logf("WARN", "usage stale");
    }
  }

  feed_watchdog();
  delay(screen_on ? CODEXMETER_MAIN_LOOP_ACTIVE_DELAY_MS
                  : CODEXMETER_MAIN_LOOP_INACTIVE_DELAY_MS);
}
