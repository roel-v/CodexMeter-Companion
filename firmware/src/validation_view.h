#pragma once
#include <ArduinoJson.h>
#include "dashboard_view_model.h"

// No chat text or credentials. Values come from the same UI inputs as the labels.
inline void print_validation_view(Print& out, const UsageModel& usage,
    const ActivityModel& activity, int page, bool waiting) {
  const auto view = build_dashboard_view_model(usage, activity, -1, false, millis());
  JsonDocument doc;
  doc["page"] = page;
  doc["waiting"] = waiting;
  doc["usage_t"] = usage.updated_at;
  doc["activity_t"] = activity.updated_at;
  doc["d7"] = view.d7_remaining;
  doc["run"] = view.running_count;
  doc["wait"] = view.waiting_count;
  doc["done"] = view.done_count;
  if (view.has_today_tokens) doc["td"] = view.today_tokens; else doc["td"] = nullptr;
  if (view.has_last_7d_tokens) doc["t7"] = view.last_7d_tokens; else doc["t7"] = nullptr;
  for (int w=0; w<2; ++w) {
    const char* key = w ? "b7" : "b0";
    const auto& b = view.breakdown[w];
    if (!b.valid) { doc[key] = nullptr; continue; }
    auto values = doc[key].to<JsonArray>();
    for (auto value : b.tokens) values.add(value);
    for (auto value : b.cents) values.add(value);
    values.add(b.partial ? 1 : 0); values.add(b.unknown ? 1 : 0);
  }
  out.print("VALIDATION "); serializeJson(doc, out); out.println();
}
