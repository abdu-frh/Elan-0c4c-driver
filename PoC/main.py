import sys
import docopt

"""
ELAN 04F3:0C4C fingerprint reader driver PoC.
Usage:
  main.py (-h | --help)
  main.py info
  main.py reset
  main.py enroll
  main.py verify

Commands:
  info        Get device info
  reset       Reset the device
  enroll      Enroll a new fingerprint
  verify      Verify a fingerprint

Options:
  -h, --help  Show this help message and exit
"""

"""
old spec info:
#define ELAN_MOC_DRIVER_FULLNAME "Elan MOC Sensors"
#define ELAN_M0C_CMD_LEN 0x3
#define ELAN_EP_CMD_OUT (0x1 | LIBUSB_ENDPOINT_OUT)
#define ELAN_EP_CMD_IN (0x3 | LIBUSB_ENDPOINT_IN)
#define ELAN_EP_MOC_CMD_IN (0x4 | LIBUSB_ENDPOINT_IN)
#define ELAN_EP_IMG_IN (0x2 | LIBUSB_ENDPOINT_IN)

new spec info:
Device Info: {
'endpoints': {'IN': [129, 130, 131, 132],
'OUT': [1, 2, 3, 4]},
'max_packet_size': {129: 64, 1: 64, 130: 64, 2: 64, 131: 64, 3: 64, 132: 64, 4: 64},
'interfaces': [0],
'configuration': <CONFIGURATION 1: 100 mA>}

"""

VENDOR_ID = 0x04F3
PRODUCT_ID = 0x0C4C
SUPPORTED_VERSION = 3.05

IO = {
    'Unkown_IN': 0x81, #Unkown
    'Unkown_OUT': 0x01, #Unkown
    'IMG_IN': 0x82,
    'IMG_OUT': 0x02, #Unkown
    'CMD_IN': 0x83,
    'CMD_OUT': 0x03, #Unkown
    'MOC_CMD_IN': 0x84,
    'MOC_CMD_OUT': 0x04 #Unkown
}

CONFIG = {
    5000 : "ELAN_CMD_TIMEOUT",
    92: "ELAN_MAX_USER_ID_LEN",
    9: "ELAN_MAX_ENROLL_NUM",
    500: "ELAN_CAL_RETRY",
    64: "ELAN_MAX_PACKET_SIZE",
    3: "ELAN_MAX_HDR_LEN"
}

ENROLLS = {
    "ENROLL_RSP_RETRY":               0,
    "ENROLL_RSP_ENROLL_REPORT":       1,
    "ENROLL_RSP_ENROLL_OK":           2,
    "ENROLL_RSP_ENROLL_CANCEL_REPORT":3,
    "ENROLL_NUM_STATES":              4
}

ERRORS = {
    0xfd: "ELAN_MSG_VERIFY_ERR",
    0xfb: "ELAN_MSG_DIRTY",
    0xfe: "ELAN_MSG_AREA_NOT_ENOUGH",
    0x41: "ELAN_MSG_TOO_HIGH",
    0x42: "ELAN_MSG_TOO_LEFT",
    0x43: "ELAN_MSG_TOO_LOW",
    0x44: "ELAN_MSG_TOO_RIGHT",
    0x00: "ELAN_MSG_OK"
}

def handle_info():
    print("Simulated device info:")
    print("  Vendor ID: 0x{:04X}".format(VENDOR_ID))
    print("  Product ID: 0x{:04X}".format(PRODUCT_ID))
    print("  Supported Protocol Version: {:.2f}".format(SUPPORTED_VERSION))
    print("  Endpoints IN: {}".format(IO['CMD_IN']))
    print("  Endpoints OUT: {}".format(IO['CMD_OUT']))

def handle_reset():
    'Placeholder for reset logic'

def handle_enroll():
    'Placeholder for enrollment logic'

def handle_verify():
    'Placeholder for verification logic'

command_router = {
    'init': handle_info,
    'scan': handle_reset,
    'enroll': handle_enroll,
    'verify': handle_verify
}

def main(args):

    # Handle help first
    if args['--help'] or args['-h']:
        print(__doc__)
        return

    # Route to the appropriate command handler
    for command, handler in command_router.items():
        if args.get(command, False):
            handler()
            return

    # If no command matches
    print("Invalid command. Use --help for usage information.")
    sys.exit(1)

if __name__ == '__main__':
    try:
        args = docopt.docopt(__doc__)
        main(args)
    except docopt.DocoptLanguageError:
        print("Error in command syntax. Use --help for usage information.")
        sys.exit(1)
