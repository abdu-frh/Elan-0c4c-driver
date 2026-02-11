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
    Commands on USB Layer happens on USB Addr:<br>
    CMD_REQ: 0x01<br>
    CMD_RESP: 0x81

    Data/Config_Upload: 0x02<br>
    DATA_IMG_RESP: 0x82
    """)
    return


@app.cell
def _():
    VENDOR_ID = 0x04F3
    PRODUCT_ID = 0x0C4C
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
    return


if __name__ == "__main__":
    app.run()
