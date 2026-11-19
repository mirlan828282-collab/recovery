# -*- coding: utf-8 -*-
"""Ограниченное восстановление удалённых файлов NTFS по сохранившимся записям MFT.

Все операции с исходным физическим диском выполняются только через ReadFile.
Поддерживается чтение простых NTFS data runs; фрагментированные/повреждённые
метаданные могут ограничить результат. Это не замена посекторному образу диска.
"""
import ctypes
import os
import struct
from ctypes import wintypes

GENERIC_READ = 0x80000000
FILE_SHARE_READ = 1
FILE_SHARE_WRITE = 2
OPEN_EXISTING = 3
FILE_ATTRIBUTE_NORMAL = 0x80
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
CHUNK = 8 * 1024 * 1024
MFT_LIMIT = 128 * 1024 * 1024

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                            wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
k32.CreateFileW.restype = wintypes.HANDLE
k32.CloseHandle.argtypes = [wintypes.HANDLE]
k32.CloseHandle.restype = wintypes.BOOL
k32.SetFilePointerEx.argtypes = [wintypes.HANDLE, ctypes.c_longlong,
                                 ctypes.POINTER(ctypes.c_longlong), wintypes.DWORD]
k32.SetFilePointerEx.restype = wintypes.BOOL
k32.ReadFile.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                         ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
k32.ReadFile.restype = wintypes.BOOL


def _open(number):
    h = k32.CreateFileW(r"\\.\PhysicalDrive%d" % number, GENERIC_READ,
                        FILE_SHARE_READ | FILE_SHARE_WRITE, None,
                        OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, None)
    if h == INVALID_HANDLE_VALUE or not h:
        raise ctypes.WinError(ctypes.get_last_error())
    return h


def _read(h, offset, size):
    pos = ctypes.c_longlong()
    if not k32.SetFilePointerEx(h, offset, ctypes.byref(pos), 0):
        raise ctypes.WinError(ctypes.get_last_error())
    buf = ctypes.create_string_buffer(size)
    got = wintypes.DWORD()
    if not k32.ReadFile(h, buf, size, ctypes.byref(got), None):
        raise ctypes.WinError(ctypes.get_last_error())
    return buf.raw[:got.value]


def _valid_boot(b):
    if len(b) < 512 or b[3:11] != b"NTFS    ":
        return None
    bps = struct.unpack_from("<H", b, 11)[0]
    spc = b[13]
    total = struct.unpack_from("<Q", b, 40)[0]
    mft_lcn = struct.unpack_from("<Q", b, 48)[0]
    rec_code = struct.unpack_from("<b", b, 64)[0]
    if bps not in (512, 1024, 2048, 4096) or not spc or spc > 128:
        return None
    if total < 2048 or mft_lcn >= total:
        return None
    cluster = bps * spc
    rec_size = (1 << -rec_code) if rec_code < 0 else rec_code * cluster
    if rec_size < 512 or rec_size > 65536:
        return None
    return {"bps": bps, "spc": spc, "cluster": cluster, "total": total,
            "mft_lcn": mft_lcn, "record_size": rec_size}


def find_ntfs_volumes(disk_number, progress=None):
    """Ищет NTFS boot sectors по всему физическому диску. Читает без записи."""
    h = _open(disk_number)
    found = []
    try:
        first = _read(h, 0, 512)
        # Получаем размер через IOCTL_DISK_GET_LENGTH_INFO.
        class LI(ctypes.Structure):
            _fields_ = [("Length", ctypes.c_longlong)]
        ioctl = 0x0007405C
        k32.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID,
            wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
        k32.DeviceIoControl.restype = wintypes.BOOL
        li, ret = LI(), wintypes.DWORD()
        if not k32.DeviceIoControl(h, ioctl, None, 0, ctypes.byref(li),
                                   ctypes.sizeof(li), ctypes.byref(ret), None):
            raise ctypes.WinError(ctypes.get_last_error())
        total_bytes = li.Length
        offset = 0
        overlap = b""
        seen = set()
        while offset < total_bytes:
            block = _read(h, offset, min(CHUNK, total_bytes - offset))
            data = overlap + block
            base = offset - len(overlap)
            at = 0
            while True:
                idx = data.find(b"NTFS    ", at)
                if idx < 0:
                    break
                boot_offset = base + idx - 3
                at = idx + 8
                if boot_offset < 0 or boot_offset % 512 or boot_offset in seen:
                    continue
                sector = _read(h, boot_offset, 512)
                info = _valid_boot(sector)
                if info:
                    seen.add(boot_offset)
                    info["offset"] = boot_offset
                    found.append(info)
            offset += len(block)
            overlap = data[-32:]
            if progress:
                progress(min(100, int(offset * 100 / max(1, total_bytes))))
        return found
    finally:
        k32.CloseHandle(h)


