#include "model.h"

#include <ArduinoJson.h>

#include "device_log.h"
#include "serial_protocol.h"
#include "wire_json.h"

static void copy_text(char* dst, size_t dst_size, const char* src) {
  if (!src) src = "";
  strlcpy(dst, src, dst_size);
}
static bool bounded_text(JsonVariantConst value,size_t bytes,size_t characters) {
  if(!json_cstring(value))return false;
  const char* text=value.as<const char*>();size_t n=strlen(text),count=0;
  if(n>bytes || !companion::valid_utf8(text,n,true))return false;
  for(size_t i=0;i<n;++i)if((uint8_t(text[i])&0xc0)!=0x80)++count;
  return count<=characters;
}

PayloadKind parse_payload(
    const char* json,
    UsageModel* usage,
    AlertModel* alert,
    ActivityModel* activity,
    ControlModel* control) {
  size_t bytes = strlen(json);
  if (bytes > 512 || !companion::valid_utf8(json, bytes)) return PAYLOAD_NONE;
  BoundedJsonAllocator allocator;
  JsonDocument doc(&allocator);
  if (!exact_json(doc,json,bytes)) {
    device_logf("ERROR", "JSON parse error");
    return PAYLOAD_NONE;
  }

  if (!doc.is<JsonObject>() || !doc["v"].is<int>() || doc["v"].as<int>() != 1 ||
      !doc["k"].is<const char*>() || !doc["t"].is<uint32_t>()) return PAYLOAD_NONE;
  const char* kind = doc["k"] | "";
  for(JsonPair pair:doc.as<JsonObject>())if(pair.key().size()!=strlen(pair.key().c_str()))return PAYLOAD_NONE;
  const char* unsigned_fields[] = {"h5r","d7r","td","t7","run","wait","done"};
  for (const char* key : unsigned_fields)
    if (!doc[key].isNull() && !doc[key].is<uint64_t>()) return PAYLOAD_NONE;
  for(const char* key : {"run","wait","done"})
    if(!doc[key].isNull() && !doc[key].is<int>())return PAYLOAD_NONE;
  for(const char* key : {"k","src","st","id","title","body","cmd","why"})
    if(!doc[key].isNull() && !json_cstring(doc[key]))return PAYLOAD_NONE;
  if(!doc["chats"].isNull() && !doc["chats"].is<bool>())return PAYLOAD_NONE;
  if(!doc["st"].isNull() && strlen(doc["st"].as<const char*>())>=sizeof(usage->status))return PAYLOAD_NONE;
  if(!doc["src"].isNull() && !bounded_text(doc["src"],32,32))return PAYLOAD_NONE;
  if(!doc["why"].isNull() && !bounded_text(doc["why"],31,31))return PAYLOAD_NONE;
  for (const char* key : {"h5", "d7"}) {
    if (!doc[key].isNull() && (!doc[key].is<int>() || doc[key].as<int>() < -1 || doc[key].as<int>() > 100)) return PAYLOAD_NONE;
  }
  for (const char* key : {"b0", "b7"}) {
    if (doc[key].isNull()) continue;
    if (!doc[key].is<JsonArray>() || doc[key].size() != 8) return PAYLOAD_NONE;
    for (JsonVariant value : doc[key].as<JsonArray>()) if (!value.is<uint64_t>()) return PAYLOAD_NONE;
  }
  if ((!strcmp(kind,"usage") || !strcmp(kind,"activity")) && !doc["src"].is<const char*>()) return PAYLOAD_NONE;
  if (!strcmp(kind,"activity") && !doc["run"].isNull() && !doc["run"].is<int>()) return PAYLOAD_NONE;
  if (!strcmp(kind,"alert")) {
    if (!doc["id"].is<const char*>() || !companion::lower_hex(doc["id"],12) ||
        !doc["title"].is<const char*>() || !doc["body"].is<const char*>() ||
        !bounded_text(doc["title"],47,16) || !bounded_text(doc["body"],210,64)) return PAYLOAD_NONE;
  }
  if (strcmp(kind, "usage") == 0) {
    usage->valid = true;
    for (int w = 0; w < 2; ++w) {
      usage->breakdown[w] = TokenBreakdown{};
      JsonArray values = doc[w == 0 ? "b0" : "b7"].as<JsonArray>();
      bool valid = values.size() == 8;
      for (int i = 0; valid && i < 8; ++i) valid = values[i].is<uint64_t>();
      if (valid) {
        auto& detail = usage->breakdown[w];
        detail.valid = true;
        for (int i = 0; i < 3; ++i) {
          detail.tokens[i] = values[i].as<uint64_t>();
          detail.cents[i] = values[i + 3].as<uint64_t>();
        }
        detail.partial = values[6].as<int>() != 0;
        detail.unknown = values[7].as<int>() != 0;
      }
    }
    usage->h5_remaining = doc["h5"] | -1;
    usage->h5_reset = doc["h5r"] | 0L;
    usage->d7_remaining = doc["d7"] | -1;
    usage->d7_reset = doc["d7r"] | 0L;
    JsonVariant today_tokens = doc["td"];
    usage->has_today_tokens =
        !today_tokens.isNull() && today_tokens.is<uint64_t>();
    usage->today_tokens =
        usage->has_today_tokens ? today_tokens.as<uint64_t>() : 0;
    JsonVariant last_7d_tokens = doc["t7"];
    usage->has_last_7d_tokens =
        !last_7d_tokens.isNull() && last_7d_tokens.is<uint64_t>();
    usage->last_7d_tokens =
        usage->has_last_7d_tokens ? last_7d_tokens.as<uint64_t>() : 0;
    usage->updated_at = doc["t"] | 0L;
    usage->received_ms = millis();
    copy_text(usage->status, sizeof(usage->status), doc["st"] | "ok");
    return PAYLOAD_USAGE;
  }

  if (strcmp(kind, "alert") == 0) {
    alert->valid = true;
    alert->has_running_count = false;
    alert->running_count = 0;
    copy_text(alert->id, sizeof(alert->id), doc["id"] | "");
    copy_text(alert->title, sizeof(alert->title), doc["title"] | "Task complete!");
    copy_text(alert->body, sizeof(alert->body), doc["body"] | "Codex task completed");
    alert->received_at = doc["t"] | 0L;
    JsonVariant run = doc["run"];
    if (!run.isNull()) {
      alert->has_running_count = true;
      alert->running_count = run | 0;
      if (alert->running_count < 0) alert->running_count = 0;
    }
    return PAYLOAD_ALERT;
  }

  if (strcmp(kind, "activity") == 0) {
    activity->valid = true;
    activity->running_count = doc["run"] | -1;
    activity->waiting_count = doc["wait"] | -1;
    activity->done_count = doc["done"] | -1;
    activity->chat_counts_valid = doc["chats"] | false;
    activity->received_ms = millis();
    activity->updated_at = doc["t"] | 0L;
    return PAYLOAD_ACTIVITY;
  }

  if (strcmp(kind, "control") == 0) {
    const char* command = doc["cmd"] | "";
    if ((strcmp(command, "brightness") == 0 || strcmp(command, "rotation") == 0) && doc["value"].is<int>()) {
      int value = doc["value"].as<int>();
      if ((strcmp(command,"brightness")==0 && value>=10 && value<=100) ||
          (strcmp(command,"rotation")==0 && (value==0 || value==90 || value==180 || value==270))) {
        control->valid=true; control->value=value;
        copy_text(control->command,sizeof(control->command),command);
        return PAYLOAD_CONTROL;
      }
      return PAYLOAD_NONE;
    }
    if (strcmp(command, "screen") == 0) {
      if (!doc["on"].is<bool>() || (!doc["why"].isNull() && !doc["why"].is<const char*>())) return PAYLOAD_NONE;
      control->valid = true;
      control->screen_on = doc["on"] | true;
      control->updated_at = doc["t"] | 0L;
      copy_text(control->command, sizeof(control->command), command);
      copy_text(control->reason, sizeof(control->reason), doc["why"] | "control");
      return PAYLOAD_CONTROL;
    }
    device_logf("WARN", "Unknown control command");
    return PAYLOAD_NONE;
  }

  device_logf("WARN", "Unknown payload kind");
  return PAYLOAD_NONE;
}

