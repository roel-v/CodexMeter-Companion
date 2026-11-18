#include "ble_service.h"

#include "config.h"
#include "device_log.h"
#include "identity.h"
#include "serial_protocol.h"

#include <NimBLEDevice.h>
#include <freertos/semphr.h>

#define SERVICE_UUID "4c41555a-4465-7669-6365-000000000001"
#define RX_CHAR_UUID "4c41555a-4465-7669-6365-000000000002"
#define TX_CHAR_UUID "4c41555a-4465-7669-6365-000000000003"
#define REQ_CHAR_UUID "4c41555a-4465-7669-6365-000000000004"
#define IDENTITY_CHAR_UUID "4c41555a-4465-7669-6365-000000000005"
static constexpr size_t RX_BUF_SIZE = companion::frame_limit + 1;
#define RX_QUEUE_SIZE 1

static NimBLEServer* server = nullptr;
static NimBLECharacteristic* tx_char = nullptr;
static NimBLECharacteristic* req_char = nullptr;
static NimBLECharacteristic* identity_char = nullptr;
static char rx_queue[RX_QUEUE_SIZE][RX_BUF_SIZE];
static char rx_current[RX_BUF_SIZE];
static uint8_t rx_head = 0;
static uint8_t rx_tail = 0;
static uint8_t rx_count = 0;
static portMUX_TYPE rx_mux = portMUX_INITIALIZER_UNLOCKED;
static volatile bool should_advertise = false;
static volatile bool connected = false;
static uint32_t connection_epoch = 1, physical_epoch = 1, queue_epoch[RX_QUEUE_SIZE], current_epoch = 0;
static uint16_t connection_handle = BLE_HS_CONN_HANDLE_NONE, connection_mtu = 23;
static companion::FragmentDecoder fragments;
static bool negotiated = false;
static bool identity_read = false;
static char pending_reply[companion::frame_limit + 1], pending_busy[160];
static size_t reply_size = 0, reply_offset = 0;
static uint32_t reply_started = 0;
static SemaphoreHandle_t dispatch_lock() {
  static StaticSemaphore_t storage;
  static SemaphoreHandle_t lock=xSemaphoreCreateRecursiveMutexStatic(&storage);
  return lock;
}
void ble_service_lock() { xSemaphoreTakeRecursive(dispatch_lock(),portMAX_DELAY); }
void ble_service_unlock() { xSemaphoreGiveRecursive(dispatch_lock()); }
struct DispatchGuard { DispatchGuard(){ble_service_lock();} ~DispatchGuard(){ble_service_unlock();} };

static void start_advertising() {
  NimBLEAdvertising* adv = NimBLEDevice::getAdvertising();
  adv->reset();
  adv->addServiceUUID(SERVICE_UUID);
  adv->enableScanResponse(true);
  adv->setName(identity_ble_name());
  adv->start();
  device_logf("INFO", "BLE advertising %s", identity_ble_name());
}

class ServerCallbacks : public NimBLEServerCallbacks {
  void onConnect(NimBLEServer*, NimBLEConnInfo& info) override {
    DispatchGuard guard;
    if (connected) { server->disconnect(info.getConnHandle()); return; }
    portENTER_CRITICAL(&rx_mux);
    ++connection_epoch; ++physical_epoch; rx_count=rx_head=rx_tail=0; fragments.clear();
    negotiated=false; reply_size=reply_offset=0; pending_busy[0]=0;
    connection_handle=info.getConnHandle(); connection_mtu=info.getMTU();
    connected = true;
    portEXIT_CRITICAL(&rx_mux);
    device_logf("INFO", "BLE connected %s", info.getAddress().toString().c_str());
  }

  void onDisconnect(NimBLEServer*, NimBLEConnInfo& info, int reason) override {
    DispatchGuard guard;
    if (info.getConnHandle()!=connection_handle) return;
    portENTER_CRITICAL(&rx_mux);
    connected = false;
    ++connection_epoch; ++physical_epoch; rx_count=rx_head=rx_tail=0; fragments.clear();
    reply_size=reply_offset=0; pending_busy[0]=0;
    portEXIT_CRITICAL(&rx_mux);
    should_advertise = true;
    device_logf("WARN", "BLE disconnected reason=%d", reason);
  }
};

