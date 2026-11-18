#pragma once

// Hardware facts shared by identity and display configuration.
#ifdef CODEXMETER_BOARD_BALL
#define CODEXMETER_HAS_POWER 0
#define CODEXMETER_HAS_IMU 0
#define CODEXMETER_HAS_SETTINGS 0
#define CODEXMETER_MODEL "spotpear_ball_v2"
#define CODEXMETER_SCREEN_W 240
#define CODEXMETER_SCREEN_H 240
#define CODEXMETER_CAPABILITIES "\"metric_validity\",\"brightness\",\"rotation\",\"touch\",\"screen\""
#else
#define CODEXMETER_HAS_POWER 1
#define CODEXMETER_HAS_IMU 1
#define CODEXMETER_HAS_SETTINGS 1
#ifdef CODEXMETER_BOARD_C6
#define CODEXMETER_MODEL "waveshare_c6_amoled_216"
#else
#define CODEXMETER_MODEL "waveshare_amoled_216"
#endif
#define CODEXMETER_SCREEN_W 480
#define CODEXMETER_SCREEN_H 480
#define CODEXMETER_CAPABILITIES "\"metric_validity\",\"brightness\",\"rotation\",\"auto_rotation\",\"themes\",\"touch\",\"screen\""
#endif
