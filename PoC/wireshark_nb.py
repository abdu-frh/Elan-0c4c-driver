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
    #CMD_PORT = 0x40
    Interface = 0

    @dataclass
    class USBCommand:
        name: str
        cmd: hex
        CMD_PORT: hex
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

    return Interface, TIMEOUT_MS, USBCommand, dataclass, init_device, time


@app.cell
def _(Interface, TIMEOUT_MS, USBCommand, time, usb):
    def cleanup(dev: usb.core.Device):
        usb.util.release_interface(dev, Interface)
        usb.util.dispose_resources(dev)
        print("Device released.")    

    def send_cmd(dev: usb.core.Device, cmd: USBCommand):
        try:
            print(f"Sending {cmd.name} command...")
            if cmd.payload == None:
                dev.write(cmd.EP_OUT,bytes([cmd.CMD_PORT,cmd.cmd]))
            else: 
                dev.write(cmd.EP_OUT,bytes([cmd.CMD_PORT,cmd.cmd,cmd.payload]))
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
    # working
    fw_ver_cmd = USBCommand(name="get firmware version",cmd=0x19,CMD_PORT=0x40,payload=None,resp_len=2,EP_IN=0x83,EP_OUT=0x01)
    enrolled_number_cmd = USBCommand(name="enrolled number",cmd=0xff,CMD_PORT=0x40,payload=0x04,resp_len=2,EP_IN=0x83,EP_OUT=0x01)
    cal_status_cmd = USBCommand(name="cal status",cmd=0xff,CMD_PORT=0x40,payload=0x00,resp_len=2,EP_IN=0x83,EP_OUT=0x01)

    #testing

    # needs wireshark
    elanmoc_remove_all_cmd = USBCommand(name="delete all",cmd=0xff,CMD_PORT=0x40,payload=0x98,resp_len=2,EP_IN=0x84,EP_OUT=0x01)
    elanmoc_set_mod_cmd = USBCommand(name="set mode",cmd=0xff,CMD_PORT=0x40,payload=0x14,resp_len=2,EP_IN=0x83,EP_OUT=0x01,)
    elanmoc_get_userid_cmd = USBCommand(name="get all user",cmd=0x21,CMD_PORT=0x43,payload=0x00,resp_len=97,EP_IN=0x84,EP_OUT=0x01)
    elanmoc_verify_cmd = USBCommand(name="verify",cmd=0xff,CMD_PORT=0x40,payload=0x73,resp_len=2,EP_IN=0x83,EP_OUT=0x01)
    return (
        cal_status_cmd,
        elanmoc_get_userid_cmd,
        elanmoc_remove_all_cmd,
        elanmoc_set_mod_cmd,
        elanmoc_verify_cmd,
        enrolled_number_cmd,
        fw_ver_cmd,
    )


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### cal_status_cmd

    This command is used during DEV_WAIT_READY and is retried up to ELAN_MOC_CAL_RETRY (500) times. The driver keeps polling this command until the sensor reports it's calibrated and ready.

    A value of 0x03 means calibration complete / sensor ready — so your sensor is good to go
    """)
    return


@app.cell
def _(
    cal_status_cmd,
    cleanup,
    elanmoc_get_userid_cmd,
    elanmoc_remove_all_cmd,
    elanmoc_set_mod_cmd,
    elanmoc_verify_cmd,
    enrolled_number_cmd,
    fw_ver_cmd,
    init_device,
    send_cmd,
):
    def get_fw_version():
        device = init_device()
        try:
            resp = send_cmd(dev=device,cmd=fw_ver_cmd)
            if resp is None:
                return
            resplen = fw_ver_cmd.resp_len
            actual_len = len(resp)
            if actual_len != resplen:
                print(f"something went wrong, expected resp_len {resplen}, actutal: {actual_len}.")
            print(f"FW Version: {resp[0]}.{resp[1]}.")
        finally:
            cleanup(dev=device)

    def set_mode():
        device = init_device()
        try:
            resp = send_cmd(dev=device,cmd=elanmoc_set_mod_cmd)
            if resp is None:
                return
            resplen = fw_ver_cmd.resp_len
            actual_len = len(resp)
            if actual_len != resplen :
                print(f"something went wrong, expected resp_len {resplen}, actutal: {actual_len}.")
            print(resp)
        finally:
            cleanup(dev=device)

    #def get_userid():
    #  device = init_device()
    #  try:
    #      resp = send_cmd(dev=device,cmd=elanmoc_get_userid_cmd)
    #       if resp is None:
    #            return
    #        resplen = elanmoc_get_userid_cmd.resp_len
    #        actual_len = len(resp)
    #        if actual_len != resplen :
    #            print(f"something went wrong, expected resp_len {resplen}, actutal: {actual_len}.")
    #        print(resp)
    #    finally:
    #        if resp != None:
    #           cleanup(dev=device)

    def get_enrolled_number():
        device = init_device()
        try:
            resp = send_cmd(dev=device,cmd=enrolled_number_cmd)
            if resp is None:
                return
            resplen = enrolled_number_cmd.resp_len
            actual_len = len(resp)
            if actual_len != resplen :
                print(f"something went wrong, expected resp_len {resplen}, actutal: {actual_len}.")
            print(f"Enrolled fingers {resp[1]}.")
        finally:
            if resp != None:
                cleanup(dev=device)

    def get_all_userids():
        device = init_device()
        try:
            # First get how many are enrolled
            resp = send_cmd(dev=device, cmd=enrolled_number_cmd)
            count = resp[1]
            print(f"Enrolled fingers: {count}")

            # Then query each one by index
            for i in range(count):
                elanmoc_get_userid_cmd.payload = i
                resp = send_cmd(dev=device, cmd=elanmoc_get_userid_cmd)
                if resp:
                    # User ID starts after some header bytes
                    user_id = resp[3:].tobytes().rstrip(b'\x00').decode('utf-8', errors='ignore')
                    print(f"Finger {i}: {user_id}")
        finally:
            cleanup(dev=device)


    def get_status():
        device = init_device()
        try:
            resp = send_cmd(dev=device,cmd=cal_status_cmd)
            if resp is None:
                return
            resplen = cal_status_cmd.resp_len
            actual_len = len(resp)
            if actual_len != resplen :
                print(f"something went wrong, expected resp_len {resplen}, actutal: {actual_len}.")
            status = resp[1]
            if status == 3:
                print(f"Sensor reported 0x0{resp[1]}, Sensor is calibrated and ready to go.")
            else:
                print(f"Sensor reported 0x0{resp[1]}, Sensor is calibrating.")
        finally:
            if resp != None:
                cleanup(dev=device)

    def delete_all():
        device = init_device()
        try:
            resp = send_cmd(dev=device,cmd=elanmoc_remove_all_cmd)
            if resp is None:
                return
            resplen = elanmoc_remove_all_cmd.resp_len
            actual_len = len(resp)
            if actual_len != resplen :
                print(f"something went wrong, expected resp_len {resplen}, actutal: {actual_len}.")
            status = resp[1]
            if status == 3:
                print(f"Sensor reported 0x0{resp[1]}, Sensor is calibrated and ready to go.")
            else:
                print(f"Sensor reported 0x0{resp[1]}, Sensor is calibrating.")
        finally:
            if resp != None:
                cleanup(dev=device)


    # funktioniert nicht 
    def verify():
        device = init_device()
        try:
            resp = send_cmd(dev=device,cmd=elanmoc_verify_cmd)
            if resp is None:
                return
            resplen = elanmoc_verify_cmd.resp_len
            actual_len = len(resp)
            if actual_len != resplen :
                print(f"something went wrong, expected resp_len {resplen}, actutal: {actual_len}.")
            print(resp)
        finally:
            if resp != None:
                cleanup(dev=device)

    if __name__ == "__main__":
        #get_fw_version()
        get_enrolled_number()
        #et_status()
        #set_mode()
        #get_all_userids()
        #delete_all()
        #sleep(1000)
        #get_enrolled_number()
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
    ## Commands to Capture USB Traffic in Linux

    `sudo modprobe usbmon` loads module thats enables us to capture usb traffic
    `sudo wiresharl` needed for
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    `Filters:` usb.bus_id == 1 && usb.device_address == 3 && usb.data_flag == 0
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    Send cmd and watch traffic with wireshark <br> Section: Leftover Capture Data, is where you can find CMD_PORT:CMD:PAYLOAD <br> example get_enrolled_number: 40ff04
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Read and processes here the recorded interaction with the fingerprint🎆
    """)
    return


