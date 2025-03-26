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

VENDOR_ID = 0x04F3
PRODUCT_ID = 0x0C4C
SUPPORTED_VERSION = 3.05

ERRORS = {
    0x41: "",
    0x42: "",
    0x43: "",
    0x44: "",
    0xfb: "",
    0xfd: "",
    0xfe: "",
    0xdd: ""
}

def handle_info():
    'Placeholder for info logic'

def handle_reset():
    'Placeholder for reset logic'

def handle_enroll():
    'Placeholder for enrollment logic'

def handle_verify():
    'Placeholder for verification logic'

def main(args):

    command_router = {
        'init': handle_info,
        'scan': handle_reset,
        'enroll': handle_enroll,
        'verify': handle_verify
    }

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