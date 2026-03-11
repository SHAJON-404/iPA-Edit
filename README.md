<p align="center">
  <h1 align="center">iPA Edit</h1>
  <p align="center">
    A powerful cross-platform tool for modifying, signing, and converting iOS <code>.ipa</code> files.
    <br /><br />
    <img src="https://img.shields.io/badge/version-v1.2-6b63ff?style=flat-square" alt="Version" />
    <img src="https://img.shields.io/badge/python-3.10+-blue?style=flat-square&logo=python&logoColor=white" alt="Python" />
    <img src="https://img.shields.io/badge/license-GPLv3-green?style=flat-square" alt="License" />
    <img src="https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey?style=flat-square" alt="Platform" />
    <br /><br />
    <a href="https://github.com/SHAJON-404/iPA-Edit/releases">📦 Download</a>
    ·
    <a href="https://github.com/SHAJON-404/iPA-Edit/issues">Report Bug</a>
    ·
    <a href="https://github.com/SHAJON-404/iPA-Edit/issues">Request Feature</a>
  </p>
</p>

---

## ✨ Features

- **Edit iPA metadata** — change bundle ID, app name, version, and icon
- **Inject tweaks** — add `.dylib` and `.deb` tweaks from the `tweaks/` folder, with automatic CydiaSubstrate bundling (via ElleKit) and `@rpath` patching
- **Remove injected dylibs** — delete tweaks and patch the Mach-O binary to strip load commands
- **Code signing** — sign single or batch iPAs using `zsign` with auto-detected certificates
- **Dylib export** — extract `.dylib` and `.framework` files to `tweaks_extracted/`
- **Deb → iPA conversion** — convert Cydia `.deb` packages to installable `.ipa` files
- **Interactive mode** — run without arguments for a guided menu-driven experience
- **Cross-platform** — works on Windows, macOS, and Linux

## 📁 Project Structure

```
iPA-Edit/
├── ipa-edit.py              # main script
├── requirements.txt
├── certificate/            # place signing certificates here
│   ├── *.p12
│   └── *.mobileprovision
├── tweaks/                 # place .dylib or .deb tweaks here for injection
├── tweaks_extracted/       # exported dylibs land here (auto-created)
├── resources/              # place ellekit.deb here for CydiaSubstrate fallback
├── zsign/                  # bundled zsign binaries (auto-detected)
│   ├── windows/zsign.exe
│   ├── mac/zsign
│   └── ubuntu/zsign
├── Signed/                 # signed output (auto-created)
└── Unsigned/               # unsigned output (auto-created)
```

## 🚀 Getting Started

### Prerequisites

- **Python 3.10+**
- **Pillow** — `pip install Pillow`

### Installation

```bash
git clone --depth=1 https://github.com/SHAJON-404/iPA-Edit.git
cd iPA-Edit
pip install -r requirements.txt
```

### Signing Setup *(optional)*

1. Place your `.p12` certificate and `.mobileprovision` profile in the `certificate/` folder.
2. The matching `zsign` binary for your OS is detected automatically from the `zsign/` directory.

### Tweak Setup

Place any `.dylib` or `.deb` tweak files in the `tweaks/` folder. They will appear in the numbered list when using option **8**.

## 🖥️ Platform Support

| Feature | Windows | macOS | Linux |
|:--|:--:|:--:|:--:|
| iPA editing | ✅ | ✅ | ✅ |
| iPA signing | ✅ | ✅ | ✅ |
| Tweak injection | ✅ | ✅ | ✅ |
| `.deb` → `.ipa` | ✅ 7-Zip / built-in | ✅ dpkg-deb / ar | ✅ dpkg-deb / ar |

## 📖 Usage

### Interactive Mode

Simply run with no arguments:

```bash
python ipa-edit.py
```

You'll see a menu:

