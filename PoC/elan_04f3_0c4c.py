import argparse
import platform
import shlex
import struct
import sys
import time
from dataclasses import dataclass
from enum import IntEnum
from typing import Optional

import libusb_package
import usb.core
import usb.util

VENDOR_ID = 0x04F3
PRODUCT_ID = 0x0C4C

# Endpoint map (confirmed from reference):
#   Most commands:           OUT 0x01, IN 0x83
#   Blocking (verify/enroll): OUT 0x01, IN 0x84
#   Image data:              OUT 0x01, IN 0x82
EP_OUT = 0x01
EP_CMD_IN = 0x83  # bridge + non-blocking MOC
EP_BLOCK_IN = 0x84  # blocking MOC (verify, enroll)
EP_IMG_IN = 0x82  # image bulk read

TIMEOUT_MS = 5000
BLOCKING_TIMEOUT_MS = 10000
INTERFACE = 0

backend = libusb_package.get_libusb1_backend()


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
    MAX_ENROLLED = 0xDD


class InitStatus(IntEnum):
    INITIALIZING = 0x01
    READY = 0x03


ERRORS = {
    0x41: "Move slightly downwards",
    0x42: "Move slightly to the right",
    0x43: "Move slightly upwards",
    0x44: "Move slightly to the left",
    0xFB: "Sensor is dirty or wet",
    0xFD: "Finger not enrolled",
    0xFE: "Finger area not enough",
    0xDD: "Maximum number of enrolled fingers reached",
}


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


