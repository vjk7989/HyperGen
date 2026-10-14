# HyperGen - Installer Build Guide

This guide explains the HyperGen packaging policy and how to make a local developer build.

- For running from source and debugging: see [`README.md`](../README.md) and [`CONTRIBUTING.md`](CONTRIBUTING.md).
- For end-user requirements and first-run behavior: see [`README.md`](../README.md).

## What Gets Bundled

The installer includes:

- **Electron app** (React frontend + Electron shell)
- **Embedded Python** (version from [`backend/.python-version`](../backend/.python-version)) with all dependencies pre-installed:
  - PyTorch (CUDA on Windows/Linux, MPS on macOS)
  - FastAPI, Diffusers, Transformers
  - LTX-2 inference packages
  - All other required libraries
- **Backend Python code**

**NOT bundled** (downloaded at runtime):

- Model weights (downloaded on first run; can be large) from Hugging Face
- On **Linux** and **Windows**: the Python environment itself is downloaded on first launch (keeps installer small)

The embedded Python is **fully isolated** from the target system's Python — it lives inside `{install_dir}/resources/python/` and never modifies system settings.

## Official release packages

Official HyperGen packages are built only by GitHub Actions on native runners:

- Windows x64: NSIS installer
- Linux x64: AppImage and DEB
- macOS arm64: DMG and ZIP

The release workflow runs the complete quality gate, prepares the platform runtime, verifies package identity and runtime manifests, and uploads checksums and updater metadata with the packages. All platform jobs must pass before a draft release is published.

Current preview releases are **unsigned**. Windows may show an unknown-publisher warning, and macOS Gatekeeper may require the user to explicitly open the app. Signing and Apple notarization require maintainer credentials and are deferred.

Local builds are useful for development and smoke testing. They are not official release artifacts and must not be uploaded as though GitHub Actions produced them.

## Prerequisites

Before building, ensure you have:

1. **Node.js 18+** - https://nodejs.org/
2. **uv** - https://docs.astral.sh/uv/ (Python package manager)
3. **git** - needed for git-based Python packages
4. **Internet connection** (for downloading Python and packages)
5. **~15GB free space** (for Python environment + build artifacts; does not include model weights — see [README](../README.md) for full disk space requirements)

### Platform-Specific

- **Windows**: PowerShell 5.1+ (comes with Windows 10/11)
- **macOS**: Xcode Command Line Tools (`xcode-select --install`)
- **Linux**: `build-essential` (or equivalent) for native extensions

## Local developer build

```bash
pnpm build
```

This auto-detects your platform and will:

1. Download a standalone Python distribution (version from [`backend/.python-version`](../backend/.python-version))
2. Install all Python dependencies (~10GB on Windows/Linux with CUDA, ~2-3GB on macOS with MPS)
3. Build the frontend
4. Package everything with electron-builder
5. Create a DMG (macOS), AppImage + deb (Linux), or NSIS installer (Windows) in the `release/` folder

## Build Options

```bash
# Full build
pnpm build

# Skip Python setup (if already prepared)
pnpm build:skip-python

# Fast rebuild (unpacked, skip Python + pnpm install)
pnpm build:fast

# Just prepare Python environment
pnpm prepare:python
```

All commands auto-detect the current platform (macOS, Linux, or Windows).

### Build Script Options

The underlying `local-build.sh` / `local-build.ps1` scripts also accept:

- `--platform mac|linux|win` — Target platform (auto-detected if omitted)
- `--skip-python` — Use existing `python-embed/` directory
- `--clean` — Remove build artifacts before starting
- `--unpack` — Build unpacked app only (faster, no installer/DMG)

## Local build output

### macOS

```
release/
  ├── HyperGen-<version>-arm64.dmg
  └── HyperGen-<version>-arm64-mac.zip
```

### Linux

```
release/
  ├── HyperGen-x86_64.AppImage
  └── HyperGen-amd64.deb
```

### Windows

```
release/
  └── HyperGen-<version>-Setup.exe
```

## Application Icon

Place icon files in `resources/` before building:

- `icon.ico` — Windows (multi-size ICO: 256x256, 128x128, 64x64, 48x48, 32x32, 16x16)
- `icon.png` — macOS and Linux (1024x1024 recommended)

## Troubleshooting

### "Python not found" during build

Ensure you have internet access. The script downloads Python automatically.

### Build fails with CUDA errors

The build doesn't require a GPU. CUDA packages are pre-built binaries.

### macOS: "App is damaged" or Gatekeeper warning

On unsigned builds, macOS Gatekeeper may block the app. Right-click the app and select **Open**, or remove the quarantine attribute from the installed HyperGen app:

```bash
xattr -dr com.apple.quarantine /Applications/HyperGen.app
```

### Installer is too large

Expected installer sizes (does not include model weights):

- **Windows**: ~10GB (PyTorch CUDA ~2.5GB + ML libraries ~5GB + Python ~200MB + Electron ~100MB)
- **Linux**: ~10GB (similar to Windows; PyTorch CUDA variant)
- **macOS**: ~2-3GB (PyTorch MPS is much smaller than CUDA variant)

### Runtime / first-run issues

End-user topics like system requirements, first-run setup, and model download behavior are documented in [`README.md`](../README.md).

## Advanced: Manual Build Steps

### macOS

```bash
# 1. Prepare Python environment
bash scripts/prepare-python.sh

# 2. Install dependencies
pnpm install

# 3. Build frontend
pnpm build:frontend

# 4. Build DMG
pnpm exec electron-builder --mac

# Or build unpacked app (faster, for testing)
pnpm exec electron-builder --mac --dir
```

### Linux

```bash
# 1. Prepare Python environment
bash scripts/prepare-python.sh

# 2. Install dependencies
pnpm install

# 3. Build frontend
pnpm build:frontend

# 4. Build AppImage + deb
pnpm exec electron-builder --linux

# Or build unpacked app (faster, for testing)
pnpm exec electron-builder --linux --dir
```

### Windows

```powershell
# 1. Prepare Python environment
./scripts/prepare-python.ps1

# 2. Install dependencies
pnpm install

# 3. Build frontend
pnpm build:frontend

# 4. Build installer
pnpm exec electron-builder --win
```
