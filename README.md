# EdgeProof

**Ship a model to the NPU, verified.**

Getting a model onto a Qualcomm Snapdragon NPU and *keeping the right answer* is
a multi-day ordeal of QNN logs, vendor libraries and silent CPU fallbacks.
EdgeProof turns the traps into one command with a PASS / WARN / FAIL report —
checked against a real connected device and your APK.

Every check was a scar earned shipping a Whisper encoder to the Hexagon NPU on
an iQOO (SM8850, Hexagon V81).

## Install

```
pip install -e .
```

Needs the Android SDK (`adb`, and `aapt`/`aapt2` from build-tools). EdgeProof
finds them via `ANDROID_HOME` / `ANDROID_SDK_ROOT` or the default Android Studio
install path. No Python dependencies — stdlib only.

## Use

```
edgeproof device                      # what SoC / Hexagon arch is connected
edgeproof scan app-debug.apk          # run the checks against that APK + device
edgeproof scan app-debug.apk --soc SM8850     # name the target when no device is attached
edgeproof scan app-debug.apk --arch 81        # or give the Hexagon arch directly
edgeproof parity --launch                     # relaunch the app, prove NPU == host
edgeproof parity --logfile saved.log          # same check on a captured log
```

`scan` exits non-zero if any check FAILs, so it drops into CI.

## Checks wired so far

| Check | What it catches |
|---|---|
| **skels** | The device loads exactly one Hexagon backend skel (e.g. `libQnnHtpV81Skel.so`). Every other arch's skel is bundled weight. On a single-target build EdgeProof reports how much is removable (≈67 MB on the reference APK) and prints the Gradle exclude. It also FAILs if the skel the device needs is missing — the quiet reason a model runs on CPU instead of the NPU. |
| **cdsprpc** | Since Android 12 an app can't `dlopen` a vendor library it hasn't declared. QNN reaches the DSP through `libcdsprpc.so`; undeclared, HTP init fails with `QNN_DEVICE_ERROR_INVALID_CONFIG` and the model silently never touches the NPU. EdgeProof flags a QNN app whose manifest is missing the declaration. |
| **parity** | Running on the NPU is worthless if fp16/quantisation moved the answer. `edgeproof parity --launch` relaunches the app, reads the self-test it prints (fixed inputs scored on device and host), and PASS/FAILs the worst drift against a tolerance — also checking it really ran on the NPU. On the reference app: **0.016, PASS**; the pre-fix whole-graph build: **0.209, FAIL**. Works on a saved log too (`--logfile`), for CI. |

Self-test line format any app can print at launch:

```
selftest <provider>: max |Δrisk| 0.016 over 10 windows · pattern 8/8
selftest[0] phone 0.7483 laptop 0.7517  <input label>
```

## Roadmap

- **split** — auto-partition a graph across CPU/NPU/CPU where the numerics survive.
- **quant** — reject a quantization scheme that costs more accuracy than a set tolerance.
- **logtriage** — classify QNN / adsprpc logcat lines as benign vs real failure.
- **bench** — latency + power across CPU / GPU / NPU on the actual device.
- **mem** — the load-time graph-prep memory spike.