def _fixup(record, bps):
    if len(record) < bps or record[:4] != b"FILE":
        return None
    usa_off, usa_count = struct.unpack_from("<HH", record, 4)
    if usa_count < 2 or usa_off + usa_count * 2 > len(record):
        return None
    seq = record[usa_off:usa_off + 2]
    out = bytearray(record)
    for i in range(1, usa_count):
        end = i * bps
        if end > len(out) or out[end - 2:end] != seq:
            return None
        out[end - 2:end] = record[usa_off + i * 2:usa_off + i * 2 + 2]
    return bytes(out)


def _parse_runs(raw, cluster_size):
    runs, pos, current_lcn = [], 0, 0
    while pos < len(raw) and raw[pos]:
        head = raw[pos]
        pos += 1
        len_bytes, off_bytes = head & 15, head >> 4
        if not len_bytes or pos + len_bytes + off_bytes > len(raw):
            break
        run_len = int.from_bytes(raw[pos:pos + len_bytes], "little")
        pos += len_bytes
        if off_bytes:
            delta = int.from_bytes(raw[pos:pos + off_bytes], "little", signed=True)
            current_lcn += delta
            pos += off_bytes
            runs.append((current_lcn * cluster_size, run_len * cluster_size))
        else:
            runs.append((None, run_len * cluster_size))
    return runs


def _attributes(rec, cluster_size):
    first = struct.unpack_from("<H", rec, 20)[0]
    pos, names, data = first, [], None
    while pos + 8 <= len(rec):
        typ, length = struct.unpack_from("<II", rec, pos)
        if typ == 0xFFFFFFFF or length < 8 or pos + length > len(rec):
            break
        nonresident = rec[pos + 8]
        if typ == 0x30 and not nonresident and length >= 24:
            value_len, value_off = struct.unpack_from("<IH", rec, pos + 16)
            val = rec[pos + value_off:pos + value_off + value_len]
            if len(val) >= 66:
                parent = struct.unpack_from("<Q", val, 0)[0] & 0x0000FFFFFFFFFFFF
                nlen, nspace = val[64], val[65]
                name = val[66:66 + nlen * 2].decode("utf-16le", "replace")
                if name and nspace != 2:
                    names.append((parent, name))
        elif typ == 0x80 and not nonresident and data is None:
            value_len, value_off = struct.unpack_from("<IH", rec, pos + 16)
            data = {"resident": rec[pos + value_off:pos + value_off + value_len],
                    "size": value_len, "runs": None}
        elif typ == 0x80 and nonresident and data is None and length >= 64:
            run_off = struct.unpack_from("<H", rec, pos + 32)[0]
            real_size = struct.unpack_from("<Q", rec, pos + 48)[0]
            runs = _parse_runs(rec[pos + run_off:pos + length], cluster_size)
            data = {"resident": None, "size": real_size, "runs": runs}
        pos += length
    return names, data


def _read_stream(h, runs, size):
    out = bytearray()
    for offset, length in runs:
        if len(out) >= size:
            break
        take = min(length, size - len(out))
        if offset is None:
            out.extend(b"\x00" * take)
        else:
            chunk = _read(h, offset, take)
            out.extend(chunk)
            if len(chunk) != take:
                break
    return bytes(out[:size])


