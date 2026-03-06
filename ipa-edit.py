'''
About: 
    iPA-Edit is a Python script that can be used to edit and sign iPA files.
    It can be used to:
        - Sign iPA files
        - Unsign iPA files
        - Edit iPA files
        - Export dylibs from iPA files
        - Import dylibs into iPA files
        - Convert .deb files to .ipa files
        - Convert .ipa files to .deb files

    Usage: python ipa-edit.py -i <input_ipa> -o <output_ipa>
    
    Author [Remake]: SHAJON-404
    GitHub: https://github.com/SHAJON-404
    Website: https://shajon.dev
    
    License: GPLv3

    Original Author: https://github.com/binnichtaktiv
'''

import io
import os
import sys
import time
import atexit
import struct
import shutil
import tarfile
import zipfile
import platform
import plistlib
import argparse
import subprocess
from PIL import Image

# Colors
RED = "\033[91m"
GREEN = "\033[92m"
WHITE = "\033[97m"
RESET = "\033[0m"

SEP = f"{WHITE}{'-' * 80}{RESET}"


class DebExtractor:
    _GLOBAL_MAGIC = b"!<arch>\n"
    _ENTRY_SIZE = 60

    @staticmethod
    def extract(deb_path: str, outdir: str) -> None:
        system = platform.system()
        if system in ("Linux", "Darwin"):
            for tool, cmd in [
                ("dpkg-deb", ["dpkg-deb", "-x", deb_path, outdir]),
                ("ar", ["ar", "x", deb_path]),
            ]:
                if shutil.which(tool):
                    orig = os.getcwd()
                    try:
                        os.chdir(outdir)
                        result = subprocess.run(cmd, capture_output=True)
                        if result.returncode == 0:
                            if tool == "ar":
                                DebExtractor._unpack_data_tar(outdir)
                            return
                    finally:
                        os.chdir(orig)

        sevenzip = DebExtractor._find_7zip()
        if sevenzip:
            subprocess.run([sevenzip, "x", deb_path, f"-o{outdir}", "-y"],
                           check=True, capture_output=True)
            DebExtractor._unpack_data_tar(outdir)
            return

        DebExtractor._extract_manual(deb_path, outdir)

    @staticmethod
    def _find_7zip() -> str | None:
        for candidate in ("7z", "7za", "7zr",
                          r"C:\Program Files\7-Zip\7z.exe",
                          r"C:\Program Files (x86)\7-Zip\7z.exe"):
            if shutil.which(candidate) or os.path.isfile(candidate):
                return candidate
        return None

    @staticmethod
    def _unpack_data_tar(outdir: str) -> None:
        for name in os.listdir(outdir):
            if name.startswith("data.tar"):
                path = os.path.join(outdir, name)
                with tarfile.open(path) as tf:
                    tf.extractall(outdir)
                os.remove(path)
                return

    @staticmethod
    def _extract_manual(deb_path: str, outdir: str) -> None:
        with open(deb_path, "rb") as f:
            if f.read(8) != DebExtractor._GLOBAL_MAGIC:
                sys.exit("[-] Not a valid .deb (ar) archive.")
            while True:
                header = f.read(DebExtractor._ENTRY_SIZE)
                if len(header) < DebExtractor._ENTRY_SIZE:
                    break
                name = header[0:16].rstrip().decode("ascii", errors="replace").rstrip("/")
                size = int(header[48:58].strip())
                data = f.read(size)
                if size % 2:
                    f.read(1)
                if name.startswith("data.tar"):
                    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tf:
                        tf.extractall(outdir)
                    return
        sys.exit("[-] Data.tar not found inside .deb.")


