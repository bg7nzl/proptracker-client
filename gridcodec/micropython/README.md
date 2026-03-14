# GridCodec for MicroPython (embedded)

Decode-only, query-only implementation for resource-constrained devices.
Compatible with standard MicroPython (e.g. ESP32, Pyboard). No `gc_set` or `gc_encode`.

- **Single file:** `gridcodec.py` — copy onto device, no dependencies.
- **Memory:** ~13 KB for Layer 1 field matrix (fixed). Layer 2 is skipped on decode.
- **API:** `decode(data)` → bytes consumed; `gc_from(grid, max_out)` / `gc_to(grid, max_out)` return lists of **field indices** (0–323). For 4-char grid input, result is still field-level (degraded).
- **Wire format:** Same as C/Python/JS/Java; Layer 2 payload is skipped but bytes are consumed so the stream position is correct.

## Usage

```python
import gridcodec
m = gridcodec.GridCodecMatrix()
n = m.decode(bytes_from_network)
# n = bytes consumed
from_fields = m.gc_from("FN")   # or "FN31" — same field-level result
to_fields = m.gc_to("PM")
# Convert field index to name
name = gridcodec.field_name(from_fields[0])  # "PM"
```

## Testing on device

1. **Install mpremote** (if needed):
   ```bash
   python3 -m venv .venv && .venv/bin/pip install mpremote
   ```
2. **Close any other program** using the board’s serial port (Thonny, minicom, etc.).
3. **Run tests** (use the script or mpremote directly):
   ```bash
   ./run_on_device.sh
   ```
   Or manually:
   ```bash
   mpremote connect /dev/ttyACM0 fs cp gridcodec.py :
   mpremote connect /dev/ttyACM0 fs cp test_gridcodec.py :
   mpremote connect /dev/ttyACM0 run test_gridcodec.py
   ```
   If you get “Permission denied” on the port: `sudo usermod -aG dialout $USER` then log out and back in.

## Verified version and device

| Item         | Value                    |
|--------------|--------------------------|
| MicroPython  | 1.27.0                   |
| Controller   | Raspberry Pi Pico (RP2040) |

Tests were run on the above; all tests passed (helpers, decode L1-only, decode L1+L2 with L2 skipped, 4-char degrades to field).

## Decode latency

`test_decode_latency()` measures decode time (ms per decode) for the L1-only (14 B) and L1+L2 (30 B, L2 skipped) payloads. Run the full test suite on device to see the printed timings.

| Payload        | Size | CPython (ref) | Raspberry Pi Pico (RP2040), 1.27.0 |
|----------------|------|----------------|-------------------------------------|
| L1-only        | 14 B | ~0.3 ms/decode | **~87 ms/decode** (measured)        |
| L1+L2 (L2 skip)| 30 B | ~10 ms/decode  | **~3535 ms/decode** (measured)      |

L1+L2 skip is slower on Pico because the L2 payload is parsed byte-by-byte to advance the stream; use L1-only payloads when decode latency matters on slow MCUs.
