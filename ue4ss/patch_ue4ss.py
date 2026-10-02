"""Builds the UE4SS files the mod ships, starting from the official UE4SS v3.0.1 release.

    python ue4ss\\patch_ue4ss.py                  downloads the official zip from GitHub
    python ue4ss\\patch_ue4ss.py UE4SS_v3.0.1.zip  uses a zip you already downloaded

Output: launcher\\payload\\UE4SS.dll (patched) and launcher\\payload\\dwmapi.dll (unchanged).

Dead Island 2 runs a customised Unreal Engine 4.25 and stock UE4SS 3.0.1 crashes on it. The patch
changes 20 bytes, nothing is added:

  1. GUObjectArray listener arrays. In this engine build the TArrays that UE4SS registers its
     create/delete listeners in sit at FUObjectArray+0x90 / +0xA0, not +0xE0 / +0xF0. The
     displacements of the 18 instructions that access them are rewritten (E0->90, E8->98,
     F0->A0, F8->A8).
  2. LoadMap hook. Hooking UEngine::LoadMap crashes on this build and the mod doesn't need it:
     the conditional jump that installs the hook is replaced with two NOPs (75 35 -> 90 90).

The original and the patched DLL are checked against their SHA-256, so the result is
byte-identical to the file inside the released installer.
"""
import hashlib
import io
import os
import sys
import urllib.request
import zipfile

URL = "https://github.com/UE4SS-RE/RE-UE4SS/releases/download/v3.0.1/UE4SS_v3.0.1.zip"
ORIGINAL_SHA256 = "8ac18fbffc1ef96b0662d4a2d537b3f224c26d65caaba7989a9404c566102b26"
PATCHED_SHA256 = "e43c8278b0a938d8ea8a5ccbb744ceab6e9e67ab0645972861a463349bba3042"
DWMAPI_SHA256 = "ce596412befa68c30b7f88f65beb77d9bdad55e9b96a276a5a9cf690c63f24bb"

# (file offset, original bytes, patched bytes)
PATCHES = [
    # 1. listener TArray offsets: disp8/disp32 low byte of each access
    (0x5258A2, "e0", "90"), (0x5258A9, "e8", "98"), (0x5258FA, "e0", "90"),
    (0x525DA2, "f0", "a0"), (0x525DA9, "f8", "a8"), (0x525DFA, "f0", "a0"),
    (0x5262B0, "e0", "90"), (0x5262B7, "e8", "98"), (0x526306, "e8", "98"),
    (0x52637D, "e0", "90"), (0x526384, "e8", "98"), (0x5263B5, "e0", "90"),
    (0x5263E0, "f0", "a0"), (0x5263E7, "f8", "a8"), (0x526436, "f8", "a8"),
    (0x5264AD, "f0", "a0"), (0x5264B4, "f8", "a8"), (0x5264E5, "f0", "a0"),
    # 2. skip the LoadMap hook: jne +0x35 -> nop nop
    (0x553332, "7535", "9090"),
]

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "launcher", "payload")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def main():
    if len(sys.argv) > 1:
        with open(sys.argv[1], "rb") as f:
            raw = f.read()
    else:
        print("downloading", URL)
        raw = urllib.request.urlopen(URL).read()
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        dll = bytearray(z.read("UE4SS.dll"))
        dwmapi = z.read("dwmapi.dll")

    if sha256(dll) != ORIGINAL_SHA256:
        sys.exit("UE4SS.dll is not the official v3.0.1 build (SHA-256 mismatch)")
    if sha256(dwmapi) != DWMAPI_SHA256:
        sys.exit("dwmapi.dll is not the official v3.0.1 build (SHA-256 mismatch)")

    for offset, old, new in PATCHES:
        old, new = bytes.fromhex(old), bytes.fromhex(new)
        if dll[offset:offset + len(old)] != old:
            sys.exit(f"unexpected bytes at 0x{offset:X}")
        dll[offset:offset + len(new)] = new

    if sha256(dll) != PATCHED_SHA256:
        sys.exit("patched UE4SS.dll has an unexpected SHA-256")

    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "UE4SS.dll"), "wb") as f:
        f.write(dll)
    with open(os.path.join(OUT, "dwmapi.dll"), "wb") as f:
        f.write(dwmapi)
    print("written", os.path.normpath(OUT), "(UE4SS.dll patched, dwmapi.dll as released)")


if __name__ == "__main__":
    main()
