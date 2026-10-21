# magi65-mac-fw-builder

*[日本語版はこちら / Japanese version](README_ja.md)*

A native macOS OTA firmware flashing tool for the IQUNIX Magi65 (ANSI/CSF6C4).

It runs on nothing but the `python3` that ships with macOS and `ctypes` (talking to IOKit directly). No additional packages to install, no pip, no venv.

## Requirements

- macOS.
- `python3`. The tool works with the system `/usr/bin/python3` (bundled with the Command Line Tools, Python 3.9 or later). If `python3` is not on your `PATH` and you get `command not found`, use the absolute path `/usr/bin/python3` as shown in the examples below (a pyenv or Homebrew `python3` works too).
- The terminal application you run the tool from (Terminal.app or similar) must be granted **System Settings > Privacy & Security > Input Monitoring**. Without it, sending HID reports fails with `kIOReturnNotPermitted`.
- The keyboard must be in **USB wired mode** (`FN + T` or `FN + 5`). The OTA interface is not exposed over wireless connections (Bluetooth or 2.4GHz).

## Procedure

Run the following steps in order. If `python3` in the examples gives you `command not found`, use `/usr/bin/python3` (see Requirements).

### 0. Clone and set up

```
git clone https://github.com/t4kuya6e/magi65-mac-fw-builder.git
cd magi65-mac-fw-builder
```

Next, **grant Input Monitoring** to the terminal application you will actually run the commands from (Terminal.app or similar).

1. Open System Settings > Privacy & Security > Input Monitoring.
2. Add your terminal application to the list and turn the toggle on.
3. Quit and relaunch that terminal application so the permission takes effect.

Then put the keyboard into **USB wired mode** and connect it directly to your Mac (`FN + T` or `FN + 5`; the OTA interface does not appear over a wireless connection).

### 1. Obtain the official firmware updater and put it in `exe_here/`

The firmware itself is not bundled with this tool. Download the official updater `.exe` for your model (Magi65 ANSI/CSF6C4) from the IQUNIX website and place it in `exe_here/` at the repository root. If you downloaded a `.zip`, extract it and place the `.exe` from inside. **Do not rename the file.** Flashing checks the model code in the file name (see "Risks and disclaimer").

```
magi65-mac-fw-builder/
├── exe_here/
│   └── MG65-CSF6C4-V0120-20260120.exe   ← put exactly one official .exe here
├── magi65_ota.py
└── ...
```

**Place exactly one `.exe` in `exe_here/`.** Every command below refers to it as `exe_here/*.exe`, so you can copy and paste them as-is without substituting a filename. With two or more `.exe` files the command stops with a usage error; with none you get `no matches found`. Both cases exit without touching the device at all.

The contents of `exe_here/` are excluded by `.gitignore`, so there is no risk of committing the file by accident.

### 2. Dry run to inspect what would be sent

With neither `--check` nor `--flash` (the default), the tool never connects to the device. It validates the extracted firmware and prints the sequence it would send (the contents of the START, DATA, and END reports). Confirm that extraction and validation succeed here first.

```
/usr/bin/python3 magi65_ota.py --exe exe_here/*.exe
```

### 3. Connectivity check (no flashing)

Connects to the device and queries the version only. Nothing is written.

```
/usr/bin/python3 magi65_ota.py --exe exe_here/*.exe --check
```

If the version and CRC of the firmware currently on the device are printed, then device selection, the communication path, and permissions are all working (if it fails with `kIOReturnNotPermitted`, re-check Input Monitoring). Make a note of the CRC: a change in this value after flashing (step 5) is how you confirm the result.

### 4. Flash

**This is irreversible. Read "Risks and disclaimer" below before running it.**

```
/usr/bin/python3 magi65_ota.py --exe exe_here/*.exe --flash --i-understand-brick-risk
```

- You will be prompted to type `FLASH` in uppercase (a second confirmation to prevent accidental runs).
- The tool launches `caffeinate` internally to prevent sleep and display sleep during the write.
- **Do not touch the keyboard or the cable while it is writing.** An interruption risks corrupting the firmware.
- On success it prints `OTA Success` and then automatically verifies the firmware CRC.

