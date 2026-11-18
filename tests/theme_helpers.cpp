#include <cassert>
#include "theme_label_helpers.h"
int main() {
  lv_obj_t label{"same", 0};
  assert(!set_label_text_if_changed(&label, "same") && label.writes == 0);
  assert(set_label_text_if_changed(&label, "changed") && label.writes == 1);
  label.text = nullptr;
  assert(set_label_text_if_changed(&label, "") && label.writes == 2);
  lv_font_t preferred{1}, fallback{2};
  assert(font_or(&preferred, &fallback) == &preferred);
  assert(font_or(nullptr, &fallback) == &fallback);
  assert(font_or(nullptr, nullptr) == nullptr);
}