class RxCallbacks : public NimBLECharacteristicCallbacks {
  void onWrite(NimBLECharacteristic* chr, NimBLEConnInfo& info) override {
    DispatchGuard guard;
    if (info.getConnHandle()!=connection_handle) return;
    std::string val = chr->getValue();
    size_t len = val.length();
    if (!len || len>companion::ble_att_value_limit) return;

    bool dropped = false;
    portENTER_CRITICAL(&rx_mux);
    connection_mtu=info.getMTU();
    const char* data=val.data();
    if (uint8_t(val[0])==0x1e) {
      negotiated=true;
      if (!fragments.push(reinterpret_cast<const uint8_t*>(val.data()),len,millis())) {
        portEXIT_CRITICAL(&rx_mux); return;
      }
      data=fragments.data(); len=fragments.size();
    } else {
      fragments.clear();
      if (len>companion::ble_att_value_limit || memchr(data,0,len)) { portEXIT_CRITICAL(&rx_mux); return; }
    }
    if(memchr(data,0,len)) { fragments.clear();portEXIT_CRITICAL(&rx_mux);return; }
    if (rx_count==RX_QUEUE_SIZE) { portEXIT_CRITICAL(&rx_mux); return; }
    memcpy(rx_queue[rx_head], data, len);
    rx_queue[rx_head][len] = '\0';
    queue_epoch[rx_head]=connection_epoch;
    rx_head = (rx_head + 1) % RX_QUEUE_SIZE;
    if (rx_count == RX_QUEUE_SIZE) {
      rx_tail = (rx_tail + 1) % RX_QUEUE_SIZE;
      dropped = true;
    } else {
      rx_count++;
    }
    portEXIT_CRITICAL(&rx_mux);
    if (dropped) {
      device_logf("WARN", "BLE RX queue full; dropped oldest");
    }
  }
};
class IdentityCallbacks : public NimBLECharacteristicCallbacks {
  void onRead(NimBLECharacteristic*,NimBLEConnInfo& info) override {
    DispatchGuard guard;
    if(info.getConnHandle()==connection_handle)identity_read=true;
  }
};

void ble_service_init() {
  identity_init();
  NimBLEDevice::init(identity_ble_name());
#ifdef CODEXMETER_TEST_BLE_MTU23
  NimBLEDevice::setMTU(23);
#endif
  server = NimBLEDevice::createServer();
  static ServerCallbacks server_callbacks;
  server->setCallbacks(&server_callbacks);

  NimBLEService* svc = server->createService(SERVICE_UUID);
  NimBLECharacteristic* rx = svc->createCharacteristic(
      RX_CHAR_UUID, NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::WRITE_NR);
  static RxCallbacks rx_callbacks;
  rx->setCallbacks(&rx_callbacks);

  tx_char = svc->createCharacteristic(
      TX_CHAR_UUID, NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::NOTIFY);
  req_char = svc->createCharacteristic(REQ_CHAR_UUID, NIMBLE_PROPERTY::NOTIFY);
  identity_char =
      svc->createCharacteristic(IDENTITY_CHAR_UUID, NIMBLE_PROPERTY::READ);
  identity_char->setValue(identity_json());
  static IdentityCallbacks identity_callbacks;
  identity_char->setCallbacks(&identity_callbacks);

  server->start();
  start_advertising();
}

