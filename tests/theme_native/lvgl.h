#pragma once
struct lv_font_t { int id; };
struct lv_obj_t { const char* text; int writes; };
inline const char* lv_label_get_text(lv_obj_t* label) { return label->text; }
inline void lv_label_set_text(lv_obj_t* label, const char* text) { label->text = text; ++label->writes; }