class ElanDevice:
    def __init__(self):
        self.dev: Optional[usb.core.Device] = None
        self.info = SensorInfo()
        self._max_packet_size = 64

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
            f"Device opened: {self.dev.idVendor:04X}:"
            f"{self.dev.idProduct:04X}"
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

    # ── Raw USB I/O ────────────────────────────────────────────

    def _write(self, data: bytes, timeout: int = TIMEOUT_MS):
        self.dev.write(EP_OUT, data, timeout=timeout)

    def _read(
        self, length: int, ep_in: int = EP_CMD_IN, timeout: int = TIMEOUT_MS
    ) -> bytes:
        buf_size = max(length, self._max_packet_size)
        data = bytes(self.dev.read(ep_in, buf_size, timeout=timeout))
        return data[:length]

    def _cmd(
        self,
        tx: bytes,
        rx_len: int,
        timeout: int = TIMEOUT_MS,
        ep_in: int = EP_CMD_IN,
        name: str = "",
    ) -> Optional[bytes]:
        label = name or f"0x{tx.hex()}"
        try:
            print(f"    [{label}] TX ({len(tx)}B): {tx.hex()}")
            self._write(tx, timeout=timeout)
            if rx_len == 0:
                return None
            time.sleep(0.05)
            data = self._read(rx_len, ep_in=ep_in, timeout=timeout)
            print(f"    [{label}] RX ({len(data)}B): {data.hex()}")
            return data
        except usb.core.USBTimeoutError:
            print(f"    [{label}] TIMEOUT")
            raise
        except usb.core.USBError as e:
            print(f"    [{label}] USB error: {e}")
            raise

    # ── MOC command helper (non-blocking → EP 0x83) ────────────

    def _moc_cmd(
        self,
        sub_cmd: int,
        payload: bytes = b"",
        rx_len: int = 2,
        timeout: int = TIMEOUT_MS,
        ep_in: int = EP_CMD_IN,
        name: str = "",
    ) -> bytes:
        tx = bytes([0x40, 0xFF, sub_cmd]) + payload
        resp = self._cmd(
            tx,
            rx_len,
            timeout=timeout,
            ep_in=ep_in,
            name=name or f"MOC 0x{sub_cmd:02X}",
        )
        if resp is None:
            return b""
        if len(resp) < 1 or resp[0] != 0x40:
            print(f"  [{name}] Unexpected response header: {resp.hex()}")
        return resp

    @staticmethod
    def _moc_result(resp: bytes) -> int:
        if len(resp) < 2:
            return -1
        return resp[1]

    @staticmethod
    def _moc_ok(resp: bytes) -> bool:
        return len(resp) >= 2 and resp[1] == MocResponse.SUCCESS

    @staticmethod
    def _get_error(code: int) -> Optional[str]:
        if (code & 0xF0) == 0:
            return None
        return ERRORS.get(code, f"Unknown error 0x{code:02X}")

    @staticmethod
    def _describe_moc_result(code: int) -> str:
        if 0x00 <= code <= 0x09:
            return f"match/success (finger {code})"
        return ERRORS.get(code, f"unknown (0x{code:02X})")

    # ── Abort ──────────────────────────────────────────────────

    def abort(self):
        """MOC 0x02 → cancel any in-progress operation."""
        try:
            self._moc_cmd(0x02, rx_len=2, ep_in=EP_CMD_IN, name="Abort")
            print("  Operation aborted.")
        except usb.core.USBError:
            pass  # best-effort

    # ── Bridge / low-level commands ────────────────────────────

    def get_fw_version(self) -> tuple[int, int]:
        """CMD: 40 19 → 2 bytes (raw, not BCD)."""
        resp = self._cmd(b"\x40\x19", 2, name="FW Version")
        major, minor = resp[0], resp[1]
        self.info.fw_major = major
        self.info.fw_minor = minor
        print(f"  FW Version: {major}.{minor}")
        return major, minor

    def get_boot_version(self) -> tuple[int, int]:
        """CMD: 40 1A → device returns up to 4 bytes, first 2 meaningful."""
        resp = self._cmd(b"\x40\x1a", 4, name="Boot Version")
        major, minor = resp[0], resp[1]
        self.info.boot_major = major
        self.info.boot_minor = minor
        print(f"  Boot Version: {major}.{minor}")
        return major, minor

    def get_fw_checksum(self) -> int:
        resp = self._cmd(b"\x40\x1b", 2, name="FW Checksum")
        checksum = (resp[0] << 8) | resp[1]
        self.info.checksum = checksum
        print(f"  FW Checksum: 0x{checksum:04X}")
        return checksum

    def get_sensor_dimensions(self) -> tuple[int, int]:
        """
        CMD: 00 0C → 4 bytes.
        Width = resp[0]+1, height = resp[2]+1 (confirmed by reference).
        """
        resp = self._cmd(b"\x00\x0c", 4, name="Sensor Dimensions")
        width = resp[0] + 1
        height = resp[2] + 1
        self.info.width = width
        self.info.height = height
        print(f"  Sensor: {width}x{height}")
        return width, height

    def read_register(self, reg: int) -> int:
        """CMD: 40 [reg+0x40] → 2 bytes, value is resp[0]."""
        if not 0 <= reg < 64:
            raise ValueError("Register out of range (0-63)")
        cmd = bytes([0x40, 0x40 + reg])
        resp = self._cmd(cmd, 2, name=f"RegRead 0x{reg:02X}")
        error = self._get_error(resp[1])
        if error:
            raise IOError(f"Failed to read register {reg}: {error}")
        return resp[0]

    def write_register(self, reg: int, value: int):
        cmd = bytes([0x40, (reg & 0x3F) + 0x80, value & 0xFF])
        self._cmd(cmd, 0, name=f"RegWrite 0x{reg:02X}=0x{value:02X}")

    def read_sensor_status(self) -> int:
        resp = self._cmd(b"\x40\x13", 1, name="Sensor SPI Status")
        print(f"  Sensor SPI status: 0x{resp[0]:02X}")
        return resp[0]

    def send_watchdog_reset(self):
        """CMD: 40 27 W D T R S T (8 bytes)."""
        cmd = b"\x40\x27WDTRST"
        assert len(cmd) == 8
        self._cmd(cmd, 0, name="WDT Reset")
        print("  Watchdog reset sent.")

    def switch_to_bootloader(self):
        cmd = b"\x42\x01RUNIAP"
        assert len(cmd) == 8
        self._cmd(cmd, 0, name="Switch Bootloader")
        print("  Switched to bootloader.")

    # ── MOC: Initialization ────────────────────────────────────

    def get_sensor_status(self) -> int:
        resp = self._moc_cmd(0x00, rx_len=2, name="Sensor Status")
        status = self._moc_result(resp)
        status_names = {
            InitStatus.READY: "ready",
            InitStatus.INITIALIZING: "booting",
        }
        name = status_names.get(status, f"unknown (0x{status:02X})")
        print(f"  Sensor status: {name}")
        return status

    def wait_sensor_ready(self, max_retries: int = 100) -> bool:
        for i in range(max_retries):
            try:
                resp = self._moc_cmd(0x00, rx_len=2, name="Poll Ready")
            except usb.core.USBTimeoutError:
                print(f"    Poll {i + 1}/{max_retries} timed out, retrying...")
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
        print("=== Device Initialization ===")
        self.get_fw_version()
        self.get_boot_version()
        self.get_fw_checksum()
        if not self.wait_sensor_ready():
            raise RuntimeError("Sensor failed to initialize")
        self.get_sensor_dimensions()
        print(f"  {self.info}")
        print("=== Initialization Complete ===")
        return self.info

    # ── MOC: Finger info & management ──────────────────────────

    def get_finger_count(self) -> int:
        """MOC 0x04 → enrolled finger count."""
        resp = self._moc_cmd(0x04, rx_len=2, name="Finger Count")
        count = self._moc_result(resp)
        print(f"  Enrolled fingers: {count}")
        return count

    def get_finger_info(self, finger_id: int) -> bytes:
        """
        MOC 0x12 [id] → 70 bytes: 40 <status> [68B data].
        If sensor returns 0xFF error, verify a finger to reset it.
        """
        resp = self._moc_cmd(
            0x12,
            payload=bytes([finger_id & 0xFF]),
            rx_len=70,
            name=f"Finger Info {finger_id}",
        )
        if len(resp) >= 2 and resp[1] == 0xFF:
            print(f"  Sensor error on finger_info — verify a finger to reset state")
        return resp

    def get_all_finger_info(self) -> list[bytes]:
        """Get info for all 10 finger slots."""
        results = []
        for fid in range(10):
            resp = self.get_finger_info(fid)
            results.append(resp)
        return results

    def remove_finger_by_index(self, index: int) -> bool:
        """MOC 0x05 [idx] [0x00] → delete finger by slot index."""
        payload = bytes([index & 0xFF, 0x00])
        resp = self._moc_cmd(0x05, payload=payload, rx_len=2, name="Delete")
        result = self._moc_result(resp)
        error = self._get_error(result)
        if result == MocResponse.SUCCESS:
            print(f"  Finger {index} deleted.")
            return True
        else:
            print(f"  Delete failed: {error or hex(result)}")
            return False

    def remove_finger_by_sid(self, sid: bytes) -> bool:
        """MOC 0x13 [69B SID] → remove finger by SID."""
        if len(sid) != 69:
            raise ValueError(f"SID must be 69 bytes, got {len(sid)}")
        resp = self._moc_cmd(0x13, payload=sid, rx_len=2, name="Delete by SID")
        result = self._moc_result(resp)
        if result == MocResponse.SUCCESS:
            print("  Finger removed by SID.")
            return True
        else:
            error = self._get_error(result)
            print(f"  Remove by SID failed: {error or hex(result)}")
            return False

    def remove_all_fingers(self):
        """
        Delete all enrolled fingers one by one (using SID).
        Mirrors the reference delete_all approach.
        """
        for fid in range(10):
            resp = self.get_finger_info(fid)
            if len(resp) >= 70 and resp[-1] == 0xFF:
                print(f"  Finger {fid} not enrolled, skipping.")
                continue
            # Construct SID from finger_info response
            sid = (struct.pack("B", 0xF0 | (fid + 5)) + resp[2:]).ljust(69, b"\x00")
            self.remove_finger_by_sid(sid)

    def wipe_all_fingers(self):
        """MOC 0x99 → bulk-delete all enrolled fingerprints."""
        self._moc_cmd(0x99, rx_len=0, name="Wipe All")
        print("  Wipe command sent, waiting for sensor...")
        # Sensor needs time to process wipe
        time.sleep(1.0)
        count = self.get_finger_count()
        print(f"  Enrolled after wipe: {count}")

    # ── MOC: Enrollment ────────────────────────────────────────

    def enroll_finger(self, user_data: bytes = b"") -> bool:
        """
        Full enrollment flow (from reference):
        1. Check enrolled count
        2. Verify finger to ensure not already enrolled
        3. 8 enroll touches (MOC 0x01 on EP 0x84)
        4. Check collision (MOC 0x10)
        5. Commit with SID (MOC 0x11)
        """
        # 1. Get current count → new finger ID
        resp = self._moc_cmd(0x04, rx_len=2, name="Enroll: Count")
        new_finger_id = enrolled = self._moc_result(resp)
        error = self._get_error(enrolled)
        if error:
            print(f"  Failed to get enrolled count: {error}")
            return False
        print(f"  Enrolled fingers: {enrolled}, new ID will be {new_finger_id}")

        # 2. Verify first — make sure this finger isn't already enrolled
        while True:
            print("  Place finger on reader (pre-enroll check)...")
            result, desc = self.verify_finger()
            if 0x00 <= result <= 0x09:
                print(f"  Finger already enrolled as {result}!")
                continue
            if result == MocResponse.VERIFY_FAILED:
                print("  Finger not yet enrolled — proceeding.")
                break
            error = self._get_error(result)
            if error:
                print(f"  {error}")
                continue
            break

        # 3. Enroll touches (8 required)
        total_attempts = 8
        attempts_done = 0
        while attempts_done < total_attempts:
            print(f"  Place finger on reader [{attempts_done + 1}/{total_attempts}]")
            payload = struct.pack(
                "BBBB",
                new_finger_id,
                total_attempts,
                attempts_done,
                0,
            )
            resp = self._moc_cmd(
                0x01,
                payload=payload,
                rx_len=2,
                timeout=BLOCKING_TIMEOUT_MS,
                ep_in=EP_BLOCK_IN,  # enroll reads from EP 0x84
                name="Enroll Touch",
            )
            result = self._moc_result(resp)
            if result == MocResponse.SUCCESS:
                attempts_done += 1
                print(f"    Touch accepted ({attempts_done}/{total_attempts})")
            elif result == MocResponse.MAX_ENROLLED:
                print("  Maximum enrolled fingers reached!")
                return False
            else:
                error = self._get_error(result)
                desc = self._describe_moc_result(result)
                print(f"    Touch rejected: {error or desc} (0x{result:02X})")
                # Don't increment — retry this touch
                continue

        # 4. Check for collision / duplicate
        resp = self._moc_cmd(0x10, rx_len=3, name="Collision Check")
        result = self._moc_result(resp)
        if result != MocResponse.SUCCESS:
            colliding = resp[2] if len(resp) >= 3 else -1
            print(f"  Collision: finger already enrolled as {colliding}")
            return False
        print("  No collision detected.")

        # 5. Commit with SID
        sid = (struct.pack("B", 0xF0 | (new_finger_id + 5)) + user_data).ljust(
            69, b"\x00"
        )
        resp = self._moc_cmd(0x11, payload=sid, rx_len=2, name="Commit Enroll")
        result = self._moc_result(resp)
        if result == MocResponse.SUCCESS:
            print("  Enrollment successful!")
            return True
        else:
            print(f"  Commit failed: 0x{result:02X}")
            return False

    # ── MOC: Verification ──────────────────────────────────────

    def verify_finger(self) -> tuple[int, str]:
        """
        MOC 0x03 → blocks until finger placed.
        Reads from EP 0x84 (blocking endpoint).
        Returns (result_code, description).
        """
        resp = self._moc_cmd(
            0x03,
            rx_len=2,
            timeout=BLOCKING_TIMEOUT_MS,
            ep_in=EP_BLOCK_IN,  # verify reads from EP 0x84
            name="Verify",
        )
        result = self._moc_result(resp)
        desc = self._describe_moc_result(result)
        print(f"  Verify result: 0x{result:02X} ({desc})")
        return result, desc

    def verify_loop(self) -> int:
        """Keep trying until a finger is recognized."""
        while True:
            print("  Place finger on reader...")
            result, desc = self.verify_finger()
            if 0x00 <= result <= 0x09:
                print(f"  Recognized finger: {result}")
                return result
            error = self._get_error(result)
            if error:
                print(f"  {error}")

    def verify_and_identify(self) -> Optional[tuple[int, bytes]]:
        """
        Verify, then retrieve SID on match.
        Returns (finger_index, sid_bytes) or None.
        """
        result, desc = self.verify_finger()
        if 0x00 <= result <= 0x09:
            info = self.get_finger_info(result)
            if len(info) >= 70:
                return result, info[2:]
        return None

    # ── MOC: Sensor mode ───────────────────────────────────────

    def set_sensor_mode(self, mode: int) -> bool:
        """MOC 0x14 [mode] → set FW sensor mode (0=normal, 1=VBS)."""
        payload = bytes([mode & 0xFF])
        resp = self._moc_cmd(0x14, payload=payload, rx_len=4, name="Set Mode")
        result = self._moc_result(resp)
        print(f"  Set mode {mode}: 0x{result:02X}")
        return result == MocResponse.SUCCESS

    # ── Image capture ──────────────────────────────────────────

    def capture_image(self) -> Optional[bytes]:
        """
        Capture fingerprint image:
        1. TX: 00 09 (trigger)
        2. RX from EP 0x82: width * height * 2 bytes (16-bit LE pixels)
        """
        w, h = self.info.width, self.info.height
        if w == 0 or h == 0:
            raise RuntimeError("Call initialize() first")

        read_size = w * h * 2

        # Trigger capture
        self._write(b"\x00\x09")
        time.sleep(0.05)

        # Read image from EP 0x82
        raw = self._read(read_size, ep_in=EP_IMG_IN, timeout=TIMEOUT_MS)
        print(f"  Captured image: {len(raw)} bytes ({w}x{h})")
        return bytes(raw)

    def capture_to_png(self, path: str):
        """Capture and save as normalized 8-bit grayscale PNG."""
        try:
            from PIL import Image
        except ImportError:
            raise ImportError("Pillow is required: pip install Pillow")

        raw = self.capture_image()
        if raw is None:
            raise RuntimeError("Capture failed")

        w, h = self.info.width, self.info.height
        img = Image.frombuffer("I;16L", (w, h), raw)

        # Find min/max for normalization
        min_val = 0xFFFF
        max_val = 0
        for y in range(h):
            for x in range(w):
                v = img.getpixel((x, y))
                min_val = min(min_val, v)
                max_val = max(max_val, v)

        # Normalize to 8-bit grayscale
        diff = max_val - min_val
        if diff == 0:
            diff = 1
        img_8b = Image.new("L", (w, h))
        for y in range(h):
            for x in range(w):
                v = img.getpixel((x, y))
                img_8b.putpixel((x, y), int((v - min_val) * 255 / diff))

        img_8b.save(path, "PNG")
        print(f"  Saved to {path}")

    # ── SDCP commands ──────────────────────────────────────────

    def get_fw_app_key(self) -> Optional[tuple[bytes, bytes]]:
        resp = self._moc_cmd(0x0D, rx_len=66, name="FW App Key")
        if self._moc_ok(resp) and len(resp) >= 66:
            x, y = resp[2:34], resp[34:66]
            print(f"  FW App Key X: {x.hex()}")
            print(f"  FW App Key Y: {y.hex()}")
            return x, y
        return None

    def get_fw_authorized_info(self, challenge: bytes) -> Optional[tuple[bytes, bytes]]:
        if len(challenge) != 32:
            raise ValueError("Challenge must be 32 bytes")
        for attempt in range(10):
            resp = self._moc_cmd(
                0x0C, payload=challenge, rx_len=66, name="FW Auth Info"
            )
            result = self._moc_result(resp)
            if result == MocResponse.SUCCESS and len(resp) >= 66:
                return resp[2:34], resp[34:66]
            elif result == MocResponse.NOT_READY:
                time.sleep(0.3)
            else:
                return None
        return None

    def receive_enroll_nonce(self) -> Optional[bytes]:
        for attempt in range(10):
            resp = self._moc_cmd(0x09, rx_len=34, name="Enroll Nonce")
            result = self._moc_result(resp)
            if result == MocResponse.SUCCESS and len(resp) >= 34:
                return resp[2:34]
            elif result == MocResponse.NOT_READY:
                time.sleep(0.3)
            else:
                return None
        return None

    # ── Register dump ──────────────────────────────────────────

    def dump_all_registers(self) -> dict[int, int]:
        regs = {}
        print("       x0  x1  x2  x3  x4  x5  x6  x7\n")
        for i in range(8):
            print(f"  {i}x ", end="")
            for j in range(8):
                reg = i * 8 + j
                val = self.read_register(reg)
                regs[reg] = val
                print(f"  {val:02x}", end="")
            print()
        return regs

    # ── Raw command ────────────────────────────────────────────

    def raw_command(
        self, data: bytes, ep_in: int = EP_CMD_IN, rx_len: int = 64
    ) -> bytes:
        self._write(data)
        time.sleep(0.05)
        return self._read(rx_len, ep_in=ep_in)


