import marimo

__generated_with = "0.19.11"
app = marimo.App(width="medium")


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Reverse Engineering ELAN WBF Fingerprint Sensor
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Using Wireshark, open source drivers from older Elan fingerprints and the Libusb libary
    """)
    return


@app.cell
def _():
    import marimo as mo

    return (mo,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Current Knowledge

    The devices is a complete arm mini computer with cpu, ram and storage.<br>
    It manages the enrollment, verfication, storage and deletion of the fingerprints.

    To communication, happens on the USB Protocol, from Computer to the Elan ARM M4.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Part 1 USB-Protocoll: Libusb is your best friend 🤗
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ##USB Descriptor Hierarchy

    USB devices are organized in a tree structure: Device → Configuration → Interface → Endpoint.

    | Level | Contains |
    |:------|:---------|
    | **Device** | Vendor ID, Product ID, Configurations |
    | **Configuration** | Power modes (usually just one) |
    | **Interface** | Unique functions per configuration |
    | **Endpoint** | Data channels (IN/OUT) |

    **Endpoints:**
    - `IN` — device to computer
    - `OUT` — computer to device

    **Transfer Types:** Bulk (large) · Interrupt (small) · Isochronous (streaming)
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # How to figure out DeviceID and VendorID

    **Command on Linux:**

    ```bash
    lsusb
    ```

    **Output:**

    ```text
    Bus 001 Device 001: ID 1d6b:0002 Linux Foundation 2.0 root hub
    Bus 001 Device 002: ID 04f3:0c4c Elan Microelectronics Corp. ELAN:ARM-M4
    Bus 001 Device 004: ID 346d:5678 ITE Intenso Rainbow Line
    Bus 002 Device 001: ID 1d6b:0003 Linux Foundation 3.0 root hub
    Bus 003 Device 001: ID 1d6b:0002 Linux Foundation 2.0 root hub
    Bus 003 Device 002: ID 0bda:2852 Realtek Semiconductor Corp. Bluetooth Radio
    Bus 004 Device 001: ID 1d6b:0003 Linux Foundation 3.0 root hub
    ```

    **Format:** `ID <VendorID>:<DeviceID>`

    **Our fingerprint device:** `ELAN:ARM-M4` with VendorID `04f3` and DeviceID `0c4c`
    """)
    return


@app.cell
def _():
    VENDOR_ID = 0x04f3
    PRODUCT_ID = 0x0c4c
    return PRODUCT_ID, VENDOR_ID


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ##Find device via Vendor and Device-ID
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### needs to be run as administrator or root in unix⬇️
    """)
    return


@app.cell
def _(PRODUCT_ID, VENDOR_ID):
    import usb.util
    import usb.core
    import libusb_package

    # Get the bundled backend
    backend = libusb_package.get_libusb1_backend()

    def find_device():
        dev = usb.core.find(backend=backend, idVendor=VENDOR_ID, idProduct=PRODUCT_ID)
        if dev is None:
            raise ValueError("Device not found")

        return dev 

    if __name__ == "__main__":
        tmp = find_device()
        print(tmp)
    return find_device, usb


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Specs for communication

    **Endpoints:** 4 total (IN/OUT pairs)
    **Config:** 1 | **Interface:** 1

    | EP | IN | OUT | Type | Size |
    |:--:|:--:|:---:|------|-----:|
    | 1 | 0x81 | 0x1 | BULK | 64 B |
    | 2 | 0x82 | 0x2 | BULK | 64 B |
    | 3 | 0x83 | 0x3 | BULK | 64 B |
    | 4 | 0x84 | 0x4 | BULK | 64 B |
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Try to do some cmds, (on linux) lol😺
    """)
    return


@app.cell
def _(find_device, usb):
    from dataclasses import dataclass
    import time

    TIMEOUT_MS = 5000
    CMD_PORT = 0x40
    Interface = 0

    @dataclass
    class USBCommand:
        name: str
        cmd: hex
        payload: hex
        resp_len: bytes
        EP_IN: hex
        EP_OUT: hex

    def init_device():
        dev = find_device()
        if dev.is_kernel_driver_active(Interface):
            dev.detach_kernel_driver(Interface)
        dev.set_configuration()
        usb.util.claim_interface(dev, Interface)
        return dev

    return CMD_PORT, Interface, TIMEOUT_MS, USBCommand, init_device, time


