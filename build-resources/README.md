# Build Resources

This folder contains the generated HyperGen icons and related resources used by the platform packagers. The checked-in assets are derived from the HyperGen logo; keep every platform variant in sync when the logo changes.

## Required Files

Official packages are built only on native GitHub Actions runners. Local packaging is for development and smoke testing; see [`docs/INSTALLER.md`](../docs/INSTALLER.md).

### `icon.ico`

Windows multi-size icon containing 256, 128, 64, 48, 32, and 16 pixel variants.

### `icon.icns`

macOS application icon.

### `icon.png` and `icons/`

High-resolution source PNG and Linux desktop icon sizes.

### `icon_source.svg`

Vector source used to regenerate the platform assets.

### Optional: `installer-sidebar.bmp`

A 164x314 BMP image for the NSIS installer sidebar.
