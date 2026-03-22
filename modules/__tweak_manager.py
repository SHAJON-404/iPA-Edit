"""
tweak_manager.py — Tweak injection and removal logic for iPA-Edit.
"""

import os
import sys
import zipfile
import shutil
import plistlib

from .__constants import RED, GREEN, WHITE, RESET, SEP
from .__deb_extractor import DebExtractor
from .__macho_utils import inject_lc_load_weak_dylib, change_macho_dylib_path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def list_tweaks(script_dir: str) -> list[str]:
    """Return sorted list of .dylib / .deb / .framework paths in tweaks/."""
    tweaks_dir = os.path.join(script_dir, "tweaks")
    if not os.path.isdir(tweaks_dir):
        return []
    return sorted(
        os.path.join(tweaks_dir, f)
        for f in os.listdir(tweaks_dir)
        if f.endswith((".dylib", ".deb", ".framework"))
    )


def dylib_needs_substrate(dylib_path: str) -> bool:
    """Return True if the dylib references CydiaSubstrate or libhooker."""
    try:
        with open(dylib_path, "rb") as f:
            raw = f.read()
        return b"CydiaSubstrate" in raw or b"libhooker" in raw or b"libsubstrate" in raw
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Tweak injection
# ---------------------------------------------------------------------------

def add_tweaks(editor) -> None:
    """
    Inject selected tweaks from the tweaks/ folder into source_ipa.

    Parameters
    ----------
    editor : IPAEditor
        The calling editor instance (used for path resolution helpers).
    """
    print(SEP)
    print(f"{WHITE}[*] Add Tweaks to iPA{RESET}")

    source_ipa = editor.ipa_path
    tweaks     = list_tweaks(editor.script_dir)
    if not tweaks:
        sys.exit(f"{RED}[-] No .dylib or .deb files found in tweaks/ folder.{RESET}")

    print(f"{WHITE}[*] Available tweaks:{RESET}")
    for i, t in enumerate(tweaks, 1):
        size_kb = os.path.getsize(t) // 1024
        print(f"  {i}: {os.path.basename(t)}  ({size_kb} KB)")
    print(SEP)

    print("[?] use , for multiple  |  'all' for every tweak  |  'exit' to cancel")
    selection = input("[?] Tweak number(s) to inject: ").strip().lower()

    if selection == "exit":
        print(f"{WHITE}[*] Cancelled{RESET}")
        return

    if selection == "all":
        chosen = tweaks
    else:
        try:
            chosen = [tweaks[int(n.strip()) - 1] for n in selection.split(",")]
        except (ValueError, IndexError):
            sys.exit("[-] Invalid selection.")

    print(SEP)
    print(f"{WHITE}[*] Tweaks to inject:{RESET}")
    for tp in chosen:
        print(f"  {GREEN}+{RESET} {os.path.basename(tp)}")
    print(SEP)

    ans     = input("[?] Sign the output iPA? [Y/n]: ").lower().strip()
    do_sign = ans in ("y", "yes", "")

    zsign = editor._resolve_zsign()
    temp  = editor._ensure_temp()

    unsigned_path = os.path.join(temp, "_tweaked_unsigned.ipa")
    out_path = editor.args.o if editor.args.o else editor._get_auto_out_path(
        "tweaked_signed" if do_sign else "tweaked_unsigned"
    )
    if not out_path.endswith(".ipa"):
        out_path += ".ipa"

    # Read IPA metadata
    app_folder_name: str | None = None
    exe_name: str | None = None
    existing_files = set()
    with zipfile.ZipFile(source_ipa, "r") as zf:
        namelist = zf.namelist()
        existing_files = set(e.replace("\\", "/") for e in namelist)
        for entry in namelist:
            parts = entry.replace("\\", "/").split("/")
            if (len(parts) == 3 and parts[0] == "Payload"
                    and parts[1].endswith(".app") and parts[2] == "Info.plist"):
                try:
                    pl = plistlib.loads(zf.read(entry))
                    exe_name        = pl.get("CFBundleExecutable")
                    app_folder_name = parts[1]
                except Exception:
                    pass
                break

    if not app_folder_name or not exe_name:
        sys.exit(f"{RED}[-] Could not locate .app or executable inside IPA.{RESET}")

    fw_prefix = f"Payload/{app_folder_name}/Frameworks/"
    exe_entry = f"Payload/{app_folder_name}/{exe_name}"

    extra_dylibs:   list[str] = []
    extra_fws:      list[str] = []
    needs_substrate = False

    for t in chosen:
        if t.endswith(".deb"):
            print(f"{WHITE}[*] Extracting tweak deb: {os.path.basename(t)}{RESET}")
            tname = os.path.basename(t).replace(".deb", "")
            tout  = os.path.join(temp, f"deb_{tname}")
            os.makedirs(tout, exist_ok=True)
            DebExtractor.extract(t, tout)
            ms_dir = os.path.join(tout, "Library", "MobileSubstrate", "DynamicLibraries")
            if os.path.isdir(ms_dir):
                for f in os.listdir(ms_dir):
                    if f.endswith(".dylib"):
                        zp = fw_prefix + f
                        if zp in existing_files:
                            print(f"{GREEN}[*]{RESET} {f} already exists in iPA, skipping.")
                            continue
                        dp = os.path.join(ms_dir, f)
                        extra_dylibs.append(dp)
                        if dylib_needs_substrate(dp):
                            needs_substrate = True
        elif t.endswith(".dylib"):
            f = os.path.basename(t)
            zp = fw_prefix + f
            if zp in existing_files:
                print(f"{GREEN}[*]{RESET} {f} already exists in iPA, skipping.")
                continue
            extra_dylibs.append(t)
            if dylib_needs_substrate(t):
                needs_substrate = True
        elif t.endswith(".framework"):
            f = os.path.basename(t)
            zp_prefix = fw_prefix + f + "/"
            if any(ef.startswith(zp_prefix) for ef in existing_files) or (fw_prefix + f) in existing_files:
                print(f"{GREEN}[*]{RESET} {f} already exists in iPA, skipping.")
                continue
            extra_fws.append(t)

    extra_fw_files: list[tuple[str, str]] = []   # (local_path, zip_entry)

    if needs_substrate:
        cs_prefix = fw_prefix + "CydiaSubstrate.framework/"
        if any(ef.startswith(cs_prefix) for ef in existing_files) or (fw_prefix + "CydiaSubstrate.framework") in existing_files:
            print(f"{GREEN}[*]{RESET} CydiaSubstrate.framework already exists in iPA, skipping bundle.")
        else:
            print(f"{WHITE}[*] Tweak requires CydiaSubstrate, bundling ElleKit{RESET}")
        ellekit_deb = os.path.join(editor.script_dir, "tweaks", "ellekit.deb")
        if not os.path.isfile(ellekit_deb):
            print(f"{RED}[!] Missing ellekit.deb in tweaks/ folder!{RESET}")
            ans2 = input("[?] Continue without substrate? [y/N]: ").lower().strip()
            if ans2 not in ("y", "yes"):
                return
        else:
            ek_out = os.path.join(temp, "ellekit_extract")
            os.makedirs(ek_out, exist_ok=True)
            DebExtractor.extract(ellekit_deb, ek_out)
            cs_fw = os.path.join(ek_out, "Library", "Frameworks", "CydiaSubstrate.framework")
            if os.path.isdir(cs_fw):
                for root, dirs, files in os.walk(cs_fw):
                    for f in files:
                        lp  = os.path.join(root, f)
                        rel = os.path.relpath(lp, cs_fw).replace("\\", "/")
                        zp  = fw_prefix + "CydiaSubstrate.framework/" + rel
                        extra_fw_files.append((lp, zp))
                print(f"{GREEN}[+] Bundled CydiaSubstrate.framework from ElleKit{RESET}")
            else:
                print(f"{RED}[!] CydiaSubstrate.framework not found in ellekit.deb{RESET}")

    # Pre-patch tweaks: fix hardcoded jailbreak CydiaSubstrate paths
    print(f"{WHITE}[*] Fixing hardcoded paths in tweaks{RESET}")
    for d in extra_dylibs:
        if d.endswith(".dylib"):
            change_macho_dylib_path(d,
                "/Library/Frameworks/CydiaSubstrate.framework/CydiaSubstrate",
                "@rpath/CydiaSubstrate.framework/CydiaSubstrate")
            change_macho_dylib_path(d,
                "/Library/MobileSubstrate/DynamicLibraries/CydiaSubstrate.framework/CydiaSubstrate",
                "@rpath/CydiaSubstrate.framework/CydiaSubstrate")

    # Build new IPA with patched binary + dylibs in Frameworks/
    print(f"{WHITE}[*] Patching binary and building temp IPA{RESET}")
    with zipfile.ZipFile(source_ipa, "r") as zin:
        with zipfile.ZipFile(unsigned_path, "w", zipfile.ZIP_DEFLATED) as zout:
            written_entries = set()
            for item in zin.infolist():
                raw        = zin.read(item.filename)
                normalized = item.filename.replace("\\", "/")

                if normalized in written_entries:
                    continue
                
                if normalized == exe_entry:
                    ba = bytearray(raw)
                    for d in extra_dylibs:
                        lc_path = f"@executable_path/Frameworks/{os.path.basename(d)}"
                        inject_lc_load_weak_dylib(ba, lc_path)
                        print(f"  {WHITE}→{RESET} Injected load cmd: {lc_path}")
                    raw = bytes(ba)

                zout.writestr(item, raw)
                written_entries.add(normalized)

            for d in extra_dylibs:
                name = os.path.basename(d)
                zp = fw_prefix + name
                if zp not in written_entries:
                    with open(d, "rb") as f:
                        zout.writestr(zp, f.read())
                    written_entries.add(zp)
                    print(f"  {GREEN}+{RESET} {zp}")

            for fw in extra_fws:
                fw_name = os.path.basename(fw)
                if os.path.isdir(fw):
                    for root, dirs, files in os.walk(fw):
                        for f in files:
                            lp  = os.path.join(root, f)
                            rel = os.path.relpath(lp, fw).replace("\\", "/")
                            zp  = fw_prefix + fw_name + "/" + rel
                            if zp not in written_entries:
                                with open(lp, "rb") as fin:
                                    zout.writestr(zp, fin.read())
                                written_entries.add(zp)
                else:
                    zp = fw_prefix + fw_name
                    if zp not in written_entries:
                        with open(fw, "rb") as fin:
                            zout.writestr(zp, fin.read())
                        written_entries.add(zp)
                print(f"  {GREEN}+{RESET} {fw_prefix}{fw_name}")

            for lp, zp in extra_fw_files:
                if zp not in written_entries:
                    with open(lp, "rb") as f:
                        zout.writestr(zp, f.read())
                    written_entries.add(zp)
            if extra_fw_files:
                print(f"  {GREEN}+{RESET} {fw_prefix}CydiaSubstrate.framework")

    print(SEP)
    import subprocess
    if do_sign:
        print(f"{WHITE}[*] Signing injected iPA{RESET}")
        p12_path, mb_path = editor._resolve_certificate()
        if not p12_path or not mb_path:
            sys.exit(f"{RED}[-] Certificate or Mobile Provision not provided.{RESET}")
        cert_pw = input("[?] Certificate password: ")
        print(SEP)
        cmd = (
            f'"{zsign}" -k "{p12_path}" -m "{mb_path}" -p "{cert_pw}"'
            f' -o "{out_path}" -z 9 "{unsigned_path}"'
        )
        subprocess.run(cmd, shell=True)
        if os.path.isfile(out_path):
            print(f"{GREEN}[+] Tweaked & signed: {out_path}{RESET}")
        else:
            print(f"{RED}[-] zsign signing failed — output IPA not found{RESET}")
    else:
        shutil.copy2(unsigned_path, out_path)
        print(f"{GREEN}[+] Tweaked (unsigned): {out_path}{RESET}")


