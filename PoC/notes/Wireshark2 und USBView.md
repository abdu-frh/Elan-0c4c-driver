## Archtitektur
PC (Wireshark) ←→ USB Bulk ←→ ARM-M4 (im Fingerprint-Gehäuse) ←→ I2C ←→ Fingerprint Sensor-Chip

## Aufbau von Wireshark packet

#### Req (Bulk Out):
[USB Header] [Vendor Header] [I2C Register] [I2C Command] [Len?]
                     ↓              ↓            ↓
                   0x??          0x40         0x19


| USBView | Wireshark Filter               | Richtung | Zweck                                             |
| ------- | ------------------------------ | -------- | ------------------------------------------------- |
| EP1 OUT | `usb.endpoint_address == 0x01` | PC → ARM | **Commands** (wo 0x40, 0x19 reingehen)            |
| EP1 IN  | `usb.endpoint_address == 0x81` | PC ← ARM | **Antworten**                                     |
| EP2-4   | `0x02/0x82`, `0x03/0x83`...    | -        | Wahrscheinlich für Firmware-Update oder Bilddaten |
