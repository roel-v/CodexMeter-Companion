# Contributing

CodexMeter Companion contains a Windows/macOS companion and firmware for the Waveshare C6, Spotpear Ball and original
Waveshare S3. Report bugs and discuss changes in [this repository](https://github.com/roel-v/CodexMeter-Companion/issues).
Include reproduction steps and redacted diagnostics. Contributions are published under the MIT license.

## Development and tests

On Windows, configure D: build output, caches and compiler scratch before installing dependencies:

```powershell
. ./scripts/windows-env.ps1
uv venv D:/build/CodexMeter/venv
uv pip install --python $MeterPython -e '.[test]'
& $MeterPython -m pytest -q -p no:cacheprovider --basetemp D:/build/CodexMeter/test-tmp
```

On macOS, use the machine's configured fast build disk. For example, with BUILD_ROOT set to that location:

```sh
python3 -m venv "$BUILD_ROOT/venv"
export TMPDIR="$BUILD_ROOT/tmp"
mkdir -p "$TMPDIR"
"$BUILD_ROOT/venv/bin/python" -m pip install -e '.[test]'
"$BUILD_ROOT/venv/bin/python" -m pytest -q -p no:cacheprovider --basetemp "$BUILD_ROOT/test-tmp"
```

`python tests/run_tests.py` forwards arguments and exit codes to pytest for older workflows. It runs the same suite;
pytest fixtures and parametrization are required. The test extra is not a runtime dependency.

## Firmware and standalone builds

On Windows, use `tools/test_firmware_usb.ps1` for native protocol/parser tests and the D: PlatformIO environment from
`scripts/windows-env.ps1`. Build each target with `pio run -d firmware -e TARGET` using that environment:

- `waveshare_c6_amoled_216`
- `spotpear_ball_v2`
- `waveshare_amoled_216`

Use `build-standalone.ps1` for the standalone Windows candidate; see its parameters and README.windows.md.
Before large builds, check D: headroom. Retain bundles and evidence on E:; do not put active build/cache output there.
On macOS, set PLATFORMIO_CORE_DIR, PLATFORMIO_BUILD_DIR, PLATFORMIO_LIBDEPS_DIR and UV_CACHE_DIR beneath BUILD_ROOT.
Install PlatformIO separately in the build environment. Builds do not authorize flashing attached devices.

## Before submitting

Run the Python suite and relevant native/firmware checks. Explain what changed, why, and what was actually tested.
Distinguish simulated checks from hardware checks; original S3 builds do not establish physical acceptance.
Keep logical-device and delivery behavior shared; keep serial/GATT handling and board geometry in their adapters.
Update protocol/persistence documentation when those contracts change. Preserve documented legacy compatibility.

Do not commit credentials, chat content, private logs, caches, environments, binaries or other build output.
For documentation-only changes, say that runtime tests were not needed.