# ---------------------------------------------------------------------------
# Tweak removal
# ---------------------------------------------------------------------------

def remove_tweaks(editor) -> None:
    """
    Remove specified tweaks from source_ipa and optionally re-sign.

    Parameters
    ----------
    editor : IPAEditor
        The calling editor instance.
    """
    print(SEP)
    print(f"{WHITE}[*] Remove Tweaks from iPA{RESET}")

    source_ipa = editor.ipa_path
    targets    = [t.strip() for t in editor.args.rm_tw.split(",")]

    ans     = input("[?] Sign the output iPA? [Y/n]: ").lower().strip()
    do_sign = ans in ("y", "yes", "")

    zsign = editor._resolve_zsign()
    temp  = editor._ensure_temp()

    unsigned_path = os.path.join(temp, "_detweaked_unsigned.ipa")

    app_folder_name = None
    with zipfile.ZipFile(source_ipa, "r") as zf:
        for entry in zf.namelist():
            parts = entry.replace("\\", "/").split("/")
            if len(parts) >= 2 and parts[0] == "Payload" and parts[1].endswith(".app"):
                app_folder_name = parts[1]
                break

    if not app_folder_name:
        sys.exit(f"{RED}[-] Could not locate .app inside IPA.{RESET}")

    fw_prefix = f"Payload/{app_folder_name}/Frameworks/"

    removed_files = []
    print(f"{WHITE}[*] Removing tweak files from IPA archive{RESET}")
    with zipfile.ZipFile(source_ipa, "r") as zin:
        with zipfile.ZipFile(unsigned_path, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                normalized    = item.filename.replace("\\", "/")
                should_remove = False

                if normalized.startswith(fw_prefix):
                    file_name = normalized[len(fw_prefix):].split("/")[0]
                    for target in targets:
                        if file_name in (target, f"{target}.dylib", f"{target}.framework"):
                            should_remove = True
                            if file_name not in removed_files:
                                removed_files.append(file_name)
                            break

                if not should_remove:
                    zout.writestr(item, zin.read(item.filename))

    for rf in removed_files:
        print(f"  {RED}-{RESET} Removed {rf} from Frameworks")

    # Inject CydiaSubstrate.framework if it was removed
    cs_fw_present = False
    with zipfile.ZipFile(unsigned_path, "r") as zcheck:
        cs_prefix     = fw_prefix + "CydiaSubstrate.framework/"
        cs_fw_present = any(
            e.replace("\\", "/").startswith(cs_prefix) for e in zcheck.namelist()
        )

    if not cs_fw_present:
        ellekit_deb = os.path.join(editor.script_dir, "tweaks", "ellekit.deb")
        if os.path.isfile(ellekit_deb):
            print(f"{WHITE}[*] CydiaSubstrate.framework Not Found — adding it from ellekit.deb{RESET}")
            ek_out = os.path.join(temp, "ellekit_extract_rm")
            os.makedirs(ek_out, exist_ok=True)
            DebExtractor.extract(ellekit_deb, ek_out)
            cs_fw = os.path.join(ek_out, "Library", "Frameworks", "CydiaSubstrate.framework")
            if os.path.isdir(cs_fw):
                tmp_ipa = unsigned_path + ".tmp"
                with zipfile.ZipFile(unsigned_path, "r") as zin:
                    with zipfile.ZipFile(tmp_ipa, "w", zipfile.ZIP_DEFLATED) as zout:
                        for item in zin.infolist():
                            zout.writestr(item, zin.read(item.filename))
                        for root, dirs, files in os.walk(cs_fw):
                            for file in files:
                                lp  = os.path.join(root, file)
                                rel = os.path.relpath(lp, cs_fw).replace("\\", "/")
                                zout.writestr(fw_prefix + "CydiaSubstrate.framework/" + rel,
                                              open(lp, "rb").read())
                os.replace(tmp_ipa, unsigned_path)
                print(f"  {GREEN}+{RESET} Injected CydiaSubstrate.framework")
            else:
                print(f"{RED}[!] CydiaSubstrate.framework not found inside ellekit.deb{RESET}")
        else:
            print(f"{WHITE}[*] CydiaSubstrate.framework not present — ellekit.deb not found, skipping{RESET}")

    out_path = editor.args.o if editor.args.o else editor._get_auto_out_path(
        "detweaked_signed" if do_sign else "detweaked_unsigned"
    )
    if not out_path.endswith(".ipa"):
        out_path += ".ipa"

    zsign_flags = ""
    for t in targets:
        if t.endswith(".framework"):
            fw_bin = t[: -len(".framework")]
            zsign_flags += f' -R "{fw_bin}"'
        else:
            base        = t if t.endswith(".dylib") else t + ".dylib"
            zsign_flags += f' -R "{base}"'

    import subprocess
    print(SEP)
    if do_sign:
        print(f"{WHITE}[*] Detweaking LC & Signing iPA{RESET}")
        p12_path, mb_path = editor._resolve_certificate()
        if not p12_path or not mb_path:
            sys.exit(f"{RED}[-] Certificate or Mobile Provision not provided.{RESET}")
        cert_pw = input("[?] Certificate password: ")
        print(SEP)
        cmd = (
            f'"{zsign}" -k "{p12_path}" -m "{mb_path}" -p "{cert_pw}"'
            f'{zsign_flags} -o "{out_path}" -z 9 "{unsigned_path}"'
        )
        print(f"[+] Using zsign command: {cmd}")
    else:
        print(f"{WHITE}[*] Detweaking LC (Adhoc/Null-sign) iPA{RESET}")
        cmd = f'"{zsign}" -a {zsign_flags} -o "{out_path}" -z 9 "{unsigned_path}"'

    subprocess.run(cmd, shell=True)
    if os.path.isfile(out_path):
        print(f"{GREEN}[+] Detweaked output: {out_path}{RESET}")
    else:
        print(f"{RED}[-] zsign operation failed — output IPA not found{RESET}")


# ---------------------------------------------------------------------------
# Tweak export
# ---------------------------------------------------------------------------

def export_tweaks(editor) -> None:
    """
    Export all tweaks (.dylib / .framework) from the IPA into a local folder.

    Parameters
    ----------
    editor : IPAEditor
        The calling editor instance.
    """
    print(SEP)
    print(f"{WHITE}[*] Export Tweaks from iPA{RESET}")

    source_ipa = editor.ipa_path
    app_folder_name = None

    with zipfile.ZipFile(source_ipa, "r") as zf:
        for entry in zf.namelist():
            parts = entry.replace("\\", "/").split("/")
            if len(parts) >= 2 and parts[0] == "Payload" and parts[1].endswith(".app"):
                app_folder_name = parts[1]
                break

        if not app_folder_name:
            sys.exit(f"{RED}[-] Could not locate .app inside IPA.{RESET}")

        fw_prefix = f"Payload/{app_folder_name}/Frameworks/"
        extracted_dir = os.path.join(editor.script_dir, "tweaks_extracted")
        os.makedirs(extracted_dir, exist_ok=True)

        available_tweaks: list[str] = []
        extracted_count = 0

        print(f"{WHITE}[*] Scanning and exporting from Frameworks/...{RESET}")

        for entry in zf.namelist():
            normalized = entry.replace("\\", "/")
            if normalized.startswith(fw_prefix) and len(normalized) > len(fw_prefix):
                # The file inside the Frameworks folder (could be a framework dir or dylib file)
                rel_path = normalized[len(fw_prefix):]
                top_level_name = rel_path.split("/")[0]

                if top_level_name.endswith(".dylib") or top_level_name.endswith(".framework"):
                    # Extract this file
                    if not normalized.endswith("/"):  # Skip directory entries
                        out_path = os.path.join(extracted_dir, rel_path)
                        os.makedirs(os.path.dirname(out_path), exist_ok=True)
                        with open(out_path, "wb") as f_out:
                            f_out.write(zf.read(entry))
                        
                        if top_level_name not in available_tweaks:
                            available_tweaks.append(top_level_name)
                    extracted_count += 1

        if available_tweaks:
            print(f"{GREEN}[+] Exported tweaks to: {extracted_dir}{RESET}")
            for twk in available_tweaks:
                print(f"  {GREEN}+{RESET} {twk}")
        else:
            print(f"{RED}[-] No tweaks (.dylib or .framework) found to export.{RESET}")

