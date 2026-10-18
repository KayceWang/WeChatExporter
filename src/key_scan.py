"""Read-only scanner for the logged-in Weixin process's WCDB key config."""

from __future__ import annotations

import ctypes
import hashlib
import hmac
import re
import struct
from ctypes import wintypes


if __name__ == "__main__" and __package__ is None:
    raise SystemExit("Run the desktop app instead of this module.")
if not hasattr(ctypes, "WinDLL"):
    raise RuntimeError("This feature requires Windows.")

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
ACCESS = PROCESS_QUERY_INFORMATION | PROCESS_VM_READ
MEM_COMMIT = 0x1000
PAGE_GUARD = 0x100
READABLE_PROTECT = (0x02, 0x04, 0x20, 0x40)
MAX_USER_ADDRESS = 0x7FFFFFFFFFFF
CHUNK = 1 << 16
OVERLAP = 128
CONFIG_NAME = b"com.Tencent.WCDB.Config.Cipher"
CONFIG_MASK = bytes.fromhex(
    "d2c7442458020000004889442450488b450048844c2448488944254048584c24"
)
CONFIG_BLOB_MAX = 1024
NODE_OFF_DATA = 0x10
NODE_OFF_LEN = 0x18
NODE_OFF_CONFIG = 0x28
NODE_HEADER_BACKSTEP = 0x10
NODE_READ_SIZE = 0x50
CONFIG_OBJ_OFFSET = 0x88
OBJ_OFF_DATA = 0x08
OBJ_OFF_LEN = 0x10
WECHAT_NAMES = ("weixin.exe", "wechat.exe")
LITERAL_RE = re.compile(rb"[xX]'([0-9a-fA-F]{64,192})'")

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
HANDLE = wintypes.HANDLE
SIZE_T = ctypes.c_size_t
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = HANDLE
kernel32.CloseHandle.argtypes = [HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.ReadProcessMemory.argtypes = [
    HANDLE, ctypes.c_void_p, ctypes.c_void_p, SIZE_T, ctypes.POINTER(SIZE_T)
]
kernel32.ReadProcessMemory.restype = wintypes.BOOL


class _MemoryBasicInformation(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", wintypes.DWORD),
        ("PartitionId", wintypes.WORD),
        ("RegionSize", SIZE_T),
        ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("_pad", wintypes.DWORD),
    ]


class _ProcessEntry32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_void_p),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


kernel32.VirtualQueryEx.argtypes = [
    HANDLE, ctypes.c_void_p, ctypes.POINTER(_MemoryBasicInformation), SIZE_T
]
kernel32.VirtualQueryEx.restype = SIZE_T
kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
kernel32.CreateToolhelp32Snapshot.restype = HANDLE
kernel32.Process32FirstW.argtypes = [HANDLE, ctypes.POINTER(_ProcessEntry32)]
kernel32.Process32FirstW.restype = wintypes.BOOL
kernel32.Process32NextW.argtypes = [HANDLE, ctypes.POINTER(_ProcessEntry32)]
kernel32.Process32NextW.restype = wintypes.BOOL

_INVALID_HANDLE = ctypes.c_void_p(-1).value


def _u64(data: bytes, offset: int) -> int:
    return struct.unpack_from("<Q", data, offset)[0]


def _read_mem(handle: HANDLE, address: int, size: int) -> bytes | None:
    buf = ctypes.create_string_buffer(size)
    got = SIZE_T()
    if not kernel32.ReadProcessMemory(
        handle, ctypes.c_void_p(address), buf, size, ctypes.byref(got)
    ):
        return None
    return buf.raw[: got.value] if got.value else None


def _processes() -> list[dict]:
    snapshot = kernel32.CreateToolhelp32Snapshot(0x2, 0)
    if snapshot == _INVALID_HANDLE:
        return []
    found = []
    try:
        entry = _ProcessEntry32()
        entry.dwSize = ctypes.sizeof(entry)
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            name = entry.szExeFile.lower()
            if name in WECHAT_NAMES:
                found.append({"pid": entry.th32ProcessID, "name": name})
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return found


def _regions(handle: HANDLE) -> list[tuple[int, int]]:
    out = []
    address = 0
    mbi = _MemoryBasicInformation()
    while address < MAX_USER_ADDRESS:
        if not kernel32.VirtualQueryEx(
            handle, ctypes.c_void_p(address), ctypes.byref(mbi), ctypes.sizeof(mbi)
        ):
            break
        base = mbi.BaseAddress or 0
        size = mbi.RegionSize or 0
        if (
            mbi.State == MEM_COMMIT
            and mbi.Protect in READABLE_PROTECT
            and not (mbi.Protect & PAGE_GUARD)
        ):
            out.append((base, size))
        address = base + size if size else address + 0x1000
    return out