@app.cell
def _(dataclass):
    from typing import Optional, List, Tuple
    from datetime import datetime
    import nest_asyncio
    nest_asyncio.apply()

    import pyshark

    @dataclass
    class UsbCommand:
        direction: str          
        endpoint: int           
        command_byte: int       
        payload: bytes         
        raw_hex: str            
        packet_num: int
        timestamp: float

    @dataclass
    class UsbTransaction:
        request: UsbCommand
        response: Optional[UsbCommand] = None
        urb_id: Optional[str] = None
    
        @property
        def is_complete(self) -> bool:
            return self.response is not None
    
        @property
        def duration_ms(self) -> Optional[float]:
            if self.response:
                return (self.response.timestamp - self.request.timestamp) * 1000
            return None

    return List, Tuple, UsbCommand, UsbTransaction, pyshark


@app.cell
def _(Tuple):
    def parse_hex_data(hex_str: str) -> Tuple[int, bytes]:
        """Parse '40:ff:04' -> (0x40, b'\xff\x04')"""
        if not hex_str:
            return (0, b'')
    
        # Remove colons if present, or use as-is
        clean = hex_str.replace(':', '')
        try:
            data = bytes.fromhex(clean)
            if len(data) == 0:
                return (0, b'')
            return (data[0], data[1:] if len(data) > 1 else b'')
        except ValueError:
            return (0, b'')


    def extract_endpoint(usb_layer) -> Tuple[int, str]:
        """Extract endpoint number and direction from USB layer"""
        try:
            # Try to get from endpoint field (e.g., '0x01')
            ep_str = getattr(usb_layer, 'endpoint_number', '0')
            ep = int(ep_str, 16) if isinstance(ep_str, str) else int(ep_str)
        
            # Direction from endpoint attribute or src/dst
            direction = getattr(usb_layer, 'endpoint_direction', None)
            if not direction:
                src = getattr(usb_layer, 'src', 'unknown')
                direction = 'OUT' if src == 'host' else 'IN'
            
            return (ep, direction)
        except:
            return (0, 'UNKNOWN')

    return extract_endpoint, parse_hex_data


