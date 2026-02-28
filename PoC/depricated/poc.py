import platform
import time
from dataclasses import dataclass

import libusb_package
import usb.core
import usb.util

VENDOR_ID = 0x04F3
PRODUCT_ID = 0x0C4C

TIMEOUT_MS = 5000
Interface = 0

backend = libusb_package.get_libusb1_backend()


@dataclass
class USBCommand:
    name: str
    cmd: int
    CMD_PORT: int
    payload: int
    resp_len: int
    EP_IN: int
    EP_OUT: int

    def __repr__(self):
        return (
            f"USBCommand("
            f"name='{self.name}', "
            f"cmd=0x{self.cmd:02x}, "
            f"CMD_PORT=0x{self.CMD_PORT:02x}, "
            f"payload=0x{self.payload:02x}, "
            f"resp_len={self.resp_len}, "
            f"EP_IN=0x{self.EP_IN:02x}, "
            f"EP_OUT=0x{self.EP_OUT:02x})"
        )


def find_device():
    dev = usb.core.find(backend=backend, idVendor=VENDOR_ID, idProduct=PRODUCT_ID)
    if dev is None:
        raise ValueError("Device not found")

    return dev


def init_device():
    dev = find_device()
    if dev is None:
        raise ValueError("Device not found")

    if platform.system() == "Linux":
        if dev.is_kernel_driver_active(Interface):
            dev.detach_kernel_driver(Interface)

    dev.set_configuration()
    usb.util.claim_interface(dev, Interface)

    return dev


def cleanup(dev: usb.core.Device):
    usb.util.release_interface(dev, Interface)
    usb.util.dispose_resources(dev)
    print("Device released.")


def send_cmd(dev: usb.core.Device, cmd: USBCommand):
    try:
        print(f"Sending {cmd.name} command...")
        if cmd.payload is None:
            dev.write(cmd.EP_OUT, bytes([cmd.CMD_PORT, cmd.cmd]))
        else:
            dev.write(cmd.EP_OUT, bytes([cmd.CMD_PORT, cmd.cmd, cmd.payload]))

        if cmd.EP_IN is None:
            return 0
        else:
            print("Waiting for device processing...")
            time.sleep(0.05)
            response = dev.read(cmd.EP_IN, cmd.resp_len, timeout=TIMEOUT_MS)
        return response
    except usb.core.USBTimeoutError:
        print("ERROR: Timeout. Is the device ready?")
        cleanup(dev=dev)
    except Exception as e:
        print(f"ERROR: {e}")
        cleanup(dev=dev)


"""Working"""
fw_ver_cmd = USBCommand(
    name="get firmware version",
    cmd=0x19,
    CMD_PORT=0x40,
    payload=None,
    resp_len=2,
    EP_IN=0x83,
    EP_OUT=0x01,
)


def get_fw_version():
    device = init_device()
    try:
        resp = send_cmd(dev=device, cmd=fw_ver_cmd)
        if resp is None:
            return
        resplen = fw_ver_cmd.resp_len
        actual_len = len(resp)
        if actual_len != resplen:
            print(
                f"something went wrong, expected resp_len {resplen}, actutal: {actual_len}."
            )
        print(f"FW Version: {resp[0]}.{resp[1]}.")
    finally:
        cleanup(dev=device)


"""Not tested and not sure"""
enrolled_number_cmd = USBCommand(
    name="enrolled number",
    cmd=0xFF,
    CMD_PORT=0x40,
    payload=0x04,
    resp_len=2,
    EP_IN=0x83,
    EP_OUT=0x01,
)
cal_status_cmd = USBCommand(
    name="cal status",
    cmd=0xFF,
    CMD_PORT=0x40,
    payload=0x00,
    resp_len=2,
    EP_IN=0x83,
    EP_OUT=0x01,
)

"""DOESNT RESPONSE LOL"""
elanmoc_remove_all_cmd = USBCommand(
    name="delete all",
    cmd=0xFF,
    CMD_PORT=0x40,
    payload=0x99,
    resp_len=2,
    EP_IN=None,
    EP_OUT=0x01,
)

"""
Mode (guess)	Meaning
0	Idle / standby
1	Capture / sensing
2	Low power
3	MOC verify mode
"""
elanmoc_set_mod_cmd = USBCommand(
    name="set mode",
    cmd=0xFF,
    CMD_PORT=0x40,
    payload=0x14,
    resp_len=2,
    EP_IN=0x83,
    EP_OUT=0x01,
)
elanmoc_enroll = USBCommand(
    name="enroll finger",
    cmd=0xFF,
    CMD_PORT=0x40,
    payload=0x01,
    resp_len=2,
    EP_IN=None,
    EP_OUT=0x01,
)
elanmoc_enroll_cancel = USBCommand(
    name="cancel enroll finger",
    cmd=0xFF,
    CMD_PORT=0x40,
    payload=0x02,
    resp_len=2,
    EP_IN=None,
    EP_OUT=0x01,
)

