import pyshark

# Used Enpoints 9
# Product string: ELAN:ARM-M4
# Number of open Pipes     : 0x08 (8 pipes to data endpoints)
# Pipe[0]                  : EndpointID=1  Direction=IN   ScheduleOffset=0  Type=Bulk  wMaxPacketSize=0x40    bInterval=1
# Pipe[1]                  : EndpointID=1  Direction=OUT  ScheduleOffset=0  Type=Bulk  wMaxPacketSize=0x40    bInterval=1
# Pipe[2]                  : EndpointID=2  Direction=IN   ScheduleOffset=0  Type=Bulk  wMaxPacketSize=0x40    bInterval=1
# Pipe[3]                  : EndpointID=2  Direction=OUT  ScheduleOffset=0  Type=Bulk  wMaxPacketSize=0x40    bInterval=1
# Pipe[4]                  : EndpointID=3  Direction=IN   ScheduleOffset=0  Type=Bulk  wMaxPacketSize=0x40    bInterval=1
# Pipe[5]                  : EndpointID=3  Direction=OUT  ScheduleOffset=0  Type=Bulk  wMaxPacketSize=0x40    bInterval=1
# Pipe[6]                  : EndpointID=4  Direction=IN   ScheduleOffset=0  Type=Bulk  wMaxPacketSize=0x40    bInterval=1
# Pipe[7]                  : EndpointID=4  Direction=OUT  ScheduleOffset=0  Type=Bulk  wMaxPacketSize=0x40    bInterval=1

# USB Handshake on
# 0x80
# 0x81
# 0x00
#
# USBView	Wireshark Filter	Richtung	Zweck
# EP1 OUT	usb.endpoint_address == 0x01	PC → ARM	Commands (wo 0x40, 0x19 reingehen)
# EP1 IN	usb.endpoint_address == 0x81	PC ← ARM	Antworten
# EP2-4	0x02/0x82, 0x03/0x83...	-	Wahrscheinlich für Firmware-Update oder Bilddaten


VENDOR_ID = 0x04F3
PRODUCT_ID = 0x0C4C

# Pick the correct interface on your machine
capture = pyshark.FileCapture("./capture_wireshark/usbcap1.pcapng")

capture
print(capture[23])