@app.cell
def _(
    Dict,
    List,
    UsbCommand,
    UsbTransaction,
    extract_endpoint,
    parse_hex_data,
    pyshark,
):
    def parse_usb_transactions(pcap_file: str, 
                              device_addr: int = 3,
                              bus_id: int = 1) -> List[UsbTransaction]:
        """
        Extract paired USB transactions (SUBMIT/COMPLETE) from capture.
        Returns list of UsbTransaction objects.
        """
        capture = pyshark.FileCapture(
            pcap_file,
            display_filter=f"usb.bus_id == {bus_id} && usb.device_address == {device_addr}"
        )
    
        # store pending SUBMITs by URB ID
        pending_requests: Dict[str, UsbCommand] = {}
        transactions: List[UsbTransaction] = []
    
        for packet in capture:
            try:
                if not hasattr(packet, 'usb'):
                    continue
                
                usb = packet.usb
            
                urb_id = getattr(usb, 'urb_id', None)
                urb_type = getattr(usb, 'urb_type', 'UNKNOWN')  # SUBMIT or COMPLETE
            
                # Get data payload
                data_str = None
                for attr in ['leftover_capture_data', 'capdata', 'usb_capdata']:
                    if hasattr(usb, attr):
                        data_str = getattr(usb, attr)
                        break
            
                if not data_str:
                    continue
            
                # Parse metadata
                endpoint, direction = extract_endpoint(usb)
                cmd_byte, payload = parse_hex_data(data_str)
                pkt_num = int(packet.number)
                timestamp = float(packet.frame_info.time_relative)
            
                command = UsbCommand(
                    endpoint=endpoint,
                    direction=direction,
                    command_byte=cmd_byte,
                    payload=payload,
                    raw_hex=data_str.replace(':', ''),
                    packet_num=pkt_num,
                    timestamp=timestamp,
                    urb_type=urb_type
                )
            
                # Pair SUBMIT with COMPLETE using URB ID
                if urb_type == 'SUBMIT' and direction == 'OUT':
                    if urb_id:
                        pending_requests[urb_id] = command
                    else:
                        # Fallback: use packet number + timestamp proximity
                        transactions.append(UsbTransaction(request=command))
                    
                elif urb_type == 'COMPLETE' and direction == 'IN':
                    if urb_id and urb_id in pending_requests:
                        req = pending_requests.pop(urb_id)
                        transactions.append(UsbTransaction(
                            request=req,
                            response=command,
                            urb_id=urb_id
                        ))
                    else:
                        # Orphan response
                        transactions.append(UsbTransaction(
                            request=command, 
                            response=command
                        ))
                    
            except Exception as e:
                continue
    
        capture.close()
    
        # Handle unmatched SUBMITs (no response captured)
        for urb_id, cmd in pending_requests.items():
            transactions.append(UsbTransaction(request=cmd, urb_id=urb_id))
    
        return transactions

    return (parse_usb_transactions,)


@app.cell
def _(parse_usb_transactions):
    transactions = parse_usb_transactions("./capture_wireshark/usbcap2.pcapng",device_addr=3,bus_id=1)
    
    # Print formatted output
    for i, txn in enumerate(transactions):
        print(f"\n=== Transaction {i+1} ===")
        req = txn.request
        
        print(f"Request (Pkt {req.packet_num}, EP{req.endpoint} {req.direction}):")
        print(f"  CMD: 0x{req.command_byte:02x}")
        print(f"  Payload: {req.payload.hex() if req.payload else 'empty'}")
        print(f"  Raw: {req.raw_hex}")
        
        if txn.response:
            resp = txn.response
            print(f"Response (Pkt {resp.packet_num}, took {txn.duration_ms:.2f}ms):")
            print(f"  CMD: 0x{resp.command_byte:02x}")
            print(f"  Payload: {resp.payload.hex() if resp.payload else 'empty'}")
        else:
            print("Response: [No response captured]")

    return


if __name__ == "__main__":
    app.run()
