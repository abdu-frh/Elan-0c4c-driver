#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ELAN 04F3:0C4C (ELAN:ARM-M4) — pyusb/libusb Match-on-Chip PoC

Confirmed working behaviors incorporated:
- Bulk OUT: 0x01
- Bulk IN: typically 0x83 for both "bridge" and MOC.
- Some units use additional IN endpoints (often 0x84 for blocking verify/enroll,
  0x82 for image). This script auto-discovers and falls back safely.
- libusb overflow guard: always read at least wMaxPacketSize then slice.
- Boot version (40 1A) may return 4 bytes; first two are meaningful.
- Register reads return 2 bytes: <value> 00 (padding).

Dependencies:
- pyusb
- libusb-package (for a bundled libusb backend), optional but recommended
"""

from __future__ import annotations

import platform
import time
from dataclasses import dataclass
from enum import IntEnum
from typing import Optional

import libusb_package
import usb.core
import usb.util

VENDOR_ID = 0x04F3
PRODUCT_ID = 0x0C4C

INTERFACE = 0

EP_OUT = 0x01

# Known/common IN endpoints for this ELAN family.
EP_IN_DEFAULT = 0x83
EP_IN_MOC_BLOCK_DEFAULT = 0x84
EP_IN_IMG_DEFAULT = 0x82

TIMEOUT_MS = 5000
BLOCKING_TIMEOUT_MS = 30000

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
    MAX_ENROLLED = 0xDD  # observed in some PoCs


class InitStatus(IntEnum):
    INITIALIZING = 0x01
    READY = 0x03


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

    # Some firmwares report (N-1) for capture sizing (seen in other PoCs).
    @property
    def capture_width(self) -> int:
        return self.width + 1 if self.width else 0

    @property
    def capture_height(self) -> int:
        return self.height + 1 if self.height else 0

    def __repr__(self) -> str:
        return (
            f"SensorInfo(fw={self.fw_major}.{self.fw_minor}, "
            f"boot={self.boot_major}.{self.boot_minor}, "
            f"checksum=0x{self.checksum:04X}, "
            f"dimensions={self.width}x{self.height})"
        )


class ElanDevice:
    def __init__(self) -> None:
        self.dev: Optional[usb.core.Device] = None
        self.info = SensorInfo()

        # Endpoint choices (auto-discovered in open()).
        self.ep_cmd_in = EP_IN_DEFAULT
        self.ep_moc_in = EP_IN_DEFAULT
        self.ep_moc_block_in = EP_IN_MOC_BLOCK_DEFAULT
        self.ep_img_in = EP_IN_IMG_DEFAULT

        self._max_packet_size = 64

    # --- lifecycle -------------------------------------------------

    def open(self) -> None:
        self.dev = usb.core.find(
            backend=backend,
            idVendor=VENDOR_ID,
            idProduct=PRODUCT_ID,
        )
        if self.dev is None:
            raise ValueError("ELAN device not found (04F3:0C4C)")

        if platform.system() == "Linux":
            if self.dev.is_kernel_driver_active(INTERFACE):
                self.dev.detach_kernel_driver(INTERFACE)

        self.dev.set_configuration()
        usb.util.claim_interface(self.dev, INTERFACE)

        cfg = self.dev.get_active_configuration()
        intf = cfg[(INTERFACE, 0)]

        eps_in = [ep for ep in intf.endpoints() if ep.bEndpointAddress & 0x80]
        in_addrs = {ep.bEndpointAddress for ep in eps_in}

        # Max packet size (take from 0x83 if present, else first IN ep, else 64).
        ep83 = next((ep for ep in eps_in if ep.bEndpointAddress == 0x83), None)
        if ep83 is not None:
            self._max_packet_size = int(ep83.wMaxPacketSize)
        elif eps_in:
            self._max_packet_size = int(eps_in[0].wMaxPacketSize)
        else:
            self._max_packet_size = 64

        # Command + MOC on this device are typically on 0x83.
        self.ep_cmd_in = 0x83 if 0x83 in in_addrs else (eps_in[0].bEndpointAddress)
        self.ep_moc_in = self.ep_cmd_in

        # Blocking MOC responses sometimes come on 0x84. If absent, use ep_moc_in.
        self.ep_moc_block_in = 0x84 if 0x84 in in_addrs else self.ep_moc_in

        # Images sometimes come on 0x82. If absent, use ep_cmd_in.
        self.ep_img_in = 0x82 if 0x82 in in_addrs else self.ep_cmd_in

        print(
            f"Device opened: {self.dev.idVendor:04X}:{self.dev.idProduct:04X} "
            f"(wMaxPacketSize={self._max_packet_size})"
        )
        print(
            "Endpoints:"
            f" OUT=0x{EP_OUT:02X}"
            f" CMD_IN=0x{self.ep_cmd_in:02X}"
            f" MOC_IN=0x{self.ep_moc_in:02X}"
            f" MOC_BLOCK_IN=0x{self.ep_moc_block_in:02X}"
            f" IMG_IN=0x{self.ep_img_in:02X}"
        )

    def close(self) -> None:
        if self.dev is None:
            return
        try:
            usb.util.release_interface(self.dev, INTERFACE)
        finally:
            usb.util.dispose_resources(self.dev)
            self.dev = None
            print("Device released.")

    def __enter__(self) -> "ElanDevice":
        self.open()
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    # --- raw USB I/O ----------------------------------------------

    def _write(self, data: bytes, timeout: int = TIMEOUT_MS) -> None:
        if self.dev is None:
            raise RuntimeError("Device not open")
        self.dev.write(EP_OUT, data, timeout=timeout)

    def _read(self, ep_in: int, length: int, timeout: int = TIMEOUT_MS) -> bytes:
        """
        Bulk IN read with overflow protection:
        always read >= wMaxPacketSize, then slice to requested length.
        """
        if self.dev is None:
            raise RuntimeError("Device not open")
        buf_size = max(length, self._max_packet_size)
        data = bytes(self.dev.read(ep_in, buf_size, timeout=timeout))
        return data[:length]

    def _cmd(
        self,
        tx: bytes,
        rx_len: int,
        timeout: int = TIMEOUT_MS,
        ep_in: Optional[int] = None,
        name: str = "",
        delay_s: float = 0.05,
    ) -> Optional[bytes]:
        label = name or f"0x{tx.hex()}"
        if ep_in is None:
            ep_in = self.ep_cmd_in

        try:
            print(f"    [{label}] TX ({len(tx)}B): {tx.hex()}")
            self._write(tx, timeout=timeout)
            if rx_len == 0:
                return None
            time.sleep(delay_s)
            data = bytes(
                self.dev.read(  # type: ignore[union-attr]
                    ep_in,
                    max(rx_len, self._max_packet_size),
                    timeout=timeout,
                )
            )
            print(f"    [{label}] RX ({len(data)}B): {data.hex()}")
            return data[:rx_len]
        except usb.core.USBTimeoutError:
            print(f"    [{label}] TIMEOUT after {timeout}ms")
            raise
        except usb.core.USBError as e:
            print(f"    [{label}] USB error: {e}")
            raise

    # --- MOC helpers ----------------------------------------------

    def _moc_cmd(
        self,
        sub_cmd: int,
        payload: bytes = b"",
        rx_len: int = 2,
        timeout: int = TIMEOUT_MS,
        name: str = "",
        ep_in: Optional[int] = None,
    ) -> bytes:
        """
        MOC command framing (confirmed):
          TX: 40 FF <subcmd> [payload...]
          RX: 40 <result> [data...]
        """
        tx = bytes([0x40, 0xFF, sub_cmd & 0xFF]) + payload
        resp = self._cmd(
            tx,
            rx_len,
            timeout=timeout,
            ep_in=ep_in if ep_in is not None else self.ep_moc_in,
            name=name or f"MOC 0x{sub_cmd:02X}",
        )
        return resp or b""

    @staticmethod
    def _moc_result(resp: bytes) -> int:
        return resp[1] if len(resp) >= 2 else -1

    @staticmethod
    def _moc_ok(resp: bytes) -> bool:
        return len(resp) >= 2 and resp[0] == 0x40 and resp[1] == 0x00

    # --- bridge / low-level commands ------------------------------

    @staticmethod
    def _bcd_to_int(b: int) -> int:
        return ((b >> 4) & 0x0F) * 10 + (b & 0x0F)

    def get_fw_version(self) -> tuple[int, int]:
        resp = self._cmd(b"\x40\x19", 2, name="FW Version")
        assert resp is not None
        major = self._bcd_to_int(resp[0])
        minor = self._bcd_to_int(resp[1])
        self.info.fw_major = major
        self.info.fw_minor = minor
        print(f"  FW Version: {major}.{minor}")
        return major, minor

    def get_boot_version(self) -> tuple[int, int]:
        # Device may return 4 bytes; first two are meaningful on known units.
        resp = self._cmd(b"\x40\x1a", 4, name="Boot Version")
        assert resp is not None
        major = self._bcd_to_int(resp[0])
        minor = self._bcd_to_int(resp[1])
        self.info.boot_major = major
        self.info.boot_minor = minor
        print(f"  Boot Version: {major}.{minor}")
        return major, minor

    def get_fw_checksum(self) -> int:
        resp = self._cmd(b"\x40\x1b", 2, name="FW Checksum")
        assert resp is not None
        checksum = (resp[0] << 8) | resp[1]
        self.info.checksum = checksum
        print(f"  FW Checksum: 0x{checksum:04X}")
        return checksum

    def get_sensor_dimensions(self) -> tuple[int, int]:
        resp = self._cmd(b"\x00\x0c", 4, name="Sensor Dimensions")
        assert resp is not None
        w = resp[0] | (resp[1] << 8)
        h = resp[2] | (resp[3] << 8)

        # Sanity fallback (rare).
        if w == 0 or h == 0 or w > 500 or h > 500:
            w = (resp[0] << 8) | resp[1]
            h = (resp[2] << 8) | resp[3]

        self.info.width = w
        self.info.height = h
        print(f"  Sensor: {w}x{h}")
        return w, h

    def read_register(self, reg: int) -> int:
        """
        Register read (confirmed):
          TX: 40 (0x40 + reg)
          RX: 2 bytes: <value> 00
        """
        if not (0 <= reg <= 0x3F):
            raise ValueError("reg must be 0x00..0x3F")
        cmd = bytes([0x40, (reg & 0x3F) + 0x40])
        resp = self._cmd(cmd, 2, name=f"RegRead 0x{reg:02X}")
        assert resp is not None
        return resp[0]

    def write_register(self, reg: int, value: int) -> None:
        cmd = bytes([0x40, (reg & 0x3F) + 0x80, value & 0xFF])
        self._cmd(cmd, 0, name=f"RegWrite 0x{reg:02X}=0x{value:02X}")

    def send_watchdog_reset(self) -> None:
        cmd = b"\x40\x27WDTRST"
        assert len(cmd) == 8
        self._cmd(cmd, 0, name="WDT Reset")
        print("  Watchdog reset sent.")

    def switch_to_bootloader(self) -> None:
        cmd = b"\x42\x01RUNIAP"
        assert len(cmd) == 8
        self._cmd(cmd, 0, name="Switch Bootloader")
        print("  Switched to bootloader.")

    # --- init / status --------------------------------------------

    def get_sensor_status(self) -> int:
        resp = self._moc_cmd(0x00, rx_len=2, name="MOC Status")
        status = self._moc_result(resp)
        status_names = {
            InitStatus.READY: "ready",
            InitStatus.INITIALIZING: "booting",
        }
        print(f"  Sensor status: {status_names.get(status, hex(status))}")
        return status

    def wait_sensor_ready(self, max_retries: int = 100) -> bool:
        for i in range(max_retries):
            try:
                resp = self._moc_cmd(0x00, rx_len=2, name="Poll Ready")
            except usb.core.USBTimeoutError:
                print(f"    Poll {i + 1}/{max_retries} timeout; retrying...")
                time.sleep(0.5)
                continue

            status = self._moc_result(resp)
            if status == InitStatus.READY:
                print(f"  Sensor ready (attempt {i + 1})")
                return True

            if status == InitStatus.INITIALIZING:
                time.sleep(0.03)
                continue

            print(f"    Unexpected init status: 0x{status:02X}")
            time.sleep(0.03)

        print("  Sensor did not become ready.")
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

    # --- finger management ----------------------------------------

    def get_finger_count(self) -> int:
        resp = self._moc_cmd(0x04, rx_len=2, name="Finger Count")
        count = self._moc_result(resp)
        print(f"  Enrolled fingers: {count}")
        return count

    def remove_finger_by_index(self, index: int) -> bool:
        """
        Matches the usb1 PoC behavior: payload is [id, 0x00].
        """
        payload = bytes([index & 0xFF, 0x00])
        resp = self._moc_cmd(0x05, payload=payload, rx_len=2, name="Delete by ID")
        result = self._moc_result(resp)
        if result in (MocResponse.SUCCESS, MocResponse.NOT_READY):
            print(f"  Finger {index} deleted (result=0x{result:02X}).")
            return True
        print(f"  Delete failed: 0x{result:02X}")
        return False

    def remove_all_fingers(self) -> None:
        self._moc_cmd(0x99, rx_len=0, name="Wipe All")
        print("  Wipe-all sent.")

    def get_finger_info(self, index: int) -> Optional[bytes]:
        """
        MOC 0x12 [idx] -> 70 bytes: 40 00 [68 bytes...]
        Returns the 68 data bytes (resp[2:]) or None on failure.
        """
        payload = bytes([index & 0xFF])
        resp = self._moc_cmd(0x12, payload=payload, rx_len=70, name="Finger Info")
        if self._moc_ok(resp) and len(resp) >= 70:
            data68 = resp[2:70]
            print(f"  Finger info {index}: {data68.hex()}")
            return data68
        print(f"  Finger info failed: 0x{self._moc_result(resp):02X}")
        return None

    @staticmethod
    def build_subsid_payload(
        finger_id: int,
        info68: bytes,
        user_data: bytes = b"",
    ) -> bytes:
        """
        Payload style used by some PoCs for commit/delete_subsid:
          [tag (1 byte)] + [user_data?] + [info68] padded/truncated to 69 bytes
        """
        if len(info68) != 68:
            raise ValueError(f"info68 must be 68 bytes, got {len(info68)}")
        tag = bytes([0xF0 | ((finger_id + 5) & 0x0F)])
        raw = tag + (user_data or b"") + info68
        return raw[:69].ljust(69, b"\x00")

    def remove_finger_by_subsid(self, subsid69: bytes) -> bool:
        """
        MOC 0x13 [69B subsid] -> 2 bytes
        """
        if len(subsid69) != 69:
            raise ValueError(f"subsid must be 69 bytes, got {len(subsid69)}")
        resp = self._moc_cmd(
            0x13,
            payload=subsid69,
            rx_len=2,
            name="Delete by SubSID",
        )
        result = self._moc_result(resp)
        if result in (MocResponse.SUCCESS, MocResponse.NOT_READY):
            print("  Deleted by SubSID.")
            return True
        print(f"  Delete by SubSID failed: 0x{result:02X}")
        return False

    # --- enroll/verify --------------------------------------------

    def enroll_finger(
        self,
        index: int,
        total_attempts: int = 8,
        attempt_index: int = 0,
        flag: int = 0x00,
    ) -> tuple[int, str]:
        """
        MOC 0x01 [id] [total] [attempt_index] [flag] -> 2 bytes

        Note: On some units this blocking response arrives on 0x84. We read from
        self.ep_moc_block_in for enroll/verify to be safe.
        """
        payload = bytes(
            [
                index & 0xFF,
                total_attempts & 0xFF,
                attempt_index & 0xFF,
                flag & 0xFF,
            ]
        )
        resp = self._moc_cmd(
            0x01,
            payload=payload,
            rx_len=2,
            timeout=BLOCKING_TIMEOUT_MS,
            name="Enroll",
            ep_in=self.ep_moc_block_in,
        )
        code = self._moc_result(resp)
        desc = self._describe_moc_result(code)
        print(f"  Enroll result: 0x{code:02X} ({desc})")
        return code, desc

    def commit_enroll_subsid(self, subsid69: bytes) -> bool:
        """
        MOC 0x11 [69B subsid] -> 2 bytes
        """
        if len(subsid69) != 69:
            raise ValueError(f"subsid must be 69 bytes, got {len(subsid69)}")
        resp = self._moc_cmd(0x11, payload=subsid69, rx_len=2, name="Commit")
        ok = self._moc_ok(resp)
        print(f"  Commit: {'OK' if ok else 'FAIL'} (0x{self._moc_result(resp):02X})")
        return ok

    def cancel_operation(self) -> None:
        self._moc_cmd(0x02, rx_len=0, name="Cancel")
        print("  Operation cancelled.")

    def verify_finger(self) -> tuple[int, str]:
        """
        MOC 0x03 -> 2 bytes, blocks until finger.
        Returns (code, description). Match codes 0x00..0x09 indicate finger index.
        """
        print("  Waiting for finger...")
        resp = self._moc_cmd(
            0x03,
            rx_len=2,
            timeout=BLOCKING_TIMEOUT_MS,
            name="Verify",
            ep_in=self.ep_moc_block_in,
        )
        code = self._moc_result(resp)
        desc = self._describe_moc_result(code)
        print(f"  Verify result: 0x{code:02X} ({desc})")
        return code, desc

    def get_sid(self, index: int) -> Optional[bytes]:
        """
        MOC 0x12 [idx] -> 70 bytes: 40 00 [68B]
        Returns the 68B SID blob.
        """
        payload = bytes([index & 0xFF])
        resp = self._moc_cmd(0x12, payload=payload, rx_len=70, name="Get SID")
        if self._moc_ok(resp) and len(resp) >= 70:
            sid = resp[2:70]
            return sid
        return None

    def verify_and_identify(self) -> Optional[tuple[int, bytes]]:
        code, _ = self.verify_finger()
        if 0x00 <= code <= 0x09:
            sid = self.get_sid(code)
            if sid is not None:
                return code, sid
        return None

    def set_sensor_mode(self, mode: int) -> bool:
        resp = self._moc_cmd(
            0x14,
            payload=bytes([mode & 0xFF]),
            rx_len=2,
            name="Set Mode",
        )
        result = self._moc_result(resp)
        print(f"  Set mode {mode}: 0x{result:02X}")
        return result == MocResponse.SUCCESS

    # --- SDCP/secure (optional) -----------------------------------

    def get_fw_app_key(self) -> Optional[tuple[bytes, bytes]]:
        """
        MOC 0x0D -> 66 bytes: 40 00 [32B X] [32B Y]
        Some units return all zeros (not provisioned).
        """
        resp = self._moc_cmd(0x0D, rx_len=66, name="FW App Key")
        if self._moc_ok(resp) and len(resp) >= 66:
            x = resp[2:34]
            y = resp[34:66]
            print(f"  FW App Key X: {x.hex()}")
            print(f"  FW App Key Y: {y.hex()}")
            return x, y
        print(f"  FW App Key failed: 0x{self._moc_result(resp):02X}")
        return None

    # --- image capture --------------------------------------------

    def capture_start(self) -> None:
        self._cmd(b"\x00\x09", 0, name="Capture Start")

    def capture_fingerprint_image(self) -> bytes:
        """
        Full capture:
          00 09
          02 0A then read w*h*2 bytes (some units use (w+1)*(h+1)).
        """
        if self.info.width == 0 or self.info.height == 0:
            raise RuntimeError("Call initialize() first (need sensor dimensions).")

        self.capture_start()
        time.sleep(0.05)

        # Prefer (+1) sizing first; if overflow occurs, fall back to raw w*h.
        w1 = self.info.capture_width or self.info.width
        h1 = self.info.capture_height or self.info.height
        size1 = w1 * h1 * 2

        self._write(b"\x02\x0a")
        time.sleep(0.05)

        try:
            raw = self._read(self.ep_img_in, size1, timeout=TIMEOUT_MS)
            print(f"  Fingerprint image: {len(raw)} bytes ({w1}x{h1})")
            return raw
        except usb.core.USBError as e:
            if "Overflow" not in str(e):
                raise

        # Retry with raw width/height.
        w2 = self.info.width
        h2 = self.info.height
        size2 = w2 * h2 * 2

        raw = self._read(self.ep_img_in, size2, timeout=TIMEOUT_MS)
        print(f"  Fingerprint image: {len(raw)} bytes ({w2}x{h2})")
        return raw

    @staticmethod
    def pixels_from_raw(raw: bytes, width: int, height: int) -> list[int]:
        pixels: list[int] = []
        limit = min(len(raw), width * height * 2)
        for i in range(0, limit, 2):
            pixels.append(raw[i] | (raw[i + 1] << 8))
        return pixels

    # --- register dump --------------------------------------------

    def dump_all_registers(self) -> dict[int, int]:
        regs: dict[int, int] = {}
        for r in range(0x40):
            regs[r] = self.read_register(r)
        print(f"  Dumped {len(regs)} registers.")
        return regs

    # --- misc ------------------------------------------------------

    @staticmethod
    def _describe_moc_result(code: int) -> str:
        if 0x00 <= code <= 0x09:
            return f"match/success (finger {code})"
        descriptions = {
            0xFE: "not ready / area not enough",
            0xFD: "verify failed (no match / not enrolled)",
            0xFC: "HLK / image quality failure",
            0xFB: "dirty sensor",
            0xFF: "error",
            0x41: "finger too high",
            0x42: "finger too left",
            0x43: "finger too low",
            0x44: "finger too right",
            0xDD: "maximum enrolled fingers reached",
        }
        return descriptions.get(code, f"unknown (0x{code:02X})")


if __name__ == "__main__":
    with ElanDevice() as sensor:
        sensor.initialize()

        # Example: set verify-ish mode (device-dependent).
        # 0 idle, 1 capture, 2 low power, 3 verify (common guess)
        sensor.set_sensor_mode(3)

        match = sensor.verify_and_identify()
        if match is not None:
            idx, sid = match
            print(f"Matched finger {idx}, SID: {sid.hex()}")
        else:
            print("No match.")

        # Uncomment to test:
        # print("Finger count:", sensor.get_finger_count())
        # regs = sensor.dump_all_registers()
        # raw = sensor.capture_fingerprint_image()
        # pixels = sensor.pixels_from_raw(
        #     raw,
        #     sensor.info.capture_width or sensor.info.width,
        #     sensor.info.capture_height or sensor.info.height,
        # )
        # print("Pixels:", len(pixels))
