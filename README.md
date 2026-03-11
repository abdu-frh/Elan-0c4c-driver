# libfprint driver for ELAN Fingerprint Reader (04f3:0c4c)


This is a driver for the **ELAN Match-on-Chip fingerprint reader** (`04f3:0c4c`) for [libfprint](https://gitlab.freedesktop.org/libfprint/libfprint).

Found in devices such as the **HP Envy 15 x360** and other laptops with this USB ID.

---

## Requirements

- Linux
- `libfprint` >= 1.94
- `meson` >= 0.50
- `ninja`
- `gcc` or `clang`
- `libgusb` development headers
- `glib2` development headers

### Install build dependencies

**Ubuntu/Debian:**
```bash
sudo apt install meson ninja-build gcc libgusb-dev libglib2.0-dev \
  libgirepository1.0-dev gtk-doc-tools
```

**Fedora/RHEL:**
```bash
sudo dnf install meson ninja-build gcc libgusb-devel glib2-devel \
  gobject-introspection-devel gtk-doc
```

**Arch Linux:**
```bash
sudo pacman -S meson ninja gcc libgusb glib2 gobject-introspection gtk-doc
```

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/abdu-frh/Elan-0c4c-driver.git
cd libfprint
```

### 2. Configure the build

```bash
meson setup builddir
```

### 3. Build

```bash
ninja -C builddir
```

### 4. Install

```bash
sudo ninja -C builddir install
```

### 5. Restart the fingerprint service

```bash
sudo systemctl restart fprintd
```

---

## Verify the device is recognized

```bash
lsusb | grep -i elan
```

You should see:
```
Bus XXX Device XXX: ID 04f3:0c4c Elan Microelectronics Corp. ELAN:Fingerprint
```

Then test with:
```bash
fprintd-enroll
```

---

## Enroll and use fingerprint authentication

**Enroll a fingerprint:**
```bash
fprintd-enroll
```

**Verify:**
```bash
fprintd-verify
```

Should also appear in the gnome settings under user

---
## Supported devices

| USB ID | Device |
|--------|--------|
| `04f3:0c4c` | ELAN Match-on-Chip Fingerprint Reader (HP Spectre x360 14" 2020) |

If your device uses the same USB ID and is not listed, it may still work. Feel free to open an issue with your laptop model.

---

## License

This driver is based on [libfprint](https://gitlab.freedesktop.org/libfprint/libfprint) and is licensed under the **GNU Lesser General Public License v2.1** — see [COPYING](COPYING) for details.
