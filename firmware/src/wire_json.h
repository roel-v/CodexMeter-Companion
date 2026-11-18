#pragma once
#include <ArduinoJson.h>
#include <stdlib.h>
#include <stddef.h>
#include <string.h>
class BoundedJsonAllocator : public ArduinoJson::Allocator {
  size_t used_ = 0;
  struct alignas(max_align_t) Header { size_t size; };
 public:
  void* allocate(size_t size) override {
    if (size > 8192 - used_ || sizeof(Header)>8192-used_-size) return nullptr;
    auto* p = static_cast<Header*>(malloc(size + sizeof(Header)));
    if (!p) return nullptr;
    p->size = size; used_ += size+sizeof(Header); return p + 1;
  }
  void deallocate(void* ptr) override {
    if (!ptr) return;
    auto* p = static_cast<Header*>(ptr) - 1; used_ -= p->size+sizeof(Header); free(p);
  }
  void* reallocate(void* ptr, size_t size) override {
    if (!ptr) return allocate(size);
    auto* old = static_cast<Header*>(ptr) - 1;
    if (size > 8192 - (used_ - old->size)) return nullptr;
    size_t before = old->size;
    auto* next = static_cast<Header*>(realloc(old, size + sizeof(Header)));
    if (!next) return nullptr;
    used_ = used_ - before + size; next->size = size; return next + 1;
  }
};

// Deserialize once through a reader and verify all remaining bytes are JSON
// whitespace. ArduinoJson otherwise accepts a valid prefix followed by garbage.
class ExactJsonReader {
 public:
  const char* bytes; size_t size, position=0;
  ExactJsonReader(const char* b,size_t s):bytes(b),size(s){}
  int read() { return position<size ? uint8_t(bytes[position++]) : -1; }
  size_t readBytes(char* out,size_t n) {
    if(n>size-position)n=size-position;
    memcpy(out,bytes+position,n);position+=n;return n;
  }
};
inline bool exact_json(JsonDocument& doc,const char* input,size_t size) {
  ExactJsonReader reader(input,size);
  if(deserializeJson(doc,reader,ArduinoJson::DeserializationOption::NestingLimit(4)) || !doc.is<JsonObject>())return false;
  for(size_t i=reader.position;i<size;++i)if(input[i]!=' ' && input[i]!='\t' && input[i]!='\r' && input[i]!='\n')return false;
  // Compare every object's raw key count to parsed unique-key count. This
  // protocol uses one root object and scalar arrays, never nested objects.
  bool quoted=false,escaped=false;size_t keys=0;
  for(size_t i=0;i<size;++i) {
    char c=input[i];
    if(quoted) { if(escaped)escaped=false;else if(c=='\\')escaped=true;else if(c=='"')quoted=false; }
    else if(c=='"')quoted=true;else if(c==':')++keys;
  }
  return keys==doc.size();
}
inline bool json_cstring(JsonVariantConst value) {
  return value.is<const char*>() && value.as<JsonString>().size()==strlen(value.as<const char*>());
}