class IPAEditor:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        self.temp_dir = os.path.join(self.script_dir, ".temp")
        self.app_path: str | None = None
        self.zip_path: str | None = None
        self.payload_path: str | None = None
        self.ipa_path: str | None = None
        self.ipa_files: list[str] = []
        self.output_dir: str | None = None
        self._register_cleanup()

    def _get_auto_out_path(self, suffix: str) -> str:
        base_name = os.path.basename(self.args.i) if self.args.i else "output"
        if base_name.lower().endswith(".ipa") or base_name.lower().endswith(".deb"):
            base_name = base_name[:-4]
            
        folder_name = "Signed" if suffix == "signed" else "Unsigned"
        folder_path = os.path.join(self.script_dir, folder_name)
        os.makedirs(folder_path, exist_ok=True)
        
        return os.path.join(folder_path, f"{base_name}_{suffix}.ipa")

    def _register_cleanup(self) -> None:
        atexit.register(self._remove_temp)

    def _remove_temp(self) -> None:
        if not os.path.isdir(self.temp_dir):
            return
        if os.path.abspath(os.getcwd()).startswith(os.path.abspath(self.temp_dir)):
            os.chdir(self.script_dir)
        for _ in range(3):
            try:
                shutil.rmtree(self.temp_dir)
                print(f"{WHITE}[*] Cleaned up .temp folder{RESET}")
                return
            except (PermissionError, OSError):
                time.sleep(0.5)

    def _ensure_temp(self) -> str:
        os.makedirs(self.temp_dir, exist_ok=True)
        return self.temp_dir

    def run(self) -> None:

        if not self.args.s and not self.args.e:
            self.ipa_path = self.args.i
            self.app_path, self.zip_path, self.payload_path = self._unzip_ipa(self.ipa_path)

        if self.args.n or self.args.b or self.args.v or self.args.f or self.args.p:
            self._edit_plist()

        if self.args.d:
            self._export_dylibs()

        if self.args.r:
            self._remove_and_sign()
        elif self.args.s:
            self._sign()

        if self.args.e:
            self._deb_to_ipa()

        if not self.args.d and not self.args.s and not self.args.e and not self.args.r:
            if self.ipa_path is None or self.payload_path is None:
                sys.exit("[-] Ipa_path or payload_path is not set.")
            self._zip_ipa()
        elif not self.args.s and not self.args.e and not self.args.r:
            self._restore_source()

        print(SEP)
        print("[+] Done")
        print(SEP)

    def _unzip_ipa(self, ipa_path: str) -> tuple[str, str, str]:
        print(SEP)
        print(f"{WHITE}[*] Extracting iPA{RESET}")
        temp = self._ensure_temp()
        zip_path = os.path.join(temp, os.path.basename(ipa_path).replace(".ipa", ".zip"))
        shutil.copy2(ipa_path, zip_path)

        if not os.path.exists(zip_path):
            sys.exit("[-] .ipa file could not be found.")

        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(temp)

        payload_path = os.path.join(temp, "Payload")
        app_folder = next((i for i in os.listdir(payload_path) if i.endswith(".app")), None)

        if app_folder is None:
            sys.exit("[-] .app folder not found inside iPA.")

        print(f"{GREEN}[+] Extracted iPA{RESET}")
        return os.path.join(payload_path, app_folder), zip_path, payload_path

    def _zip_ipa(self) -> None:
        print(SEP)
        print(f"{WHITE}[*] Generating iPA...{RESET}")
        if self.payload_path is None:
            sys.exit("[-] Payload_path is not set.")

        output = self.args.o if self.args.o else self._get_auto_out_path("unsigned")
        if output.endswith(".ipa"):
            output = output[:-4]

        shutil.make_archive(output, "zip", os.path.dirname(self.payload_path), os.path.basename(self.payload_path))
        zip_out = output + ".zip"
        ipa_out = output + ".ipa"
        os.replace(zip_out, ipa_out)

        if self.args.k:
            print(f"{WHITE}[*] Source iPA kept{RESET}")

        print(f"{GREEN}[+] Saved: {ipa_out}{RESET}")

    def _restore_source(self) -> None:
        print(f"{WHITE}[*] Restoring source files{RESET}")

    def _edit_plist(self) -> None:
        if self.app_path is None:
            sys.exit("[-] iPA not extracted.")
        print(SEP)
        print(f"{WHITE}[*] Editing Info.plist{RESET}")

        plist_path = os.path.join(self.app_path, "Info.plist")
        with open(plist_path, "rb") as f:
            pl = plistlib.load(f)

        if self.args.b:
            print(f"{WHITE}[*] BundleID: {pl['CFBundleIdentifier']} -> {self.args.b}{RESET}")
            pl["CFBundleIdentifier"] = self.args.b

        if self.args.n:
            key = "CFBundleDisplayName" if "CFBundleDisplayName" in pl else "CFBundleName"
            print(f"{WHITE}[*] App name: {pl.get(key)} -> {self.args.n}{RESET}")
            pl[key] = self.args.n

        if self.args.v:
            print(f"{WHITE}[*] Version: {pl['CFBundleShortVersionString']} -> {self.args.v}{RESET}")
            pl["CFBundleShortVersionString"] = self.args.v

        if self.args.p:
            self._apply_icon(pl)

        if self.args.f:
            pl["LSSupportsOpeningDocumentsInPlace"] = True
            pl["UIFileSharingEnabled"] = True
            print(f"{GREEN}[+] Enabled document browser{RESET}")

        with open(plist_path, "wb") as f:
            plistlib.dump(pl, f)
        print(f"{GREEN}[+] Plist saved{RESET}")

    def _apply_icon(self, pl: dict) -> None:
        if self.app_path is None:
            sys.exit("[-] iPA not extracted.")
        src = self.args.p
        if not src.endswith(".png"):
            with Image.open(src) as img:
                img.save(src, "PNG")

        with Image.open(src) as img:
            img.resize((120, 120)).save(os.path.join(self.app_path, "changedicon_60x60@2x.png"), "PNG")
            img.resize((152, 152)).save(os.path.join(self.app_path, "changedicon_76x76@2x~ipad.png"), "PNG")

        pl["CFBundleIcons"] = {
            "CFBundlePrimaryIcon": {
                "CFBundleIconFiles": ["changedicon_60x60"],
                "CFBundleIconName": "changedicon_",
            }
        }
        pl["CFBundleIcons~ipad"] = {
            "CFBundlePrimaryIcon": {
                "CFBundleIconFiles": ["changedicon_60x60", "changedicon_76x76"],
                "CFBundleIconName": "changedicon_",
            }
        }
        print(f"{GREEN}[+] Icon changed{RESET}")

    def _list_dylibs(self) -> list[str]:
        if self.app_path is None:
            sys.exit("[-] iPA not extracted.")
        dylibs: list[str] = []
        for root, dirs, files in os.walk(self.app_path):
            dylibs += [os.path.join(root, f) for f in files if f.endswith(".dylib")]
            frameworks = [d for d in dirs if d.endswith(".framework")]
            dylibs += [os.path.join(root, d) for d in frameworks]
            dirs[:] = [d for d in dirs if not d.endswith(".framework")]
        return dylibs

    def _export_dylibs(self) -> None:
        print(SEP)
        print(f"{WHITE}[*] Export dylibs{RESET}")
        dylibs = self._list_dylibs()

        if not dylibs:
            print(f"{RED}[-] No dylibs found{RESET}")
            return

        for i, f in enumerate(dylibs, 1):
            print(f"  {i}: {os.path.basename(f)}")

        selection = input("[?] File numbers (comma separated) or 'exit': ").strip().lower()
        if selection == "exit":
            print(f"{WHITE}[*] Export cancelled{RESET}")
            return

        selected = [dylibs[int(n.strip()) - 1] for n in selection.split(",")]

        if not os.path.exists(self.args.o):
            sys.exit("[-] Output folder does not exist.")

        exported_fw = exported_dl = False
        for f in selected:
            if os.path.isdir(f):
                shutil.copytree(f, os.path.join(self.args.o, os.path.basename(f)))
                exported_fw = True
            else:
                shutil.copy(f, self.args.o)
                exported_dl = True

        if exported_fw and exported_dl:
            print(f"{GREEN}[+] Exported .framework(s) and .dylib(s){RESET}")
        elif exported_fw:
            print(f"{GREEN}[+] Exported .framework(s){RESET}")
        else:
            print(f"{GREEN}[+] Exported .dylib(s){RESET}")

    def _remove_and_sign(self) -> None:
        print(SEP)
        print(f"{WHITE}[*] Remove dylibs & sign{RESET}")
        dylibs = self._list_dylibs()

        if not dylibs:
            print(f"{RED}[-] No dylibs found{RESET}")
            return

        for i, f in enumerate(dylibs, 1):
            print(f"  {i}: {os.path.basename(f)}")

        print(SEP)
        selection = input("[?] File numbers to DELETE (comma separated) or 'exit': ").strip().lower()
        if selection == "exit":
            print(f"{WHITE}[*] Cancelled{RESET}")
            return

        selected = [dylibs[int(n.strip()) - 1] for n in selection.split(",")]
        deleted_names: list[str] = []
        for f in selected:
            name = os.path.basename(f)
            deleted_names.append(name)
            if os.path.isdir(f):
                shutil.rmtree(f)
            else:
                os.remove(f)
            print(f"{RED}[-] Deleted: {name}{RESET}")
        print(f"{GREEN}[+] Dylib removal complete{RESET}")

        print(SEP)
        print(f"{WHITE}[*] Patching binary to remove dylib references{RESET}")
        self._patch_binary_remove_dylibs(deleted_names)
        print(f"{GREEN}[+] Binary patched{RESET}")

        print(SEP)
        print(f"{WHITE}[*] Re-packing iPA{RESET}")
        if self.payload_path is None:
            sys.exit("[-] Payload_path is not set.")
        temp = self._ensure_temp()
        temp_ipa = os.path.join(temp, "repacked")
        shutil.make_archive(temp_ipa, "zip", os.path.dirname(self.payload_path), os.path.basename(self.payload_path))
        temp_ipa_file = temp_ipa + ".zip"
        unsigned_ipa = temp_ipa + ".ipa"
        os.replace(temp_ipa_file, unsigned_ipa)

        ans = input("[?] Sign the patched iPA? [Y/n]: ").lower().strip()
        do_sign = ans in ("y", "yes", "")

        if do_sign:
            print(SEP)
            print(f"{WHITE}[*] Signing{RESET}")
            zsign = self._resolve_zsign()
            p12_path, mb_path = self._resolve_certificate()
            if not p12_path or not mb_path:
                p12_path = input("[?] .p12 path: ").strip(' "\'')
                mb_path = input("[?] .mobileprovision path: ").strip(' "\'')
            cert_pw = input("[?] Certificate password: ")
            print(SEP)

            signed_final = self.args.o if self.args.o else self._get_auto_out_path("signed")
            cmd = f'"{zsign}" -k "{p12_path}" -m "{mb_path}" -p "{cert_pw}" -o "{signed_final}" -z 9 "{unsigned_ipa}"'
            subprocess.run(cmd, shell=True)
            print(f"{GREEN}[+] Signed: {signed_final}{RESET}")
        else:
            unsigned_final = self.args.o if self.args.o else self._get_auto_out_path("unsigned")
            shutil.copy2(unsigned_ipa, unsigned_final)
            print(f"{GREEN}[+] Unsigned saved: {unsigned_final}{RESET}")

    def _find_main_executable(self) -> str | None:
        if self.app_path is None:
            return None
        plist_path = os.path.join(self.app_path, "Info.plist")
        if os.path.isfile(plist_path):
            with open(plist_path, "rb") as f:
                pl = plistlib.load(f)
            exe_name = pl.get("CFBundleExecutable")
            if exe_name:
                exe_path = os.path.join(self.app_path, exe_name)
                if os.path.isfile(exe_path):
                    return exe_path
        return None

    def _patch_binary_remove_dylibs(self, deleted_names: list[str]) -> None:
        exe = self._find_main_executable()
        if exe is None:
            print(f"{RED}[-] Main executable not found, skipping patch{RESET}")
            return

        with open(exe, "rb") as f:
            data = bytearray(f.read())

        magic = struct.unpack_from("<I", data, 0)[0]
        if magic == 0xCAFEBABE or magic == 0xBEBAFECA:
            nfat = struct.unpack_from(">I", data, 4)[0]
            for i in range(nfat):
                off = 8 + i * 20
                slice_offset = struct.unpack_from(">I", data, off + 8)[0]
                self._patch_macho_slice(data, slice_offset, deleted_names)
        elif magic in (0xFEEDFACE, 0xFEEDFACF):
            self._patch_macho_slice(data, 0, deleted_names)
        else:
            print(f"{RED}[-] Unknown binary format, skipping patch{RESET}")
            return

        with open(exe, "wb") as f:
            f.write(data)

    def _patch_macho_slice(self, data: bytearray, base: int, deleted_names: list[str]) -> None:
        magic = struct.unpack_from("<I", data, base)[0]
        is64 = magic == 0xFEEDFACF
        hdr_size = 32 if is64 else 28
        ncmds = struct.unpack_from("<I", data, base + 16)[0]
        sizeofcmds = struct.unpack_from("<I", data, base + 20)[0]

        LC_LOAD_DYLIB = 0x0C
        LC_LOAD_WEAK = 0x80000018
        LC_LAZY_LOAD = 0x20
        DYLIB_CMDS = (LC_LOAD_DYLIB, LC_LOAD_WEAK, LC_LAZY_LOAD)

        offset = base + hdr_size
        cmds_end = offset + sizeofcmds
        removed = 0
        i = 0
        while i < ncmds and offset < cmds_end:
            cmd = struct.unpack_from("<I", data, offset)[0]
            cmdsize = struct.unpack_from("<I", data, offset + 4)[0]
            if cmdsize == 0:
                break
            if cmd in DYLIB_CMDS:
                name_off = struct.unpack_from("<I", data, offset + 12)[0]
                name_start = offset + name_off
                name_end = data.index(0, name_start) if 0 in data[name_start:offset + cmdsize] else offset + cmdsize
                dylib_path = data[name_start:name_end].decode("utf-8", errors="replace")
                dylib_basename = dylib_path.rsplit("/", 1)[-1]
                if dylib_basename.endswith(".framework"):
                    dylib_basename = dylib_basename
                match = any(
                    dylib_basename == d or
                    dylib_basename == d.replace(".dylib", "") or
                    dylib_path.find(d.replace(".framework", "")) != -1 or
                    dylib_path.find(d.replace(".dylib", "")) != -1
                    for d in deleted_names
                )
                if match:
                    tail_start = offset + cmdsize
                    tail_end = cmds_end
                    data[offset:tail_end - cmdsize] = data[tail_start:tail_end]
                    data[tail_end - cmdsize:tail_end] = b"\x00" * cmdsize
                    sizeofcmds -= cmdsize
                    ncmds -= 1
                    removed += 1
                    continue
            offset += cmdsize
            i += 1

        if removed:
            struct.pack_into("<I", data, base + 16, ncmds)
            struct.pack_into("<I", data, base + 20, sizeofcmds)
            print(f"{GREEN}[+] Removed {removed} dylib reference(s) from binary{RESET}")

    def _resolve_zsign(self) -> str:
        platform_map = {"Windows": "windows/zsign.exe", "Darwin": "mac/zsign", "Linux": "linux/zsign"}
        local = os.path.join(self.script_dir, "zsign", platform_map.get(platform.system(), ""))
        if os.path.isfile(local):
            print(f"{WHITE}[*] Zsign: {local}{RESET}")
            return local
        if shutil.which("zsign"):
            return "zsign"
        return input("[?] Zsign path: ").strip(' "\'')

    def _resolve_certificate(self) -> tuple[str, str]:
        cert_dir = os.path.join(self.script_dir, "certificate")
        p12 = mp = ""
        if os.path.isdir(cert_dir):
            for f in os.listdir(cert_dir):
                if f.endswith(".p12"):
                    p12 = os.path.join(cert_dir, f)
                elif f.endswith(".mobileprovision"):
                    mp = os.path.join(cert_dir, f)
        if p12 and mp:
            print(f"{GREEN}[+] Cert: {os.path.basename(p12)} + {os.path.basename(mp)}{RESET}")
            return p12, mp
        return "", ""

    def _sign(self) -> None:
        print(SEP)
        print(f"{WHITE}[*] Signing{RESET}")
        zsign = self._resolve_zsign()
        p12_path, mb_path = self._resolve_certificate()

        if not self.args.i.endswith(".ipa"):
            self.output_dir = os.path.join(self.script_dir, "Signed")
            os.makedirs(self.output_dir, exist_ok=True)
            entries = os.listdir(self.args.i)
            self.ipa_files = [e for e in entries if e.endswith(".ipa")]
            if not p12_path or not mb_path:
                for entry in entries:
                    full = os.path.join(self.args.i, entry)
                    if entry.endswith(".p12"):
                        p12_path = full
                    elif entry.endswith(".mobileprovision"):
                        mb_path = full
                if p12_path and mb_path:
                    ans = input(f"[?] Use certificate found in {self.args.i}? [Y/n]: ").lower().strip()
                    if ans in ("y", "yes", ""):
                        print(f"[+] Cert: {p12_path} + {mb_path}")

        if not p12_path or not mb_path:
            p12_path = input("[?] .p12 path: ").strip(' "\'')
            mb_path = input("[?] .mobileprovision path: ").strip(' "\'')

        cert_pw = input("[?] Certificate password: ")

        if not self.args.i.endswith(".ipa"):
            if not self.ipa_files:
                sys.exit("[-] No .ipa files found in input directory.")
            if self.output_dir is None:
                sys.exit("[-] Output_dir is not set.")
            for ipa_file in self.ipa_files:
                src = os.path.join(self.args.i, ipa_file)
                base = ipa_file[:-4] if ipa_file.endswith(".ipa") else ipa_file
                dst = os.path.join(self.output_dir, f"{base}_signed.ipa")
                print(f"{WHITE}[*] Signing: {ipa_file}{RESET}")
                cmd = f'"{zsign}" -k "{p12_path}" -m "{mb_path}" -p "{cert_pw}" -o "{dst}" -z 9 "{src}"'
                subprocess.run(cmd, shell=True)
                print(f"{GREEN}[+] Signed: {dst}{RESET}")
        else:
            out_path = self.args.o if self.args.o else self._get_auto_out_path("signed")
            if not out_path.endswith(".ipa"):
                out_path += ".ipa"
            print(f"{WHITE}[*] Signing: {os.path.basename(self.args.i)}{RESET}")
            cmd = f'"{zsign}" -k "{p12_path}" -m "{mb_path}" -p "{cert_pw}" -o "{out_path}" -z 9 "{self.args.i}"'
            subprocess.run(cmd, shell=True)
            print(f"{GREEN}[+] Signed: {out_path}{RESET}")

    def _deb_to_ipa(self) -> None:
        print(SEP)
        print(f"{WHITE}[*] Converting .deb to .ipa{RESET}")
        temp = self._ensure_temp()
        deb_temp = os.path.join(temp, "deb_extract")
        os.makedirs(deb_temp, exist_ok=True)

        print(f"{WHITE}[*] Extracting deb{RESET}")
        DebExtractor.extract(self.args.i, deb_temp)

        apps_dir = os.path.join(deb_temp, "Applications")
        if not os.path.isdir(apps_dir):
            sys.exit("[-] Applications folder not found in deb.")

        app_folder = next((f for f in os.listdir(apps_dir) if f.endswith(".app")), None)
        if app_folder is None:
            sys.exit("[-] .app not found. Check: https://github.com/SHAJON-404/iPA-Edit/issues")

        print(f"{GREEN}[+] Found: {app_folder}{RESET}")
        src = os.path.join(apps_dir, app_folder)
        payload = os.path.join(deb_temp, "Payload")
        os.makedirs(payload, exist_ok=True)
        shutil.copytree(src, os.path.join(payload, app_folder))

        print(f"{WHITE}[*] Generating iPA{RESET}")
        output = self.args.o if self.args.o else self._get_auto_out_path("unsigned")
        if output.endswith(".ipa"):
            output = output[:-4]
        shutil.make_archive(output, "zip", os.path.dirname(payload), os.path.basename(payload))
        ipa_out = output + ".ipa"
        os.replace(output + ".zip", ipa_out)

        if self.args.k:
            print(f"{WHITE}[*] Source deb kept{RESET}")

        print(f"{GREEN}[+] Saved: {ipa_out}{RESET}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="iPA Edit – modify iPA files.")
    p.add_argument("-i", metavar="input",    type=str, help="input .ipa/.deb")
    p.add_argument("-o", metavar="output",   type=str, help="output path/name")
    p.add_argument("-b", metavar="bundleID", type=str, help="change bundle ID")
    p.add_argument("-n", metavar="name",     type=str, help="change app name")
    p.add_argument("-v", metavar="version",  type=str, help="change app version")
    p.add_argument("-p", metavar="icon",     type=str, help="change app icon")
    p.add_argument("-f", action="store_true", help="enable document browser")
    p.add_argument("-d", action="store_true", help="export injected .dylib(s)")
    p.add_argument("-r", action="store_true", help="remove .dylib(s) & sign")
    p.add_argument("-s", action="store_true", help="sign iPA(s) with a certificate")
    p.add_argument("-e", action="store_true", help=".deb to .ipa conversion")
    p.add_argument("-k", action="store_true", help="keep source iPA/deb")
    return p


def interactive_mode() -> argparse.Namespace:
    os.system("cls" if os.name == "nt" else "clear")
    print(SEP)
    print(f"{WHITE}[*] iPA Edit – Interactive Mode{RESET}")
    print(f"{WHITE}[*] Author: S. SHAJON{RESET}")
    print(f"{WHITE}[*] GitHub: https://github.com/SHAJON-404/iPA-Edit.git{RESET}")
    print(SEP)
    print("  1: Edit iPA (bundle ID, name, version, icon, file browser)")
    print("  2: Export dylibs from iPA")
    print("  3: Remove dylibs & sign iPA")
    print("  4: Sign iPA(s)")
    print("  5: Convert .deb to .ipa")
    print("  6: Change app icon")
    print("  7: Enable document browser")
    print("  8: Exit")
    print(SEP)

    choice = input("[?] Select option (1-8): ").strip()
    print(SEP)
    if choice == "8":
        sys.exit(f"{WHITE}[*] Bye{RESET}")

    args = argparse.Namespace(
        i=None, o="", b=None, n=None, v=None, p=None,
        f=False, d=False, r=False, s=False, e=False, k=False,
    )

    if choice == "1":
        args.i = input("[?] Input .ipa path: ").strip()
        print(SEP)
        b = input("[?] New bundle ID (enter to skip): ").strip()
        if b:
            args.b = b
        n = input("[?] New app name (enter to skip): ").strip()
        if n:
            args.n = n
        v = input("[?] New version (enter to skip): ").strip()
        if v:
            args.v = v
        p = input("[?] New icon path (enter to skip): ").strip()
        if p:
            args.p = p
        fb = input("[?] Enable document browser? [y/N]: ").lower().strip()
        if fb in ("y", "yes"):
            args.f = True
        k = input("[?] Keep source iPA? [y/N]: ").lower().strip()
        if k in ("y", "yes"):
            args.k = True

    elif choice == "2":
        args.i = input("[?] Input .ipa path: ").strip()
        args.o = input("[?] Output folder for exported dylibs: ").strip()
        args.d = True

    elif choice == "3":
        args.i = input("[?] Input .ipa path: ").strip()
        args.r = True

    elif choice == "4":
        args.i = input("[?] Input .ipa or folder path: ").strip()
        args.s = True

    elif choice == "5":
        args.i = input("[?] Input .deb path: ").strip()
        args.e = True
        k = input("[?] Keep source .deb? [y/N]: ").lower().strip()
        if k in ("y", "yes"):
            args.k = True

    elif choice == "6":
        args.i = input("[?] Input .ipa path: ").strip()
        args.p = input("[?] Icon image path: ").strip()

    elif choice == "7":
        args.i = input("[?] Input .ipa path: ").strip()
        args.f = True

    else:
        sys.exit("[-] Invalid option")

    if not args.i:
        sys.exit("[-] Input path is required.")

    return args


if __name__ == "__main__":
    try:
        if len(sys.argv) == 1:
            ns = interactive_mode()
        else:
            ns = build_parser().parse_args()
            if not ns.i or not ns.o:
                sys.exit("[-] -i and -o are required when using command-line arguments.")
                
        for attr in ['i', 'o', 'p']:
            val = getattr(ns, attr, None)
            if isinstance(val, str):
                setattr(ns, attr, val.strip(' "\''))
                
        IPAEditor(ns).run()
    except KeyboardInterrupt:
        print(f"\n{WHITE}[*] Interrupted, exiting.{RESET}")
        sys.exit(0)

