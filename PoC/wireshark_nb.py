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
    ## Part 1 USB-Protocoll: Libusb is your best friend 🤗
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ##USB Descriptor Hierarchy

    USB devices are organized in a tree structure: Device → Configuration → Interface → Endpoint.

    Device contains: Vendor ID, Product ID and List of Configuration.<br>
    Configuration: Are modes, like High power or Low power mode, most devices have only one mode. <br> Interface: Inside one configuartion, there are multiple interfaces. each represents a unique function. <br>
    Example: webcam has, Interface 0: Video camera, Interface 1: microphone, Interface 2: Speaker etc. <br>
    Endpoint: The Endpoints for each Interface/function: <br> IN endpoint: from device to computer. <br> OUT endpoint: from computer to device. <br> Types: Bulk(large package), interrupt(small packages), Isochronous (streaming data)
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ##How to figure out DeviceID and VendorID

    command on linux: lsusb

    ###Output:
    Bus 001 Device 001: ID 1d6b:0002 Linux Foundation 2.0 root hub<br>
    Bus 001 Device 002: ID 04f3:0c4c Elan Microelectronics Corp. ELAN:ARM-M4<br>
    Bus 001 Device 004: ID 346d:5678 ITE Intenso Rainbow Line<br>
    Bus 002 Device 001: ID 1d6b:0003 Linux Foundation 3.0 root hub<br>
    Bus 003 Device 001: ID 1d6b:0002 Linux Foundation 2.0 root hub<br>
    Bus 003 Device 002: ID 0bda:2852 Realtek Semiconductor Corp. Bluetooth Radio<br>
    Bus 004 Device 001: ID 1d6b:0003 Linux Foundation 3.0 root hub<br>

    its always after the ID < VendorID : DeviceID > <br>
    our Fingerprint device here is, the ELAN:ARM-M4, VendorID:04f3 DeviceID:0c4c
    """)
    return


@app.cell
def _():
    VENDOR_ID = 0x04F3
    PRODUCT_ID = 0x0C4C
    return


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


app._unparsable_cell(
    r"""
    import usb.util
    import usb.core
    import libusb_package

    # Get the bundled backend
    backend = libusb_package.get_libusb1_backend()

    def find_device(
        dev = usb.core.find(backend=backend, idVendor=VENDOR_ID, idProduct=PRODUCT_ID)
        if dev is None:
            raise ValueError("Device not found")

        return dev 

    if __name__ == "__find_device__":
        tmp = find_device()
        print(tmp)
    """,
    name="_"
)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ##Lists descriptors: Configurations, Interface, Endpoints
    Lol straight up stole from libusb docs
    """)
    return


app._unparsable_cell(
    r"""
    def list_descriptors():
        dev = find_device()
        for cfg in dev:
        sys.stdout.write(str(cfg.bConfigurationValue) + '\n')
        for intf in cfg:
            sys.stdout.write('\t' + \
                             str(intf.bInterfaceNumber) + \
                             ',' + \
                             str(intf.bAlternateSetting) + \
                             '\n')
            for ep in intf:
                sys.stdout.write('\t\t' + \
                                 str(ep.bEndpointAddress) + \
                                 '\n')

    if __name__ == "__list_descriptors__":
        list_descriptors()
    """,
    name="_"
)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ###Commands on USB Layer happens on USB Addr:<br>
    CMD_REQ: 0x01<br>
    CMD_RESP: 0x81

    Data/Config_Upload: 0x02<br>
    DATA_IMG_RESP: 0x82<br>

    ### Commands on I2I Layer<br>
    CMD_REQ: 0x40 + HEX_CMD
    + Req_length
    + Resp length<br>

    #### Example firmware version request<br>

    static const struct elanmoc_cmd fw_ver_cmd = {<br>
      .cmd_header = {0x40, 0x19},<br>
      .cmd_len = 2,<br>
      .resp_len = 2,<br>
    }
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ##Wireshark part🦈
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


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Try to emulate cmds only works on linux lol😺
    """)
    return


@app.cell
def _(find_device):
    import usb.core
    import usb.util


    def config_device(dev):
        dev.set_configuration()

        cfg = dev.get_active_configuration()
        intf = cfg[(0, 0)]  # Interface 0, Alternate setting 0

        # Detach kernel driver if attached (Linux/macOS)
        if dev.is_kernel_driver_active(0):
            print("Detaching kernel driver...")
            dev.detach_kernel_driver(0)

        # Claim interface
        usb.util.claim_interface(dev, 0)

        return intf

    def find_and_config_device():
        dev = find_device()
        return dev

    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Found USB Endpoints
    """)
    return


@app.cell
def _():
    EP_OUT = 0x01  
    EP_IN  = 0x81  
    return


app._unparsable_cell(
    r"""
    from dataclasses import dataclass
    import time

    TIMEOUT_MS = 5000
    CMD_PORT = 0x40

    @dataclass
    class elan_cmd:
        name: str
        cmd: hex
        payload: hex
        resp_len: bytes

    send_cmd(dev,cmd:elan_cmd):
        # Claim interface
        usb.util.claim_interface(dev, 0)

        try:
            print(f"Sending {cmd.name} command...")

            CMD = bytes([CMD_PORT, cmd.cmd])  

            # WRITE PHASE: Send to EP1 OUT (0x01)
            bytes_written = dev.write(EP_OUT, CMD, timeout=TIMEOUT_MS)
            print(f"Sent {bytes_written} bytes")

            print("Waiting for device processing...")
            time.sleep(0.05)

            # READ PHASE: Read from EP1 IN (0x81)
            resp = dev.read(EP_IN, 64, timeout=TIMEOUT_MS)

            # Parse response (first resp_len bytes are valid)
            if len(resp) >= cmd.resp_len:
                version_major = resp[0]
                version_minor = resp[1]
                version_combined = (resp[0] << 8) | resp[1]

                print(f"Response raw: {resp[:cmd.resp_len].hex()}")
                print(f"Firmware Version: {version_major}.{version_minor} (0x{version_combined:04X})")
                return resp[:cmd.resp_len]
            else:
                print(f"Short response: {resp.hex()}")
                return resp

        except usb.core.USBTimeoutError:
            print("ERROR: Timeout. Is the device ready?")
            raise
        except Exception as e:
            print(f"ERROR: {e}")
            raise
        finally:
            # Cleanup
            usb.util.release_interface(dev, 0)
            print("Interface released")
    """,
    name="_"
)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### Get Firmware Version
    """)
    return


if __name__ == "__main__":
    app.run()