"""[32 bytes ECC data] param"""
elanmoc_ECC_enroll_commit = USBCommand(
    name="ECC enroll commit",
    cmd=0xFF,
    CMD_PORT=0x40,
    payload=0x0A,
    resp_len=2,
    EP_IN=None,
    EP_OUT=0x01,
)
FpEccSignVerify = USBCommand(
    name="ECC Sign Verfiy",
    cmd=0xFF,
    CMD_PORT=0x40,
    payload=0x06,
    resp_len=1202,
    EP_IN=None,
    EP_OUT=0x01,
)
FpGetFWAP_PKey = USBCommand(
    name="get public key",
    cmd=0xFF,
    CMD_PORT=0x40,
    payload=0x0D,
    resp_len=66,
    EP_IN=None,
    EP_OUT=0x01,
)
FpGetFWAuthorizedInfo = USBCommand(
    name="get Authorized info",
    cmd=0xFF,
    CMD_PORT=0x40,
    payload=0x0C,
    resp_len=66,
    EP_IN=None,
    EP_OUT=0x01,
)
FpReceiveEnrollNonce = USBCommand(
    name="receive enroll nonce",
    cmd=0xFF,
    CMD_PORT=0x40,
    payload=0x09,
    resp_len=34,
    EP_IN=None,
    EP_OUT=0x01,
)
"""response 0xFF"""
OnDeviceGetSID = USBCommand(
    name="get secure id",
    cmd=0xFF,
    CMD_PORT=0x40,
    payload=0x12,
    resp_len=34,
    EP_IN=None,
    EP_OUT=0x01,
)
OnDeviceCommitEnrollID = USBCommand(
    name="commit secure id",
    cmd=0xFF,
    CMD_PORT=0x40,
    payload=0x11,
    resp_len=2,
    EP_IN=None,
    EP_OUT=0x01,
)


"""0x00 is ok, rest check Errorcodes"""
ElanFP_Verfication_CD = USBCommand(
    name="verify",
    cmd=0xFF,
    CMD_PORT=0x40,
    payload=0x03,
    resp_len=2,
    EP_IN=0x83,
    EP_OUT=0x01,
)

"""0x00 success, 0xFE finger not found, 0xFF Error"""
ElanFP_RemoveFinger_SubSID = USBCommand(
    name="remove finger sid",
    cmd=0xFF,
    CMD_PORT=0x40,
    payload=0x13,
    resp_len=2,
    EP_IN=None,
    EP_OUT=0x01,
)

"""remove finger by id"""
ElanFP_RemoveFinger_CD = USBCommand(
    name="remove finger by id",
    cmd=0xFF,
    CMD_PORT=0x40,
    payload=0x05,
    resp_len=2,
    EP_IN=None,
    EP_OUT=0x01,
)

"""0x03 ready, 0x01 not ready"""
FpDeviceInitialize_POA = USBCommand(
    name="device init",
    cmd=0xFF,
    CMD_PORT=0x40,
    payload=0x00,
    resp_len=2,
    EP_IN=None,
    EP_OUT=0x01,
)


SendWDTCMD = USBCommand(
    name="reset watchdog timer",
    cmd=0x40,
    CMD_PORT=0x40,
    payload=0x27,
    resp_len=2,
    EP_IN=None,
    EP_OUT=0x01,
)

ReadSensorStatus = USBCommand(
    name="read sensor status",
    cmd=0x40,
    CMD_PORT=0x40,
    payload=0x13,
    resp_len=2,
    EP_IN=None,
    EP_OUT=0x01,
)

GetSensorTrace = USBCommand(
    name="get sensor trace",
    cmd=0x00,
    CMD_PORT=0x40,
    payload=0x0C,
    resp_len=4,
    EP_IN=None,
    EP_OUT=0x01,
)

CheckDuplicate = USBCommand(
    name="check for duplicate",
    cmd=0xFF,
    CMD_PORT=0x40,
    payload=0x10,
    resp_len=3,
    EP_IN=None,
    EP_OUT=0x01,
)

CaptureStart = USBCommand(
    name="start capture",
    cmd=0x00,
    CMD_PORT=0x40,
    payload=0x09,
    resp_len=2,
    EP_IN=None,
    EP_OUT=0x01,
)
CaptureBaseImage = USBCommand(
    name="capture base img",
    cmd=0x01,
    CMD_PORT=0x0A,
    payload=0x10,
    resp_len=128000,
    EP_IN=None,
    EP_OUT=0x01,
)
GetImgFromFW = USBCommand(
    name="read fingerprint",
    cmd=0x02,
    CMD_PORT=0x40,
    payload=0x0A,
    resp_len=2,
    EP_IN=None,
    EP_OUT=0x01,
)


if __name__ == "__main__":
    get_fw_version()