# ── Main ───────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    commands_list = """
Commands:
  info
  fw_ver
  boot_ver
  checksum
  status
  spi_status
  enrolled_count
  finger_info <id>
  finger_info_all
  enroll [--user TEXT]
  verify
  identify
  verify_loop
  delete <id>
  delete_all
  wipe_all
  capture <png>
  read_reg <reg>
  dump_regs
  raw [--ep-in EP] [--rx-len N] <hex...>
  soft_reset
  hard_reset
  bootloader
  set_mode <mode>

Examples:
  python elan_04f3_0c4c.py info
  python elan_04f3_0c4c.py enroll --user myuser
  python elan_04f3_0c4c.py capture fingerprint.png
  python elan_04f3_0c4c.py raw 40 19
""".strip("\n")

    parser = argparse.ArgumentParser(
        prog="elan-fingerprint",
        description="ELAN fingerprint sensor tool",
        epilog=commands_list,
        formatter_class=argparse.RawTextHelpFormatter,
    )

    # IMPORTANT: do NOT require a subcommand; we’ll start an interactive prompt
    # if none is provided.
    sub = parser.add_subparsers(
        dest="command",
        metavar="command",
        title="commands",
        required=False,
    )

    # Info / status
    sub.add_parser("info", help="Show device and firmware info")
    sub.add_parser("fw_ver", help="Print firmware version")
    sub.add_parser("boot_ver", help="Print bootloader version")
    sub.add_parser("checksum", help="Print firmware checksum")
    sub.add_parser("status", help="Print sensor status")
    sub.add_parser("spi_status", help="Print sensor SPI status")

    # Fingers
    sub.add_parser("enrolled_count", help="Print enrolled finger count")
    p = sub.add_parser("finger_info", help="Show finger info for a slot")
    p.add_argument("id", type=int, help="Finger slot ID (0-9)")
    sub.add_parser("finger_info_all", help="Show info for all 10 slots")

    # Enroll / verify
    p = sub.add_parser("enroll", help="Enroll a new finger")
    p.add_argument("--user", default="", help="User data string to embed in SID")
    sub.add_parser("verify", help="Verify a finger (single attempt)")
    sub.add_parser("identify", help="Verify and retrieve SID")
    sub.add_parser("verify_loop", help="Keep verifying until recognized")

    # Delete
    p = sub.add_parser("delete", help="Delete a finger by slot index")
    p.add_argument("id", type=int, help="Finger slot ID (0-9)")
    sub.add_parser("delete_all", help="Delete all fingers (by SID)")
    sub.add_parser("wipe_all", help="Bulk-wipe all enrolled fingerprints")

    # Capture
    p = sub.add_parser("capture", help="Capture fingerprint image to PNG")
    p.add_argument("png", help="Output PNG file path")

    # Registers
    p = sub.add_parser("read_reg", help="Read a single register")
    p.add_argument("reg", type=int, help="Register number (0-63)")
    sub.add_parser("dump_regs", help="Dump registers as 8x8 table")

    # Low-level
    p = sub.add_parser("raw", help="Send raw hex bytes and read response")
    p.add_argument("hex", nargs="+", help="Hex bytes (e.g. 40 19)")
    p.add_argument(
        "--ep-in",
        type=lambda x: int(x, 0),
        default=EP_CMD_IN,
        help=f"IN endpoint (default 0x{EP_CMD_IN:02X})",
    )
    p.add_argument("--rx-len", type=int, default=64, help="Response length")

    # Misc
    sub.add_parser("soft_reset", help="USB soft reset")
    sub.add_parser("hard_reset", help="Watchdog reset")
    sub.add_parser("bootloader", help="Switch to bootloader mode")
    p = sub.add_parser("set_mode", help="Set sensor mode")
    p.add_argument("mode", type=int, help="Mode (0=normal, 1=VBS)")

    return parser


def interactive_loop(parser: argparse.ArgumentParser):
    print("Interactive mode. Type 'help' to see commands, 'quit' to exit.")
    while True:
        try:
            line = input("elan> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return

        if not line:
            continue
        if line in {"q", "quit", "exit"}:
            return
        if line in {"h", "help", "?"}:
            parser.print_help()
            continue

        argv = shlex.split(line)
        try:
            args = parser.parse_args(argv)
        except SystemExit:
            # argparse throws SystemExit on parse errors; keep the REPL alive.
            continue

        if args.command is None:
            parser.print_help()
            continue

        run_command(args)


def run_command(args):
    with ElanDevice() as sensor:
        try:
            if args.command == "info":
                sensor.initialize()
                print()
                print(f"  VID:PID:  {VENDOR_ID:04X}:{PRODUCT_ID:04X}")
                print(f"  Firmware: {sensor.info.fw_major}.{sensor.info.fw_minor}")
                print(f"  Boot:     {sensor.info.boot_major}.{sensor.info.boot_minor}")
                print(f"  Checksum: 0x{sensor.info.checksum:04X}")
                print(f"  Sensor:   {sensor.info.width}x{sensor.info.height}")
                count = sensor.get_finger_count()
                print(f"  Enrolled: {count}")

            elif args.command == "fw_ver":
                major, minor = sensor.get_fw_version()
                print(f"Firmware version: {major}.{minor}")

            elif args.command == "boot_ver":
                major, minor = sensor.get_boot_version()
                print(f"Bootloader version: {major}.{minor}")

            elif args.command == "checksum":
                cs = sensor.get_fw_checksum()
                print(f"Firmware checksum: 0x{cs:04X}")

            elif args.command == "status":
                sensor.get_sensor_status()

            elif args.command == "spi_status":
                sensor.read_sensor_status()

            elif args.command == "enrolled_count":
                sensor.initialize()
                sensor.get_finger_count()

            elif args.command == "finger_info":
                sensor.initialize()
                resp = sensor.get_finger_info(args.id)
                print(f"Finger info {args.id}:")
                _hexdump(resp)

            elif args.command == "finger_info_all":
                sensor.initialize()
                for fid in range(10):
                    resp = sensor.get_finger_info(fid)
                    print(f"Finger info {fid}:")
                    _hexdump(resp)

            elif args.command == "enroll":
                sensor.initialize()
                sensor.enroll_finger(user_data=args.user.encode())

            elif args.command == "verify":
                sensor.initialize()
                result, desc = sensor.verify_finger()
                print(f"Result: 0x{result:02X} ({desc})")

            elif args.command == "identify":
                sensor.initialize()
                match = sensor.verify_and_identify()
                if match:
                    idx, sid = match
                    print(f"Matched finger {idx}, SID:")
                    _hexdump(sid)
                else:
                    print("No match.")

            elif args.command == "verify_loop":
                sensor.initialize()
                result = sensor.verify_loop()
                print(f"Recognized finger: {result}")

            elif args.command == "delete":
                sensor.initialize()
                sensor.remove_finger_by_index(args.id)

            elif args.command == "delete_all":
                sensor.initialize()
                sensor.remove_all_fingers()

            elif args.command == "wipe_all":
                sensor.initialize()
                sensor.wipe_all_fingers()

            elif args.command == "capture":
                sensor.initialize()
                sensor.capture_to_png(args.png)

            elif args.command == "read_reg":
                val = sensor.read_register(args.reg)
                print(f"Register {args.reg}: 0x{val:02X}")

            elif args.command == "dump_regs":
                sensor.dump_all_registers()

            elif args.command == "raw":
                payload = bytes(int(h, 16) for h in args.hex)
                print(f"Sending [{len(payload)}B]:")
                _hexdump(payload)
                resp = sensor.raw_command(payload, ep_in=args.ep_in, rx_len=args.rx_len)
                print(f"Received [{len(resp)}B]:")
                _hexdump(resp)

            elif args.command == "soft_reset":
                sensor.dev.reset()
                print("USB device reset.")

            elif args.command == "hard_reset":
                sensor.send_watchdog_reset()

            elif args.command == "bootloader":
                sensor.switch_to_bootloader()

            elif args.command == "set_mode":
                sensor.initialize()
                sensor.set_sensor_mode(args.mode)

            else:
                raise ValueError(f"Unknown command: {args.command}")

        except (Exception, KeyboardInterrupt):
            print("\nAborting...")
            sensor.abort()
            raise


def main(argv=None):
    parser = build_parser()
    argv = sys.argv[1:] if argv is None else argv

    if not argv:
        # No args => interactive prompt instead of argparse error
        interactive_loop(parser)
        return

    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return

    run_command(args)


if __name__ == "__main__":
    main()
