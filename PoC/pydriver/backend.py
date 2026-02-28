import platform
import struct
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional

import libusb_package
import usb.core
import usb.util

VENDOR_ID = 0x04F3
PRODUCT_ID = 0x0C4C

EP_CMD_IN = 0x83  # Low-level sensor commands (40 xx)
EP_MOC_IN = 0x83  # MOC commands (40 FF xx)
EP_OUT = 0x01

TIMEOUT_MS = 5000
BLOCKING_TIMEOUT_MS = 30000
INTERFACE = 0

backend = libusb_package.get_libusb1_backend()


# ── Response codes ──────────────────────────────────────────────────


class MocResponse(IntEnum):
    SUCCESS = 0x00
    NOT_READY = 0xFE
    VERIFY_FAILED = 0xFD
    HLK_FAIL = 0xFC
    DIRTY = 0xFB
    ERROR = 0xFF
    TOO_HIGH = 0x41
    TOO_LEFT = 0x42
    TOO_LOW = 0x43
    TOO_RIGHT = 0x44


class InitStatus(IntEnum):
    INITIALIZING = 0x01
    READY = 0x03


# ── Sensor info container ──────────────────────────────────────────


@dataclass
class SensorInfo:
    fw_major: int = 0
    fw_minor: int = 0
    boot_major: int = 0
    boot_minor: int = 0
    checksum: int = 0
    width: int = 0
    height: int = 0

    @property
    def image_size(self) -> int:
        return self.width * self.height

    @property
    def image_byte_size(self) -> int:
        return self.width * self.height * 2

    def __repr__(self):
        return (
            f"SensorInfo(fw={self.fw_major}.{self.fw_minor}, "
            f"boot={self.boot_major}.{self.boot_minor}, "
            f"checksum=0x{self.checksum:04X}, "
            f"dimensions={self.width}x{self.height})"
        )


# ── Low-level USB transport ────────────────────────────────────────


