import pyshark

# Pick the correct interface on your machine
capture = pyshark.FileCapture("./capture_wireshark/usbcap1.pcapng")
