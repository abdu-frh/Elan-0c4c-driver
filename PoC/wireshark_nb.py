import marimo

__generated_with = "0.19.9"
app = marimo.App(width="medium")


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Reverse Engineering ELAN WBF Fingerprint Sensor
    """)
    return


@app.cell
def _():
    import marimo as mo

    return (mo,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Using Wireshark and drivers from older Elan fingerprint version from Libusb libary
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Commands cause windows suck🙄<br>

    eval "$(ssh-agent -s)"<br>
    ssh-add ~/.ssh/github
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### Current Knowledge
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    The devices is a complete arm mini computer with cpu and storage.
    It manages the enroll, verfication, storage and deletion of the fingerprint.

    To communication with it, happens on the USB Protocol, from Computer to the Elan ARM M4.
    """)
    return


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


@app.cell
def _():
    VENDOR_ID = 0x04F3
    PRODUCT_ID = 0x0C4C

    # Endpoint addresses (from your USBView dump)
    EP_OUT = 0x01  # Endpoint 1 OUT (Commands)
    EP_IN = 0x81   # Endpoint 1 IN (Responses)
    return EP_IN, EP_OUT, PRODUCT_ID, VENDOR_ID


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Try to emulate cmds only works on linux lol😺
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### needs to be run as administrator or root in unix⬇️
    """)
    return


@app.cell
def _(EP_IN, EP_OUT, PID, PRODUCT_ID, VENDOR_ID, VID):
    import usb.core
    import usb.util
    import time
    import libusb_package

    # Get the bundled backend
    backend = libusb_package.get_libusb1_backend()

    FW_VER_CMD = bytes([0x40, 0x19])  
    EXPECTED_RESP_LEN = 2             
    TIMEOUT_MS = 1000     

    def send_elan_cmd():
        # Find device
        dev = usb.core.find(backend=backend,idVendor=VENDOR_ID, idProduct=PRODUCT_ID)
        if dev is None:
            raise ValueError(f"Device {VID:04x}:{PID:04x} not found. Check PID!")

        print(f"Found device: {PRODUCT_ID}")

       # Unmark if device driver is not configured by os
       #dev.set_configuration()

        cfg = dev.get_active_configuration()
        intf = cfg[(0, 0)]  # Interface 0, Alternate setting 0

        # Detach kernel driver if attached (Linux/macOS)
        if dev.is_kernel_driver_active(0):
            print("Detaching kernel driver...")
            dev.detach_kernel_driver(0)

        # Claim interface
        usb.util.claim_interface(dev, 0)

        try:
            print(f"Sending command: {FW_VER_CMD.hex()} (Register 0x{FW_VER_CMD[0]:02X}, Opcode 0x{FW_VER_CMD[1]:02X})")

            # WRITE PHASE: Send to EP1 OUT (0x01)
            bytes_written = dev.write(EP_OUT, FW_VER_CMD, timeout=TIMEOUT_MS)
            print(f"Sent {bytes_written} bytes")

            # CRITICAL DELAY: ARM-M4 needs time to process I2C command
            print("Waiting for device processing (50ms)...")
            time.sleep(0.05)

            # READ PHASE: Read from EP1 IN (0x81)
            resp = dev.read(EP_IN, 64, timeout=TIMEOUT_MS)

            # Parse response (first resp_len bytes are valid)
            if len(resp) >= EXPECTED_RESP_LEN:
                version_major = resp[0]
                version_minor = resp[1]
                version_combined = (resp[0] << 8) | resp[1]

                print(f"Response raw: {resp[:EXPECTED_RESP_LEN].hex()}")
                print(f"Firmware Version: {version_major}.{version_minor} (0x{version_combined:04X})")
                return resp[:EXPECTED_RESP_LEN]
            else:
                print(f"Short response: {resp.hex()}")
                return resp

        except usb.core.USBTimeoutError:
            print("ERROR: Timeout waiting for response. Is the device ready?")
            raise
        except Exception as e:
            print(f"ERROR: {e}")
            raise
        finally:
            # Cleanup
            usb.util.release_interface(dev, 0)
            print("Interface released")

    if __name__ == "__main__":
        send_elan_cmd()
    return


if __name__ == "__main__":
    app.run()