@app.cell
def _(CMD_PORT, Interface, TIMEOUT_MS, USBCommand, time, usb):
    def cleanup(dev: usb.core.Device):
        usb.util.release_interface(dev, Interface)
        usb.util.dispose_resources(dev)
        print("Device released")    

    def send_cmd(dev: usb.core.Device, cmd: USBCommand):
        try:
            print(f"Sending {cmd.name} command...")
            dev.write(cmd.EP_OUT,bytes([CMD_PORT,cmd.cmd]))
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

    return cleanup, send_cmd


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ##Some cmd infomation from older driver

    From `elanmoc.c`:

    ```c
    static void elanmoc_cmd_ver_cb(FpiDeviceElanmoc *self, uint8_t *buffer_in,
                                   gsize length_in, GError *error) {
      if (error) {
        fpi_ssm_mark_failed(self->task_ssm, error);
        return;
      }

      self->fw_ver = (buffer_in[0] << 8 | buffer_in[1]);
      fp_info("elanmoc  FW Version %x ", self->fw_ver);
      fpi_ssm_next_state(self->task_ssm);
    }
    ```

    From `elanmoc.h`:

    ```c
    static const struct elanmoc_cmd fw_ver_cmd = {
      .cmd_header = {0x40, 0x19},
      .cmd_len = 2,
      .resp_len = 2,
    };
    ```
    """)
    return


@app.cell
def _():
    ERRORS = {
        0xFD: "ELAN_MSG_VERIFY_ERR",
        0xFB: "ELAN_MSG_DIRTY",
        0xFE: "ELAN_MSG_AREA_NOT_ENOUGH",
        0x41: "ELAN_MSG_TOO_HIGH",
        0x42: "ELAN_MSG_TOO_LEFT",
        0x43: "ELAN_MSG_TOO_LOW",
        0x44: "ELAN_MSG_TOO_RIGHT",
        0x00: "ELAN_MSG_OK",
    }
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    | Constant | Calculation | Hex | Decimal | Meaning |
    |----------|-------------|-----|---------|---------|
    | `ELAN_EP_CMD_OUT` | `0x1 \| 0x00` | `0x01` | **1** | Endpoint 1, **OUT** (Host → Device) |
    | `ELAN_EP_CMD_IN` | `0x3 \| 0x80` | `0x83` | **131** | Endpoint 3, **IN** (Device → Host) |
    | `ELAN_EP_MOC_CMD_IN` | `0x4 \| 0x80` | `0x84` | **132** | Endpoint 4, **IN** |
    | `ELAN_EP_IMG_IN` | `0x2 \| 0x80` | `0x82` | **130** | Endpoint 2, **IN** |
    """)
    return


@app.cell
def _(USBCommand):
    fw_ver_cmd = USBCommand(name="get firmware version",cmd=0x19,payload=None,resp_len=2,EP_IN=0x83,EP_OUT=0x01)

    return (fw_ver_cmd,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### Get Firmware Version
    """)
    return


@app.cell
def _(cleanup, fw_ver_cmd, init_device, send_cmd):
    def get_fw_version():
        dev = init_device()
        try:
            resp = send_cmd(dev=dev,cmd=fw_ver_cmd)
            if resp is None:
                return
            if len(resp) == fw_ver_cmd.resp_len:
                print(f"FW Version: {resp[0]}.{resp[1]}")
        finally:
            cleanup(dev=dev)

    if __name__ == "__main__":
        get_fw_version()
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    #Wireshark🦈
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Trying to find the endpoints from recorded communication, from usage in windows
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Read and processes here the recorded interaction with the fingerprint🎆
    """)
    return


@app.cell
def _():
    import nest_asyncio
    nest_asyncio.apply()

    import pyshark

    capture = pyshark.FileCapture("./capture_wireshark/usbcap1.pcapng",display_filter="usb.device_address == 1")

    capture.load_packets()

    print(capture)
    return


if __name__ == "__main__":
    app.run()