```
  1: Edit iPA (bundle ID, name, version, icon, file browser)
  2: Export dylibs from iPA
  3: Remove dylibs & sign iPA
  4: Sign iPA(s)
  5: Convert .deb to .ipa
  6: Change app icon
  7: Enable document browser
  8: Add tweaks to iPA
  9: Exit
```

### Command-Line Mode

```bash
python ipa-edit.py -i <input> -o <output> [options]
```

| Flag | Description |
|:--|:--|
| `-i` | Input `.ipa` or `.deb` file |
| `-o` | Output path or filename |
| `-b` | Change bundle ID |
| `-n` | Change app display name |
| `-v` | Change app version |
| `-p` | Change app icon (any image format) |
| `-f` | Enable iOS document browser |
| `-d` | Export injected `.dylib` / `.framework` files |
| `-r` | Remove selected dylibs, patch binary, and sign |
| `-s` | Sign iPA(s) with a certificate |
| `-e` | Convert `.deb` to `.ipa` |
| `-k` | Keep the original source file |
| `-tw` | Inject tweaks from `tweaks/` folder (interactive) |

### Examples

```bash
# Edit metadata
python ipa-edit.py -i app.ipa -o patched.ipa -b com.new.id -n "My App" -v 2.0

# Inject tweaks (interactive selection)
python ipa-edit.py -i app.ipa -tw

# Remove injected tweaks & sign
python ipa-edit.py -i app.ipa -o . -r

# Sign a single iPA
python ipa-edit.py -i app.ipa -o signed.ipa -s

# Batch sign all iPAs in a folder
python ipa-edit.py -i ./ipas/ -o ./output/ -s

# Convert .deb to .ipa
python ipa-edit.py -i tweak.deb -o converted.ipa -e
```

## 💉 Tweak Injection

Place `.dylib` or `.deb` files in the `tweaks/` folder, then select option **8** (or use `-tw`):

```
[*] Available tweaks:
  1: AboutME.dylib  (518 KB)
  2: blatantsPatch.dylib  (103 KB)
  3: some_tweak.deb  (1.2 MB)

[?] use , for multiple | 'all' for every tweak | 'exit' to cancel
[?] Tweak number(s) to inject: 1,2,3
```

**Advanced Injection System:**
- **.deb Support**: Automatically unzips `.deb` files and locates the correct `MobileSubstrate` dynamic libraries to inject.
- **Auto-Substrate Bundling**: If any tweak requires `CydiaSubstrate`, the script will automatically extract `ellekit.deb` from the `resources/` folder and bundle `CydiaSubstrate.framework` natively inside the app!
- **Path Patching**: Fixes hardcoded jailbreak paths (e.g. `/Library/Frameworks/...`) to standard `@rpath/` iOS paths before injection, effectively eliminating kernel AMFI/sandbox crash issues on jailed devices.

## 🔐 Certificate & Zsign Auto-Detection

When using `-s`, `-r`, or `-tw`, certificates and the signing tool are resolved automatically:

**zsign** — checked in order:
1. Bundled binary from `zsign/{windows,mac,ubuntu}/`
2. `zsign` on system `PATH`
3. Manual prompt as fallback

**Certificate** — checked in order:
1. `certificate/` folder (`.p12` + `.mobileprovision`)
2. Input directory (batch signing scenario)
3. Manual prompt as fallback

## 📝 License

This project is licensed under the **GPLv3** License.

## 🙏 Credits

- Original project by [binnichtaktiv](https://github.com/binnichtaktiv)
- Rewritten and maintained by [SHAJON-404](https://github.com/SHAJON-404)

---

<p align="center">
  <a href="https://github.com/SHAJON-404/iPA-Edit/issues">Issues</a> · <a href="https://shajon.dev">Contact</a>
</p>

[![Stargazers over time](https://starchart.cc/SHAJON-404/iPA-Edit.svg?background=%231e1e1e&axis=%23f9f9f9&line=%236b63ff)](https://starchart.cc/SHAJON-404/iPA-Edit)
