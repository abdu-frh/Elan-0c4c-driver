
#include <stdio.h>
#include "libusb-1.0/libusb.h"


int main() {
    libusb_context *ctx = NULL;

    int r = libusb_init(&ctx);
    if (r < 0) {
        printf("Init error\n");
        return 1;
    }

    printf("libusb initialized successfully!\n");

    libusb_exit(ctx);
    return 0;
}