def scan_deleted_files(disk_number, volume, progress=None):
    """Читает первые 128 MiB MFT и возвращает найденные удалённые файловые записи."""
    h = _open(disk_number)
    try:
        rs = volume["record_size"]
        mft_start = volume["offset"] + volume["mft_lcn"] * volume["cluster"]
        max_records = MFT_LIMIT // rs
        records, entries = {}, []
        for i in range(max_records):
            raw = _read(h, mft_start + i * rs, rs)
            if len(raw) != rs or raw[:4] != b"FILE":
                if i > 32:
                    break
                continue
            rec = _fixup(raw, volume["bps"])
            if not rec:
                continue
            flags = struct.unpack_from("<H", rec, 22)[0]
            names, data = _attributes(rec, volume["cluster"])
            if not names:
                continue
            parent, name = names[0]
            if name in (".", ".."):
                continue
            item = {"record": i, "parent": parent, "name": name,
                    "size": data["size"] if data else 0, "data": data,
                    "directory": bool(flags & 2), "in_use": bool(flags & 1)}
            # Keep live directory records too: they are needed to rebuild paths.
            records[i] = item
            if (not item["in_use"] and not item["directory"] and data and
                    data["size"] <= 2 * 1024 * 1024 * 1024):
                entries.append(item)
            if progress and i % 128 == 0:
                progress(min(99, int(i * 100 / max_records)))
        # Resolve old parent references where corresponding MFT records survived.
        for item in entries:
            parts, parent, seen = [item["name"]], item["parent"], set()
            while parent not in (5, 0) and parent in records and parent not in seen:
                seen.add(parent)
                p = records[parent]
                parts.append(p["name"])
                parent = p["parent"]
            item["path"] = "\\".join(reversed(parts))
        return entries
    finally:
        k32.CloseHandle(h)


def recover_file(disk_number, volume, item, destination):
    """Извлекает один найденный файл в указанный каталог назначения."""
    if item.get("directory"):
        raise ValueError("Каталог как отдельный файл не восстанавливается.")
    os.makedirs(destination, exist_ok=True)
    rel = item.get("path") or item["name"]
    rel = rel.replace("/", "\\").replace(":", "_")
    parts = [p for p in rel.split("\\") if p not in ("", ".", "..")]
    if not parts:
        parts = ["recovered_%d.bin" % item["record"]]
    target = os.path.join(destination, *parts)
    parent = os.path.dirname(target)
    os.makedirs(parent, exist_ok=True)
    h = _open(disk_number)
    try:
        d = item["data"]
        payload = d["resident"] if d["resident"] is not None else _read_stream(h, d["runs"], d["size"])
    finally:
        k32.CloseHandle(h)
    if len(payload) != item["size"]:
        raise IOError("Файл прочитан не полностью; сохранение отменено.")
    # Avoid overwriting files with identical names.
    base, ext = os.path.splitext(target)
    candidate, n = target, 1
    while os.path.exists(candidate):
        candidate = "%s_recovered_%d%s" % (base, n, ext)
        n += 1
    with open(candidate, "wb") as f:
        f.write(payload)
    return candidate


def destination_disk_numbers(folder):
    """Определяет физические номера дисков, на которых расположен путь Windows."""
    drive, _ = os.path.splitdrive(os.path.abspath(folder))
    if not drive:
        raise ValueError("Не удалось определить локальный диск папки назначения.")
    path = r"\\.\%s" % drive
    h = k32.CreateFileW(path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE,
                        None, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, None)
    if h == INVALID_HANDLE_VALUE or not h:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        # VOLUME_DISK_EXTENTS: DWORD count + first DISK_EXTENT (DWORD + 2 * LARGE_INTEGER).
        class EXTENT(ctypes.Structure):
            _fields_ = [("DiskNumber", wintypes.DWORD),
                        ("StartingOffset", ctypes.c_longlong),
                        ("ExtentLength", ctypes.c_longlong)]
        buf = ctypes.create_string_buffer(8 + ctypes.sizeof(EXTENT) * 32)
        returned = wintypes.DWORD()
        ok = k32.DeviceIoControl(h, 0x00560000, None, 0, buf, len(buf),
                                 ctypes.byref(returned), None)
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())
        count = struct.unpack_from("<I", buf.raw, 0)[0]
        if count < 1 or count > 32:
            raise ValueError("Не удалось определить физический диск назначения.")
        return set(struct.unpack_from("<I", buf.raw, 8 + i * ctypes.sizeof(EXTENT))[0]
                   for i in range(count))
    finally:
        k32.CloseHandle(h)


def ensure_destination_is_other_disk(source_disk_number, folder):
    disks = destination_disk_numbers(folder)
    if source_disk_number in disks:
        raise ValueError("Папка назначения находится на том же физическом диске, "
                         "с которого выполняется восстановление. Выберите другой диск.")
    return True