def _chunks(handle: HANDLE, regions: list[tuple[int, int]], overlap: int):
    for base, size in regions:
        offset = 0
        while offset < size:
            take = min(CHUNK, size - offset)
            data = _read_mem(handle, base + offset, take)
            if data:
                yield base + offset, data
            if take <= overlap:
                break
            offset += take - overlap


def _candidate_keys(blob: bytes):
    if not blob or len(blob) > CONFIG_BLOB_MAX:
        return
    decoded = bytes(value ^ CONFIG_MASK[i % len(CONFIG_MASK)]
                    for i, value in enumerate(blob))
    seen = set()
    for match in LITERAL_RE.finditer(decoded):
        run = match.group(1).decode("ascii", "ignore").lower()
        starts = [0]
        if len(run) > 96:
            starts.extend(range(0, len(run) - 63, 32))
            starts.append(len(run) - 64)
        for start in starts:
            key = run[start:start + 64]
            if len(key) != 64 or key in seen:
                continue
            seen.add(key)
            salt = run[start + 64:start + 96]
            yield key, salt if len(salt) == 32 else None


def _scan_pid(handle: HANDLE, pid: int, status):
    regions = _regions(handle)
    if not regions:
        return {}
    needles = set()
    for base, data in _chunks(handle, regions, len(CONFIG_NAME) - 1):
        pos = data.find(CONFIG_NAME)
        while pos >= 0:
            needles.add(base + pos)
            pos = data.find(CONFIG_NAME, pos + 1)
    status(f"进程 {pid}：找到配置标记 {len(needles)} 处")
    if not needles:
        return {}

    patterns = [struct.pack("<QQ", address, len(CONFIG_NAME)) for address in needles]
    config_ptrs = []
    for base, data in _chunks(handle, regions, OVERLAP):
        for pattern in patterns:
            pos = data.find(pattern)
            while pos >= 0:
                node = _read_mem(handle, base + pos - NODE_HEADER_BACKSTEP, NODE_READ_SIZE)
                if node and len(node) >= NODE_OFF_CONFIG + 8:
                    if (
                        _u64(node, NODE_OFF_DATA) in needles
                        and _u64(node, NODE_OFF_LEN) == len(CONFIG_NAME)
                    ):
                        config_ptrs.append(_u64(node, NODE_OFF_CONFIG))
                pos = data.find(pattern, pos + 1)

    keys = {}
    seen_blobs = set()
    for config_ptr in config_ptrs:
        obj = _read_mem(handle, config_ptr + CONFIG_OBJ_OFFSET, 0x28)
        if not obj or len(obj) < OBJ_OFF_LEN + 8:
            continue
        data_ptr, data_len = _u64(obj, OBJ_OFF_DATA), _u64(obj, OBJ_OFF_LEN)
        if not (0 < data_len <= CONFIG_BLOB_MAX) or data_ptr in seen_blobs:
            continue
        seen_blobs.add(data_ptr)
        blob = _read_mem(handle, data_ptr, data_len)
        if blob:
            keys.update(_candidate_keys(blob))
    return keys


def extract_candidates(status=lambda _message: None) -> dict[str, str | None]:
    processes = _processes()
    if not processes:
        raise RuntimeError("未检测到微信进程；请打开并登录微信后重试。")
    candidates = {}
    access_errors = 0
    for process in processes:
        handle = kernel32.OpenProcess(ACCESS, False, process["pid"])
        if not handle:
            access_errors += 1
            continue
        try:
            found = _scan_pid(handle, process["pid"], status)
            candidates.update({key: candidates.get(key, salt) for key, salt in found.items()})
        finally:
            kernel32.CloseHandle(handle)
        if candidates:
            break
    if not candidates:
        if access_errors == len(processes):
            raise RuntimeError("无法只读访问微信进程；请在相同 Windows 用户下运行。")
        raise RuntimeError("当前微信版本未匹配到密钥配置；确认已登录后重试。")
    return candidates


def verify_key(key: bytes, page1: bytes) -> bool:
    if len(key) != 32 or len(page1) < 4096:
        return False
    salt = page1[:16]
    mac_salt = bytes(value ^ 0x3A for value in salt)
    mac_key = hashlib.pbkdf2_hmac("sha512", key, mac_salt, 2, dklen=32)
    tag = hmac.new(
        mac_key, page1[16:4096 - 64] + struct.pack("<I", 1), hashlib.sha512
    ).digest()
    return hmac.compare_digest(tag, page1[4096 - 64:4096])
