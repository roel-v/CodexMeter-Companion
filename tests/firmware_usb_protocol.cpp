// Build against the actual firmware core and the pinned ArduinoJson headers.
#include "companion_protocol.h"
#include "wire_json.h"
#include "model.h"
#include "token_view_model.h"
#include "dashboard_view_model.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <string>
#include <vector>
using namespace companion;
static int effects=0, fences=0;
static DisplayState display;
void device_logf(const char*,const char*,...) {}
static DisplayState state(){return display;}
static const char* apply(const char* json,const char*) {
  BoundedJsonAllocator allocator;JsonDocument doc(&allocator);
  if(!exact_json(doc,json,strlen(json)))return "bad_request";
  if(doc["reject"]==true)return "unsupported";
  ++effects;return nullptr;
}
static void fence(Endpoint,Endpoint,bool){++fences;}
static const char* B="0011223344556677";
static const char* H="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
static const char* T="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
static std::string control(const char* op,uint32_t q=1,const char* token=T,bool host=false) {
  return std::string("CM1 {\"op\":\"")+op+"\",\"q\":"+std::to_string(q)+",\"boot\":\""+B+"\",\"token\":\""+token+"\""+(host?std::string(",\"host\":\"")+H+"\"":"")+"}";
}
static std::string data(uint32_t seq,const char* payload="{\"v\":1}",const char* revision="-") {
  return std::string("CM1 DATA ")+B+" "+T+" "+std::to_string(seq)+" "+revision+" "+payload;
}
static std::string dispatch(Protocol& p,const std::string& s,uint32_t at=100,Endpoint endpoint=Endpoint::Usb) {
  return p.dispatch(endpoint,s.c_str(),s.size(),at);
}
static void contains(const std::string& s,const char* expected){if(s.find(expected)==std::string::npos){fprintf(stderr,"Expected %s, got %s\n",expected,s.c_str());abort();}}
int main() {
  {
    UsageModel usage; ActivityModel activity;
    activity.valid=true; activity.running_count=2; activity.received_ms=100;
    auto view=build_dashboard_view_model(usage,activity,-1,false,101);
    assert(view.running_count==2 && view.waiting_count==-1 && view.done_count==-1);
    activity.chat_counts_valid=true;activity.waiting_count=3;activity.done_count=-1;
    view=build_dashboard_view_model(usage,activity,-1,false,101);
    assert(view.running_count==2 && view.waiting_count==3 && view.done_count==-1);
    view=build_dashboard_view_model(usage,activity,-1,false,15100);
    assert(view.running_count==-1 && view.waiting_count==-1 && view.done_count==-1);
  }
  {
    TokenBreakdown b;
    auto total=token_display_row(b,3,true,123);
    assert(total.has_tokens && total.tokens==123 && !total.has_cost);
    assert(!token_display_row(b,0,true,123).has_tokens);
    b.valid=true;b.unknown=true;b.cents[0]=1;b.cents[1]=2;b.cents[2]=3;
    total=token_display_row(b,3,false,0);
    assert(!total.has_tokens && total.has_cost && total.cents==6 && total.partial);
    b.cents[0]=UINT64_MAX;
    assert(!token_display_row(b,3,true,123).has_cost);
    assert(token_display_row(b,0,true,123).has_cost);
  }


  {
    UsageModel usage; AlertModel alert; ActivityModel activity; ControlModel control;
    assert(parse_payload(R"({"v":1,"k":"activity","t":1,"src":"codex","run":null,"wait":null,"done":null,"chats":false})",
                         &usage,&alert,&activity,&control)==PAYLOAD_ACTIVITY);
    assert(activity.running_count==-1 && activity.waiting_count==-1 && activity.done_count==-1);
    assert(!activity.chat_counts_valid);
    assert(parse_payload(R"({"v":1,"k":"activity","t":1,"src":"codex","run":2,"wait":3,"done":null,"chats":true})",
                         &usage,&alert,&activity,&control)==PAYLOAD_ACTIVITY);
    assert(activity.chat_counts_valid && activity.running_count==2 && activity.waiting_count==3 && activity.done_count==-1);
  }

  // The production owner-change callback uses this exact decision before touching
  // telemetry or last_host_payload_ms. Maintenance is a live lease, not fresh data.
  assert(preserve_maintenance_telemetry(Endpoint::Usb,Endpoint::Maintenance,true));
  assert(preserve_maintenance_telemetry(Endpoint::Ble,Endpoint::Maintenance,true));
  assert(!preserve_maintenance_telemetry(Endpoint::Usb,Endpoint::Maintenance,false));
  assert(!preserve_maintenance_telemetry(Endpoint::None,Endpoint::Maintenance,true));
  assert(!preserve_maintenance_telemetry(Endpoint::LegacyBle,Endpoint::Maintenance,true));
  assert(!preserve_maintenance_telemetry(Endpoint::Maintenance,Endpoint::None,true));
  assert(!preserve_maintenance_telemetry(Endpoint::Maintenance,Endpoint::Usb,true));
  Session maintenance_test;
  assert(!maintenance_test.claim(Endpoint::Usb,H,T,100));
  assert(!maintenance_test.claim(Endpoint::Maintenance,H,T,101));
  assert(maintenance_test.live());
  assert(!maintenance_test.expire(120100));
  assert(maintenance_test.expire(120101));
  assert(!maintenance_test.live());

  for(bool legacy : {false,true}) {
    assert(screen_policy_reason("lock",legacy,false));assert(screen_policy_reason("unlock",legacy,true));
    assert(screen_policy_reason("mac_locked",legacy,false)==legacy);
    assert(screen_policy_reason("mac_unlocked",legacy,true)==legacy);
    assert(screen_policy_reason("ble_restored",legacy,true)==legacy);
    assert(!screen_policy_reason("ble_restored",legacy,false));
    assert(!screen_policy_reason("explicit",legacy,true));
  }
  const std::string line="CM1 {\"op\":\"ping\"}\r\n";
  for(size_t split=0;split<=line.size();++split) {
    LineDecoder decoder;int frames=0;
    for(size_t i=0;i<split;++i)frames+=decoder.push(line[i],10);
    for(size_t i=split;i<line.size();++i)frames+=decoder.push(line[i],11);
    assert(frames==1);assert(std::string(decoder.data())=="CM1 {\"op\":\"ping\"}");
  }
  { LineDecoder d;int frames=0;for(char c:std::string("\nA\nB\n"))frames+=d.push(c,0);assert(frames==2); }
  { LineDecoder d;for(int i=0;i<641;++i)assert(!d.push('x',0));assert(!d.push('\n',1));assert(!d.push('x',2));assert(d.push('\n',3)); }
  { LineDecoder d;d.push('x',0xffffff00);d.tick(0x00000300);for(char c:std::string("suffix\n"))assert(!d.push(c,0x301));d.push('x',0x302);assert(d.push('\n',0x303)); }
  { LineDecoder d;for(char c:std::string("a\rb\n"))assert(!d.push(c,0)); }
  assert(valid_utf8("R\xc3\xa9sum\xc3\xa9",8));assert(!valid_utf8("\xc0\xaf",2));assert(!valid_utf8("\xed\xa0\x80",3));
  uint32_t number=0;assert(decimal("4294967295",number));assert(!decimal("4294967296",number));assert(!decimal("01",number));
  { FragmentDecoder d;std::string logical(640,'x');size_t offset=0;while(offset<logical.size()) {
    size_t count=logical.size()-offset;if(count>15)count=15;
    std::vector<uint8_t> part={0x1e,2,128,uint8_t(offset>>8),uint8_t(offset)};
    part.insert(part.end(),logical.begin()+offset,logical.begin()+offset+count);
    bool completed=d.push(part.data(),part.size(),100);offset+=count;assert(completed==(offset==logical.size()));
    }assert(std::string(d.data())==logical);
    uint8_t gap[]={0x1e,0,10,0,2,'x'};assert(!d.push(gap,sizeof(gap),101));
    uint8_t start[]={0x1e,0,2,0,0,'x'},tail[]={0x1e,0,2,0,1,'y'};
    assert(!d.push(start,sizeof(start),0));assert(!d.push(tail,sizeof(tail),2000));assert(!d.push(tail,sizeof(tail),2001));
  }
  Protocol p;p.init(B,{state,apply,fence});p.identity(Endpoint::Usb);
  auto claim=control("claim",1,T,true);
  contains(dispatch(p,claim),"\"ok\":true");
  contains(dispatch(p,data(1)),"\"ok\":true");assert(effects==1);
  contains(dispatch(p,data(1)),"\"ok\":true");assert(effects==1);
  contains(dispatch(p,data(1,"{\"v\":1}","1")),"conflict");assert(effects==1);
  contains(dispatch(p,data(3)),"out_of_order");assert(effects==1);
  contains(dispatch(p,data(2,"{\"reject\":true}")),"unsupported");assert(effects==1);
  contains(dispatch(p,data(2,"{\"reject\":true}")),"unsupported");assert(effects==1);
  contains(dispatch(p,data(3)),"\"ok\":true");assert(effects==2);
  auto ping=control("ping",2);contains(dispatch(p,ping,6000),"\"ok\":true");
  p.tick(13000);assert(!p.session.live());contains(dispatch(p,data(4),13000),"stale_session");
  p.identity(Endpoint::Usb);contains(dispatch(p,claim,13001),"stale_session");
  const char* T2="cccccccccccccccccccccccccccccccc";
  auto claim2=control("claim",3,T2,true);contains(dispatch(p,claim2,13002),"\"ok\":true");
  contains(dispatch(p,control("release",4,T2),13003),"\"ok\":true");
  contains(dispatch(p,control("release",4,T2),13004),"\"ok\":true");
  p.legacy_accepted(13005);p.disconnected();
  contains(dispatch(p,control("release",4,T2),13006),"stale_session");
  for(const auto& malformed : {claim+"{}",claim+"garbage",std::string("CM1 {\"op\":\"claim\",\"op\":\"ping\",\"q\":9,\"boot\":\"")+B+"\",\"token\":\""+T+"\"}"}) {
    assert(dispatch(p,malformed,14000).empty() || dispatch(p,malformed,14000).find("bad_request")!=std::string::npos);
    assert(!p.session.live());
  }
  { BoundedJsonAllocator a;JsonDocument d(&a);assert(!exact_json(d,"{\"a\":1,\"a\":2}",13));assert(!exact_json(d,"{}{}",4)); }
  AlertLedger ledger;
  for(int i=0;i<32;++i){char id[13];snprintf(id,sizeof(id),"%012x",i);assert(ledger.accept(id,100)==0);}
  assert(ledger.accept("000000000000",200)==1);assert(ledger.accept("ffffffffffff",200)==-1);assert(ledger.accept("ffffffffffff",65100)==0);
  {
    UsageModel usage;AlertModel alert;ActivityModel activity;ControlModel control;
    const char* valid="{\"v\":1,\"k\":\"activity\",\"src\":\"codex\",\"run\":2,\"t\":1784000000}";
    assert(parse_payload(valid,&usage,&alert,&activity,&control)==PAYLOAD_ACTIVITY);assert(activity.running_count==2);
    for(const auto& invalid : {
      std::string(valid)+"{}",
      std::string("{\"v\":1,\"k\":\"activity\",\"src\":\"codex\",\"run\":2,\"run\":3,\"t\":1}"),
      std::string("{\"v\":1,\"k\":\"activity\",\"src\":\"codex\",\"run\":4294967295,\"t\":1}"),
      std::string("{\"v\":1,\"k\":\"activity\",\"src\":\"codex\",\"run\":2,\"chats\":1,\"t\":1}"),
      std::string("{\"v\":2,\"k\":\"activity\",\"src\":\"codex\",\"run\":2,\"t\":1}"),
      std::string("{\"v\":1,\"k\":\"control\",\"cmd\":\"screen\",\"on\":\"false\",\"t\":1}")}) {
      assert(parse_payload(invalid.c_str(),&usage,&alert,&activity,&control)==PAYLOAD_NONE);assert(activity.running_count==2);
    }
    std::string maximum=valid;maximum.append(512-maximum.size(),' ');
    assert(parse_payload(maximum.c_str(),&usage,&alert,&activity,&control)==PAYLOAD_ACTIVITY);
    maximum+=' ';assert(parse_payload(maximum.c_str(),&usage,&alert,&activity,&control)==PAYLOAD_NONE);
    std::string detailed="{\"v\":1,\"k\":\"usage\",\"src\":\"codex\",\"t\":1784000000,\"b0\":[18446744073709551615,2,3,4,5,6,0,0],\"b7\":[7,8,9,10,11,12,0,0]}";
    detailed.append(512-detailed.size(),' ');
    assert(parse_payload(detailed.c_str(),&usage,&alert,&activity,&control)==PAYLOAD_USAGE);
    assert(usage.breakdown[0].valid && usage.breakdown[0].tokens[0]==UINT64_MAX && usage.breakdown[1].cents[2]==12);
    std::string unicode="{\"v\":1,\"k\":\"alert\",\"id\":\"0123456789ab\",\"title\":\"";
    for(int i=0;i<16;++i)unicode+="\xc3\xa9";
    unicode+="\",\"body\":\"";for(int i=0;i<64;++i)unicode+="\xc3\xa9";
    unicode+="\",\"t\":1784000000}";unicode.append(512-unicode.size(),' ');
    assert(parse_payload(unicode.c_str(),&usage,&alert,&activity,&control)==PAYLOAD_ALERT);
    assert(strlen(alert.title)==32 && strlen(alert.body)==128);
    assert(parse_payload("{\"v\":1,\"k\":\"alert\",\"id\":\"0123456789ab\",\"title\":\"12345678901234567\",\"body\":\"\",\"t\":1}",&usage,&alert,&activity,&control)==PAYLOAD_NONE);
  }
  {
    Session s;assert(!s.claim(Endpoint::Ble,H,T,0xfffffff0));
    assert(!s.claim(Endpoint::Usb,H,T2,0xfffffff1));assert(s.same_host);
    assert(!strcmp(s.check(Endpoint::Ble,T,0xfffffff2),"busy_usb"));
    assert(!s.claim(Endpoint::Maintenance,H,T2,0xfffffff3));
    assert(!strcmp(s.check(Endpoint::Usb,T2,10),"busy_maintenance"));
    assert(!s.expire(119970));assert(s.expire(119987));
    const char* H2="dddddddddddddddddddddddddddddddd";
    assert(!s.claim(Endpoint::Usb,H2,T,120000));assert(!s.same_host);
  }
  {
    Protocol maximum;maximum.init(B,{state,apply,fence});maximum.identity(Endpoint::Usb);
    contains(dispatch(maximum,claim),"\"ok\":true");
    std::string body="{\"v\":1}";body.append(512-body.size(),' ');
    contains(dispatch(maximum,data(1,body.c_str())),"\"ok\":true");
    body+=' ';assert(dispatch(maximum,data(2,body.c_str())).empty());
  }
  {
    Protocol m;m.init(B,{state,apply,fence});m.identity(Endpoint::Usb);
    contains(dispatch(m,claim),"\"ok\":true");
    m.identity(Endpoint::Usb);
    contains(dispatch(m,control("claim",99,T2,true)),"busy_usb");
    contains(dispatch(m,claim),"\"ok\":true");
    contains(dispatch(m,control("maint",2,T,true)),"\"ok\":true");
    m.identity(Endpoint::Usb);
    contains(dispatch(m,control("maint",3,T2,true)),"busy_maintenance");
    contains(dispatch(m,control("maint",4,T,true),100000),"\"ok\":true");
    m.tick(219999);assert(m.session.owner==Endpoint::Maintenance);
    m.tick(220000);assert(!m.session.live());
  }
  {
    Protocol invalid;invalid.init(B,{state,apply,fence});invalid.identity(Endpoint::Usb);
    assert(dispatch(invalid,"CM2 {} ").empty());
    auto nul=control("claim",1,T,true);auto at=nul.find("claim");nul.replace(at,5,"claim\\u0000x");
    contains(dispatch(invalid,nul),"bad_request");assert(!invalid.session.live());
    auto wrong_boot=claim;wrong_boot.replace(wrong_boot.find(B),16,"ffffffffffffffff");
    contains(dispatch(invalid,wrong_boot),"bad_boot");assert(!invalid.session.live());
    contains(dispatch(invalid,control("unknown",7)),"bad_request");assert(!invalid.session.live());
    auto zero=control("claim",0,T,true);assert(dispatch(invalid,zero).empty());
  }
  {
    BoundedJsonAllocator allocator;void* aligned=allocator.allocate(16);
    assert(aligned && reinterpret_cast<uintptr_t>(aligned)%alignof(max_align_t)==0);allocator.deallocate(aligned);
    assert(!allocator.allocate(8193));
  }
  puts("firmware USB core/protocol tests passed");
}
