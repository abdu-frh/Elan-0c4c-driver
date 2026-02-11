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
    It manages the enroll,verfication,storage and deletion of the fingerprint.

    To communication with it, happens on the USB Protocol,from Computer to the Elan ARM M4.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    Commands on USB Layer happens on USB Addr:
    CMD_REQ: 0x01
    CMD_RESP: 0x81

    Data/Config_Upload: 0x02
    DATA_IMG_RESP: 0x82
    """)
    return


if __name__ == "__main__":
    app.run()