void usage_apply_demo(UsageModel* usage) {
  long now = time(nullptr);
  if (now < 1000) now = 1783070000;
  usage->valid = true;
  usage->h5_remaining = 72;
  usage->h5_reset = now + 73 * 60;
  usage->d7_remaining = 84;
  usage->d7_reset = now + 3 * 24 * 60 * 60;
  usage->has_today_tokens = false;
  usage->today_tokens = 0;
  usage->has_last_7d_tokens = false;
  usage->last_7d_tokens = 0;
  usage->updated_at = now;
  usage->received_ms = millis();
  copy_text(usage->status, sizeof(usage->status), "ok");
}

void usage_apply_token_demo(UsageModel* usage) {
  long now = time(nullptr);
  if (now < 1000) now = 1783070000;
  usage->valid = true;
  usage->h5_remaining = -1;
  usage->h5_reset = 0;
  usage->d7_remaining = 97;
  usage->d7_reset = now + 6 * 24 * 60 * 60;
  usage->has_today_tokens = true;
  usage->today_tokens = 18600000ULL;
  usage->has_last_7d_tokens = true;
  usage->last_7d_tokens = 236000000ULL;
  usage->updated_at = now;
  usage->received_ms = millis();
  copy_text(usage->status, sizeof(usage->status), "ok");
}

void alert_apply_demo(AlertModel* alert) {
  long now = time(nullptr);
  if (now < 1000) now = 1783070000;
  alert->valid = true;
  alert->has_running_count = false;
  alert->running_count = 0;
  copy_text(alert->id, sizeof(alert->id), "demo");
  copy_text(alert->title, sizeof(alert->title), "Task complete!");
  copy_text(alert->body, sizeof(alert->body), "CodexMeter display test: ready.");
  alert->received_at = now;
}

void activity_apply_demo(ActivityModel* activity, int running_count) {
  activity->chat_counts_valid = false;
  long now = time(nullptr);
  if (now < 1000) now = 1783070000;
  activity->valid = true;
  activity->running_count = running_count < 0 ? 0 : running_count;
  activity->updated_at = now;
}
