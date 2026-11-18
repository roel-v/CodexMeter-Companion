#pragma once
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <time.h>
class Stream;
inline uint32_t millis(){return 100;}
inline size_t strlcpy(char* out,const char* in,size_t capacity) {
  size_t length=strlen(in);
  if(capacity){size_t count=length<capacity-1?length:capacity-1;memcpy(out,in,count);out[count]=0;}
  return length;
}