### 5. Verify after flashing

Once step 4 finishes, confirm that the CRC has changed to that of the official firmware you obtained. The `--flash` run verifies this automatically, but you can also check it by hand.

```
/usr/bin/python3 magi65_ota.py --exe exe_here/*.exe --check
```

If the reported CRC matches the CRC at the end of the official firmware body, the write succeeded.

## Options

| Option | Description |
|---|---|
| `--exe <path>` | (required) Path to the `.exe` or `.exe.zip` containing the firmware. If exactly one `.exe` sits in `exe_here/`, you can write `exe_here/*.exe` |
| `--check` | Connect to the device and query the version only (no flashing) |
| `--flash` | Write the firmware to the device |
| `--i-understand-brick-risk` | Consent flag required by `--flash` |
| `--allow-unverified-model` | With `--flash`, write even if the model code in the file name is unverified or cannot be read |
| `--report-len <int>` | HID report length (default 64) |
| `--timeout <float>` | Timeout in seconds when waiting for a device response (default 2.0) |

## Risks and disclaimer

- Flashing firmware over OTA is **irreversible**. An interruption or failure during the write may **brick** the keyboard, leaving it unable to boot.
- No simple user-level recovery path (DFU or similar) has been confirmed. Hardware-level recovery (Telink BDT, reflashing through the PCB pads) may be possible but is unverified, and would require disassembly and dedicated equipment.
- The data this tool sends is based on protocol analysis of the official updater (decompilation) and on successful flashing of a single physical unit. **Safety on all units and in all situations is not guaranteed. Use at your own risk.**
- The tool rejects any updater file or device that does not match the fixed Magi65 identifiers (VID=`0x320F` / PID=`0x5055` / UsagePage=`0xFFEF` / ReportID=`5`). Note, however, that this **cannot distinguish between model variants that share the same VID/PID**. Always use the official file for your own model.
- Because the model code can only be read from the official file name (`MG65-<model>-V<version>-<date>.exe`; for a `.zip`, the `.exe` name inside), `--flash` refuses files whose model and version are not verified. Verified: `CSF6C4` (all versions) and `CS0164` `V0121`. Names that do not follow the official format (such as the ` (1)` added on re-download) are refused too, so restore the original name. Add `--allow-unverified-model` only when you knowingly flash an unverified version.

### Limits of firmware integrity validation

The original official tool (by IQUNIX) does not itself recompute the CRC at the end of the firmware body; it only checks that the value is neither `0x00000000` nor `0xFFFFFFFF`. This tool stops at the same level of validation, supplemented by the checks below, but **this is not complete corruption detection**.

- `code_2M` and `param_128K` must resolve uniquely during resource extraction, matching on name, type, and size
- The declared size must agree with the actual data length, and the chunk count must fit in a 16-bit index
- The CRC at the end of the body must not be `0x00000000` or `0xFFFFFFFF`
- The extracted identifiers (VID/PID/UsagePage/ReportID) must match the fixed Magi65 values

A corrupted image that carries valid-looking values (one that passes every check above while its contents are broken) will not be detected.

## Tests

The pure-logic tests run without any hardware.

```
/usr/bin/python3 -m unittest discover -s tests -v
```

The extraction tests that use a real official `.exe` run only when the environment variable `MAGI65_TEST_EXE` points at an actual file; otherwise they are skipped automatically.

```
MAGI65_TEST_EXE=$(echo exe_here/*.exe) /usr/bin/python3 -m unittest discover -s tests -v
```

## Documentation

Both documents are written in Japanese.

- [`docs/OTA_PROTOCOL.md`](docs/OTA_PROTOCOL.md): analysis of the USB HID OTA protocol, based on decompilation and verification against real hardware
- [`docs/design.md`](docs/design.md): design document for this tool

## License

MIT. See [`LICENSE`](LICENSE) for details.