void ble_service_tick() {
  DispatchGuard guard;
  if (should_advertise) {
    should_advertise = false;
    start_advertising();
  }
  // One notification per loop; minimum-MTU fragment is 15 logical bytes.
  uint8_t fragment[companion::ble_att_value_limit]; size_t length=0; uint16_t handle=BLE_HS_CONN_HANDLE_NONE;
  portENTER_CRITICAL(&rx_mux);
  if (connected && pending_busy[0]) {
    strcpy(pending_reply,pending_busy); pending_busy[0]=0;
    reply_size=strlen(pending_reply); reply_offset=0; reply_started=millis();
  }
  if (reply_size && millis()-reply_started>=2000) reply_size=reply_offset=0;
  if (connected && reply_size) {
    size_t cap=connection_mtu>8 ? connection_mtu-8 : 15;
    if (cap>507) cap=507;
    size_t count=reply_size-reply_offset; if(count>cap)count=cap;
    fragment[0]=0x1e;fragment[1]=reply_size>>8;fragment[2]=reply_size&255;
    fragment[3]=reply_offset>>8;fragment[4]=reply_offset&255;
    memcpy(fragment+5,pending_reply+reply_offset,count);length=count+5;
    handle=connection_handle;
  }
  portEXIT_CRITICAL(&rx_mux);
  if(length && tx_char && tx_char->notify(fragment,length,handle)) {
    portENTER_CRITICAL(&rx_mux);
    reply_offset+=length-5;
    if(reply_offset==reply_size)reply_size=reply_offset=0;
    portEXIT_CRITICAL(&rx_mux);
  }
}

bool ble_service_has_data() {
  portENTER_CRITICAL(&rx_mux);
  bool has_data = rx_count > 0;
  portEXIT_CRITICAL(&rx_mux);
  return has_data;
}

const char* ble_service_take_data() {
  portENTER_CRITICAL(&rx_mux);
  if (rx_count == 0) {
    rx_current[0] = '\0';
  } else {
    strlcpy(rx_current, rx_queue[rx_tail], sizeof(rx_current));
    current_epoch=queue_epoch[rx_tail];
    rx_tail = (rx_tail + 1) % RX_QUEUE_SIZE;
    rx_count--;
  }
  portEXIT_CRITICAL(&rx_mux);
  return rx_current;
}

void ble_service_ack() {
  if (!connected || !tx_char) return;
  tx_char->setValue("{\"ack\":true}");
  tx_char->notify();
}

void ble_service_nack() {
  if (!connected || !tx_char) return;
  tx_char->setValue("{\"err\":true}");
  tx_char->notify();
}

void ble_service_request_refresh() {
  if (!connected || !req_char) return;
  uint8_t value = 1;
  req_char->setValue(&value, 1);
  req_char->notify();
}

bool ble_service_connected() {
  return connected;
}
bool ble_service_can_dispatch() { return !reply_size && !pending_busy[0]; }
bool ble_service_take_identity_read() { bool result=identity_read;identity_read=false;return result; }
uint32_t ble_service_epoch() { portENTER_CRITICAL(&rx_mux); auto e=physical_epoch; portEXIT_CRITICAL(&rx_mux); return e; }
bool ble_service_data_current() { portENTER_CRITICAL(&rx_mux); bool valid=connected && current_epoch==connection_epoch; portEXIT_CRITICAL(&rx_mux); return valid; }
void ble_service_fence(const char* error) {
  DispatchGuard guard;
  portENTER_CRITICAL(&rx_mux);
  ++connection_epoch; rx_count=rx_head=rx_tail=0; fragments.clear();
  reply_size=reply_offset=0;
  if (connected && negotiated && error)
    snprintf(pending_busy,sizeof(pending_busy),"CM1 {\"op\":\"owner\",\"boot\":\"%s\",\"err\":\"%s\"}",identity_boot(),error);
  portEXIT_CRITICAL(&rx_mux);
}
void ble_service_reply(const char* reply) {
  if(!reply || !*reply || strlen(reply)>companion::frame_limit)return;
  portENTER_CRITICAL(&rx_mux);
  if(connected && !reply_size && !pending_busy[0]) {
    strcpy(pending_reply,reply);reply_size=strlen(reply);reply_offset=0;reply_started=millis();
  }
  portEXIT_CRITICAL(&rx_mux);
}
void ble_service_identity_changed() {
  DispatchGuard guard;
  ble_service_fence(nullptr);
  if(identity_char)identity_char->setValue(identity_json());
}
