#pragma once
#include <lvgl.h>
#include <string.h>

inline const lv_font_t* font_or(const lv_font_t* preferred, const lv_font_t* fallback) {
  return preferred ? preferred : fallback;
}

inline bool set_label_text_if_changed(lv_obj_t* label, const char* text) {
  const char* current = lv_label_get_text(label);
  if (current && strcmp(current, text) == 0) return false;
  lv_label_set_text(label, text);
  return true;
}