class ElanDevice:
    def __init__(self):
        self.dev: Optional[usb.core.Device] = None
        self.info = SensorInfo()

    def open(self):
        self.dev = usb.core.find(
            backend=backend, idVendor=VENDOR_ID, idProduct=PRODUCT_ID
        )
        if self.dev is None:
            raise ValueError("ELAN device not found")

        if platform.system() == "Linux":
            if self.dev.is_kernel_driver_active(INTERFACE):
                self.dev.detach_kernel_driver(INTERFACE)

        self.dev.set_configuration()
        usb.util.claim_interface(self.dev, INTERFACE)

        cfg = self.dev.get_active_configuration()
        intf = cfg[(INTERFACE, 0)]
        ep_in = usb.util.find_descriptor(
            intf,
            custom_match=lambda e: (
                usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_IN
            ),
        )
        self._max_packet_size = ep_in.wMaxPacketSize if ep_in else 64
        print(
            f"Device opened: {self.dev.idVendor:04X}:{self.dev.idProduct:04X}"
            f" (max packet: {self._max_packet_size})"
        )

    def close(self):
        if self.dev is not None:
            usb.util.release_interface(self.dev, INTERFACE)
            usb.util.dispose_resources(self.dev)
            self.dev = None
            print("Device released.")

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *args):
        self.close()

    # ── Raw USB I/O ────────────────────────────────────────────────

    def _write(self, data: bytes, timeout: int = TIMEOUT_MS):
        """Bulk OUT write."""
        self.dev.write(EP_OUT, data, timeout=timeout)

    def _read(self, length: int, timeout: int = TIMEOUT_MS) -> bytes:
        """Bulk IN read. Buffer is at least max packet size to prevent overflow."""
        buf_size = max(length, self._max_packet_size)
        data = bytes(self.dev.read(EP_IN, buf_size, timeout=timeout))
        return data[:length]

    def _cmd(
        self,
        tx: bytes,
        rx_len: int,
        timeout: int = TIMEOUT_MS,
        ep_in: int = EP_CMD_IN,
        name: str = "",
    ) -> Optional[bytes]:
        """Send command, read response."""
        label = name or f"0x{tx.hex()}"
        try:
            print(f"    [{label}] TX ({len(tx)}B): {tx.hex()}")
            self._write(tx, timeout=timeout)
            if rx_len == 0:
                return None
            time.sleep(0.05)
            buf_size = max(rx_len, self._max_packet_size)
            data = bytes(self.dev.read(ep_in, buf_size, timeout=timeout))
            print(f"    [{label}] RX ({len(data)}B): {data.hex()}")
            return data[:rx_len]
        except usb.core.USBTimeoutError:
            print(f"    [{label}] TIMEOUT (no response after {timeout}ms)")
            raise
        except usb.core.USBError as e:
            print(f"    [{label}] USB error: {e}")
            raise

    # ── MOC command helper ─────────────────────────────────────────

    def _moc_cmd(
        self,
        sub_cmd: int,
        payload: bytes = b"",
        rx_len: int = 2,
        timeout: int = TIMEOUT_MS,
        name: str = "",
    ) -> bytes:
        """
        Send MOC command: 40 FF <sub_cmd> [payload...]
        Response read from EP 0x84.
        """
        tx = bytes([0x40, 0xFF, sub_cmd]) + payload
        resp = self._cmd(
            tx,
            rx_len,
            timeout=timeout,
            ep_in=EP_MOC_IN,
            name=name or f"MOC 0x{sub_cmd:02X}",
        )
        if resp is None:
            return b""
        if len(resp) < 1 or resp[0] != 0x40:
            print(f"  [{name}] Unexpected response header: {resp.hex()}")
        return resp

    @staticmethod
    def _moc_result(resp: bytes) -> int:
        """Extract result byte from MOC response (byte index 1)."""
        if len(resp) < 2:
            return -1
        return resp[1]

    @staticmethod
    def _moc_ok(resp: bytes) -> bool:
        """Check if MOC response indicates success."""
        return len(resp) >= 2 and resp[1] == MocResponse.SUCCESS

    # ── Bridge / low-level commands ────────────────────────────────

    def get_fw_version(self) -> tuple[int, int]:
        """CMD: 40 19 → 2 bytes packed BCD."""
        resp = self._cmd(b"\x40\x19", 2, name="FW Version")
        major = (resp[0] >> 4) * 10 + (resp[0] & 0x0F)
        minor = (resp[1] >> 4) * 10 + (resp[1] & 0x0F)
        self.info.fw_major = major
        self.info.fw_minor = minor
        print(f"  FW Version: {major}.{minor}")
        return major, minor

    def get_boot_version(self) -> tuple[int, int]:
        """CMD: 40 1A → 2 bytes packed BCD."""
        resp = self._cmd(b"\x40\x1a", 2, name="Boot Version")
        major = (resp[0] >> 4) * 10 + (resp[0] & 0x0F)
        minor = (resp[1] >> 4) * 10 + (resp[1] & 0x0F)
        self.info.boot_major = major
        self.info.boot_minor = minor
        print(f"  Boot Version: {major}.{minor}")
        return major, minor

    def get_fw_checksum(self) -> int:
        """CMD: 40 1B → 2 bytes."""
        resp = self._cmd(b"\x40\x1b", 2, name="FW Checksum")
        checksum = (resp[0] << 8) | resp[1]
        self.info.checksum = checksum
        print(f"  FW Checksum: 0x{checksum:04X}")
        return checksum

    def get_sensor_dimensions(self) -> tuple[int, int]:
        """CMD: 00 0C → 4 bytes (width, height as uint16 LE)."""
        resp = self._cmd(b"\x00\x0c", 4, name="Sensor Dimensions")
        # Parse as two uint16 — try both LE and raw byte pairs
        width = resp[0] | (resp[1] << 8)
        height = resp[2] | (resp[3] << 8)
        # Sanity check — if dimensions look wrong, try big-endian
        if width == 0 or height == 0 or width > 500 or height > 500:
            width = (resp[0] << 8) | resp[1]
            height = (resp[2] << 8) | resp[3]
        self.info.width = width
        self.info.height = height
        print(f"  Sensor: {width}x{height}")
        return width, height

    def read_register(self, reg: int) -> int:
        """CMD: 40 [reg+0x40] → 1 byte."""
        cmd = bytes([0x40, (reg & 0x3F) + 0x40])
        resp = self._cmd(cmd, 1, name=f"RegRead 0x{reg:02X}")
        return resp[0]

    def write_register(self, reg: int, value: int):
        """CMD: 40 [reg+0x80] [value] → no response."""
        cmd = bytes([0x40, (reg & 0x3F) + 0x80, value & 0xFF])
        self._cmd(cmd, 0, name=f"RegWrite 0x{reg:02X}=0x{value:02X}")

    def read_sensor_status(self) -> int:
        """CMD: 40 13 → 1 byte SPI status."""
        resp = self._cmd(b"\x40\x13", 1, name="Sensor Status")
        print(f"  Sensor SPI status: 0x{resp[0]:02X}")
        return resp[0]

    def send_watchdog_reset(self):
        """CMD: 40 27 W D T R S T (8 bytes) → no response."""
        cmd = b"\x40\x27WDTRST"
        assert len(cmd) == 8
        self._cmd(cmd, 0, name="WDT Reset")
        print("  Watchdog reset sent.")

    def switch_to_bootloader(self):
        """CMD: 42 01 R U N I A P (8 bytes) → no response."""
        cmd = b"\x42\x01RUNIAP"
        assert len(cmd) == 8
        self._cmd(cmd, 0, name="Switch Bootloader")
        print("  Switched to bootloader.")

    # ── MOC: Initialization ────────────────────────────────────────

    def get_sensor_status(self) -> int:
        """
        MOC 0x00 — Query MOC chip status.
        Returns: 0x01 = booting, 0x03 = ready.
        """
        resp = self._moc_cmd(0x00, rx_len=2, name="Sensor Status")
        return self._moc_result(resp)

    def wait_sensor_ready(self, max_retries: int = 100) -> bool:
        for i in range(max_retries):
            try:
                resp = self._moc_cmd(0x00, rx_len=2, name="Poll Ready")
            except usb.core.USBTimeoutError:
                print(f"    Poll attempt {i + 1}/{max_retries} timed out, retrying...")
                time.sleep(0.5)
                continue

            status = self._moc_result(resp)
            if status == InitStatus.READY:
                print(f"  Sensor ready (attempt {i + 1})")
                return True
            elif status == InitStatus.INITIALIZING:
                print(f"    Sensor initializing (attempt {i + 1})...")
                time.sleep(0.03)
            else:
                print(f"    Unexpected init status: 0x{status:02X}")
                time.sleep(0.03)
        print("  Sensor did not become ready!")
        return False

    def initialize(self) -> SensorInfo:
        """
        Full initialization sequence:
        1. Get bridge FW version
        2. Poll sensor ready
        3. Get sensor dimensions
        """
        self.get_fw_version()

        if not self.wait_sensor_ready():
            raise RuntimeError("Sensor failed to initialize")

        print("=== Device Initialization ===")
        self.get_boot_version()
        self.get_fw_checksum()

        self.get_sensor_dimensions()
        print(f"  {self.info}")
        print("=== Initialization Complete ===")
        return self.info

    # ── MOC: Finger count & management ─────────────────────────────

    def get_finger_count(self) -> int:
        """MOC 0x04 → enrolled finger count (0–50)."""
        resp = self._moc_cmd(0x04, rx_len=2, name="Finger Count")
        count = self._moc_result(resp)
        print(f"  Enrolled fingers: {count}")
        return count

    def remove_finger_by_index(self, index: int) -> bool:
        """MOC 0x05 [idx_hi] [idx_lo] → remove finger."""
        payload = bytes([(index >> 8) & 0xFF, index & 0xFF])
        resp = self._moc_cmd(0x05, payload=payload, rx_len=2, name="Remove by Index")
        result = self._moc_result(resp)
        if result == MocResponse.SUCCESS:
            print(f"  Finger {index} removed.")
            return True
        elif result == MocResponse.NOT_READY:
            print(f"  Finger {index} not found (0xFE) — treating as success.")
            return True
        else:
            print(f"  Remove failed: 0x{result:02X}")
            return False

    def remove_finger_by_sid(self, sid: bytes) -> bool:
        """MOC 0x13 [69B SID] → remove finger by SID."""
        if len(sid) != 69:
            raise ValueError(f"SID must be 69 bytes, got {len(sid)}")
        resp = self._moc_cmd(0x13, payload=sid, rx_len=2, name="Remove by SID")
        result = self._moc_result(resp)
        if result in (MocResponse.SUCCESS, MocResponse.NOT_READY):
            print(f"  Finger removed by SID.")
            return True
        else:
            print(f"  Remove by SID failed: 0x{result:02X}")
            return False

    def remove_all_fingers(self):
        """MOC 0x99 → delete all enrolled fingerprints. No response."""
        self._moc_cmd(0x99, rx_len=0, name="Delete All")
        print("  All fingerprints deleted.")

    def check_duplicate(self) -> bytes:
        """MOC 0x10 → 3-byte duplicate check result."""
        resp = self._moc_cmd(0x10, rx_len=3, name="Check Duplicate")
        print(f"  Duplicate check: {resp.hex()}")
        return resp

    # ── MOC: Enrollment ────────────────────────────────────────────

    def enroll_finger(
        self,
        index: int,
        param1: int = 0x00,
        param2: int = 0x00,
        flag: int = 0x00,
    ) -> tuple[int, str]:
        """
        MOC 0x01 [idx] [p1] [p2] [flag] → enroll one touch.
        Returns (result_code, description).
        Blocks until finger is placed.
        """
        payload = bytes([index & 0xFF, param1, param2, flag])
        resp = self._moc_cmd(
            0x01,
            payload=payload,
            rx_len=2,
            timeout=BLOCKING_TIMEOUT_MS,
            name="Enroll",
        )
        result = self._moc_result(resp)
        desc = self._describe_moc_result(result)
        print(f"  Enroll touch result: 0x{result:02X} ({desc})")
        return result, desc

    def cancel_operation(self):
        """MOC 0x02 → cancel enroll/verify in progress."""
        self._moc_cmd(0x02, rx_len=0, name="Cancel")
        print("  Operation cancelled.")

    def commit_enroll_id(self, sid: bytes) -> bool:
        """MOC 0x11 [69B SID] → bind SID to last enrolled template."""
        if len(sid) != 69:
            raise ValueError(f"SID must be 69 bytes, got {len(sid)}")
        resp = self._moc_cmd(0x11, payload=sid, rx_len=2, name="Commit Enroll ID")
        result = self._moc_result(resp)
        if result == MocResponse.SUCCESS:
            print("  Enrollment committed with SID.")
            return True
        else:
            print(f"  Commit failed: 0x{result:02X}")
            return False

    # ── MOC: Verification ──────────────────────────────────────────

    def verify_finger(self) -> tuple[int, str]:
        """
        MOC 0x03 → verify/identify (blocks until finger placed).
        Returns (result_code, description).
        result 0x00–0x09 = match at that finger index.
        """
        print("  Waiting for finger...")
        resp = self._moc_cmd(
            0x03,
            rx_len=2,
            timeout=BLOCKING_TIMEOUT_MS,
            name="Verify",
        )
        result = self._moc_result(resp)
        desc = self._describe_moc_result(result)
        print(f"  Verify result: 0x{result:02X} ({desc})")
        return result, desc

    def get_sid(self, index: int) -> Optional[bytes]:
        """MOC 0x12 [idx] → 70 bytes (40 00 [68B SID data])."""
        payload = bytes([index & 0xFF])
        resp = self._moc_cmd(0x12, payload=payload, rx_len=70, name="Get SID")
        if self._moc_ok(resp):
            sid_data = resp[2:]
            print(f"  SID for finger {index}: {sid_data.hex()}")
            return sid_data
        else:
            result = self._moc_result(resp)
            print(f"  Get SID failed: 0x{result:02X}")
            return None

    def verify_and_identify(self) -> Optional[tuple[int, bytes]]:
        """
        Full verify flow:
        1. Send verify (blocks for finger)
        2. On match, retrieve SID
        Returns (finger_index, sid_bytes) or None on failure.
        """
        result, desc = self.verify_finger()
        if 0x00 <= result <= 0x09:
            sid = self.get_sid(result)
            if sid is not None:
                return result, sid
        return None

    # ── MOC: Sensor mode ───────────────────────────────────────────

    def set_sensor_mode(self, mode: int) -> bool:
        """MOC 0x14 [mode] → set FW sensor mode."""
        payload = bytes([mode & 0xFF])
        resp = self._moc_cmd(0x14, payload=payload, rx_len=2, name="Set Mode")
        result = self._moc_result(resp)
        print(f"  Set mode {mode}: 0x{result:02X}")
        return result == MocResponse.SUCCESS

    # ── MOC: SDCP commands ─────────────────────────────────────────

    def get_fw_app_key(self) -> Optional[tuple[bytes, bytes]]:
        """
        MOC 0x0D → 66 bytes: 40 00 [32B X] [32B Y]
        Returns (x, y) raw P-256 coordinates, or None on error.
        """
        resp = self._moc_cmd(0x0D, rx_len=66, name="FW App Key")
        if self._moc_ok(resp) and len(resp) >= 66:
            x = resp[2:34]
            y = resp[34:66]
            print(f"  FW App Key X: {x.hex()}")
            print(f"  FW App Key Y: {y.hex()}")
            return x, y
        else:
            print(f"  Get FW App Key failed")
            return None

    def get_fw_authorized_info(self, challenge: bytes) -> Optional[tuple[bytes, bytes]]:
        """
        MOC 0x0C [32B challenge] → 66 bytes: 40 00 [32B block1] [32B block2]
        Retries on 0xFE (not ready) up to 10 times.
        """
        if len(challenge) != 32:
            raise ValueError(f"Challenge must be 32 bytes, got {len(challenge)}")

        for attempt in range(10):
            resp = self._moc_cmd(
                0x0C, payload=challenge, rx_len=66, name="FW Auth Info"
            )
            result = self._moc_result(resp)
            if result == MocResponse.SUCCESS and len(resp) >= 66:
                block1 = resp[2:34]
                block2 = resp[34:66]
                return block1, block2
            elif result == MocResponse.NOT_READY:
                print(f"  Auth info not ready, retry {attempt + 1}/10")
                time.sleep(0.3)
            else:
                print(f"  Auth info failed: 0x{result:02X}")
                return None
        print("  Auth info: max retries exceeded")
        return None

    def receive_enroll_nonce(self) -> Optional[bytes]:
        """
        MOC 0x09 → 34 bytes: 40 00 [32B nonce]
        Retries on 0xFE up to 10 times.
        """
        for attempt in range(10):
            resp = self._moc_cmd(0x09, rx_len=34, name="Enroll Nonce")
            result = self._moc_result(resp)
            if result == MocResponse.SUCCESS and len(resp) >= 34:
                nonce = resp[2:34]
                print(f"  Enroll nonce: {nonce.hex()}")
                return nonce
            elif result == MocResponse.NOT_READY:
                print(f"  Nonce not ready, retry {attempt + 1}/10")
                time.sleep(0.3)
            else:
                print(f"  Enroll nonce failed: 0x{result:02X}")
                return None
        print("  Enroll nonce: max retries exceeded")
        return None

    def ecc_sign_verify(self, ecc_data: bytes, flag: int = 0x00) -> Optional[bytes]:
        """
        MOC 0x06 [96B ECC data] [flag] → ~1202 bytes response.
        """
        if len(ecc_data) != 96:
            raise ValueError(f"ECC data must be 96 bytes, got {len(ecc_data)}")
        payload = ecc_data + bytes([flag])
        resp = self._moc_cmd(0x06, payload=payload, rx_len=1202, name="ECC Sign Verify")
        if len(resp) >= 2:
            print(f"  ECC sign/verify response: {len(resp)} bytes")
            return resp
        return None

    def ecc_enroll_commit(self, ecc_data: bytes) -> bool:
        """MOC 0x0A [32B ECC data] → 2 bytes."""
        if len(ecc_data) != 32:
            raise ValueError(f"ECC data must be 32 bytes, got {len(ecc_data)}")
        resp = self._moc_cmd(0x0A, payload=ecc_data, rx_len=2, name="ECC Enroll Commit")
        return self._moc_ok(resp)

    # ── Image capture ──────────────────────────────────────────────

    def capture_start(self):
        """CMD: 00 09 → trigger sensor (no response)."""
        self._cmd(b"\x00\x09", 0, name="Capture Start")

    def capture_base_image(self) -> Optional[bytes]:
        """
        CMD: 01 0A → read base/background image (w×h×2 bytes).
        120x120 sensor: reads 0x3200 bytes (80x80 effective).
        """
        w, h = self.info.width, self.info.height
        if w == 0 or h == 0:
            raise RuntimeError(
                "Sensor dimensions not initialized — call initialize() first"
            )

        if w == 120 and h == 120:
            read_size = 0x3200  # 80×80×2
        else:
            read_size = w * h * 2

        self._write(b"\x01\x0a")
        time.sleep(0.05)
        raw = self._read(read_size, timeout=TIMEOUT_MS)
        print(f"  Base image: {len(raw)} bytes")
        return bytes(raw)

    def capture_fingerprint_image(self) -> Optional[bytes]:
        """
        Full capture sequence:
        1. 00 09 → trigger sensor
        2. 02 0A → read fingerprint image (w×h×2 bytes)
        Returns raw pixel data (LE uint16 pairs).
        """
        w, h = self.info.width, self.info.height
        if w == 0 or h == 0:
            raise RuntimeError(
                "Sensor dimensions not initialized — call initialize() first"
            )

        # Trigger capture
        self.capture_start()
        time.sleep(0.05)

        # Read image
        read_size = w * h * 2
        self._write(b"\x02\x0a")
        time.sleep(0.05)
        raw = self._read(read_size, timeout=TIMEOUT_MS)
        print(f"  Fingerprint image: {len(raw)} bytes")
        return bytes(raw)

    @staticmethod
    def pixels_from_raw(raw: bytes, width: int, height: int) -> list[int]:
        """Convert raw LE byte pairs to 16-bit pixel values."""
        pixels = []
        for i in range(0, min(len(raw), width * height * 2), 2):
            pixels.append(raw[i] | (raw[i + 1] << 8))
        return pixels

    # ── Register dump (USER_DEFINE sub-cmd 0x02 equivalent) ───────

    def dump_all_registers(self) -> dict[int, int]:
        """Read all 64 sensor registers (0x00–0x3F)."""
        regs = {}
        for r in range(0x40):
            val = self.read_register(r)
            regs[r] = val
        print(f"  Dumped {len(regs)} registers")
        return regs

    # ── Helper ─────────────────────────────────────────────────────

    @staticmethod
    def _describe_moc_result(code: int) -> str:
        if 0x00 <= code <= 0x09:
            return f"match/success (finger {code})"
        descriptions = {
            0xFE: "not ready / area not enough",
            0xFD: "verify failed (no match)",
            0xFC: "HLK / image quality failure",
            0xFB: "dirty sensor",
            0xFF: "error",
            0x41: "finger too high",
            0x42: "finger too left",
            0x43: "finger too low",
            0x44: "finger too right",
        }
        return descriptions.get(code, f"unknown (0x{code:02X})")


# ── Main ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    with ElanDevice() as sensor:
        # Full init
        sensor.initialize()

        # Query enrolled fingers
        sensor.get_finger_count()

        # # Verify (uncomment to test — blocks until finger placed)
        # result = sensor.verify_and_identify()
        # if result:
        #     idx, sid = result
        #     print(f"Matched finger {idx}, SID: {sid.hex()}")

        # # Capture image (uncomment to test)
        # raw = sensor.capture_fingerprint_image()
        # if raw:
        #     pixels = sensor.pixels_from_raw(
        #         raw, sensor.info.width, sensor.info.height
        #     )
        #     print(f"Got {len(pixels)} pixels")
