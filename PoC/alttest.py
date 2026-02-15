import usb.core
import usb.util

VENDOR_ID = 0x04F3
PRODUCT_ID = 0x0C4C


def testthis():

    # Find and configure device
    dev = usb.core.find(idVendor=VENDOR_ID, idProduct=PRODUCT_ID)

    # CRITICAL: Detach kernel driver if active
    interface = 0  # Usually interface 0
    if dev.is_kernel_driver_active(interface):
        print(f"Detaching kernel driver from interface {interface}")
        dev.detach_kernel_driver(interface)

    dev.set_configuration()

    # Claim interface (Linux usually requires this)
    usb.util.claim_interface(dev, interface)  # Interface 0

    # Known endpoints (example)
    EP_OUT = 0x01  # OUT endpoint (host → device)
    EP_IN = 0x81  # IN endpoint (device → host)

    # WRITE to OUT endpoint
    data = bytes([0x40, 0x19])
    bytes_written = dev.write(EP_OUT, data, timeout=5000)

    # READ from IN endpoint
    # Returns array.array('B') - convert to bytes if needed
    response = dev.read(EP_IN, size_or_buffer=2, timeout=5000)
    print(bytes(response))  # Convert to bytes
    usb.util.release_interface(dev, interface)
    dev.attach_kernel_driver(interface)


if __name__ == "__main__":
    testthis()
