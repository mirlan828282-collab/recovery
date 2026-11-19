# -*- coding: utf-8 -*-
"""Read-only physical disk and partition inspection for Windows."""
import ctypes
from ctypes import wintypes

GENERIC_READ = 0x80000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
FILE_ATTRIBUTE_NORMAL = 0x00000080
IOCTL_DISK_GET_LENGTH_INFO = 0x0007405C
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class GET_LENGTH_INFORMATION(ctypes.Structure):
    _fields_ = [("Length", ctypes.c_longlong)]


def _open_disk(number):
    path = r"\\.\PhysicalDrive%d" % number
    handle = kernel32.CreateFileW(
        path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE,
        None, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, None)
    if handle == INVALID_HANDLE_VALUE:
        raise ctypes.WinError(ctypes.get_last_error())
    return handle


def _read_at(handle, offset, size):
    kernel32.SetFilePointerEx.argtypes = [
        wintypes.HANDLE, ctypes.c_longlong,
        ctypes.POINTER(ctypes.c_longlong), wintypes.DWORD]
    kernel32.SetFilePointerEx.restype = wintypes.BOOL
    new_pos = ctypes.c_longlong()
    if not kernel32.SetFilePointerEx(handle, offset, ctypes.byref(new_pos), 0):
        raise ctypes.WinError(ctypes.get_last_error())
    buf = ctypes.create_string_buffer(size)
    read = wintypes.DWORD()
    kernel32.ReadFile.argtypes = [
        wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
    kernel32.ReadFile.restype = wintypes.BOOL
    if not kernel32.ReadFile(handle, buf, size, ctypes.byref(read), None):
        raise ctypes.WinError(ctypes.get_last_error())
    return buf.raw[:read.value]


def _disk_size(handle):
    info = GET_LENGTH_INFORMATION()
    returned = wintypes.DWORD()
    ok = kernel32.DeviceIoControl(
        handle, IOCTL_DISK_GET_LENGTH_INFO, None, 0,
        ctypes.byref(info), ctypes.sizeof(info), ctypes.byref(returned), None)
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    return info.Length


def _human_size(size):
    return "%.2f GB" % (size / float(1024 ** 3))


def list_physical_disks():
    disks = []
    for number in range(16):
        try:
            handle = _open_disk(number)
            try:
                size = _disk_size(handle)
                disks.append({"number": number, "size": size, "size_text": _human_size(size)})
            finally:
                kernel32.CloseHandle(handle)
        except OSError:
            continue
    return disks


def _parse_mbr(sector):
    entries = []
    if len(sector) < 512 or sector[510:512] != b"\\x55\\xaa":
        return entries
    for i in range(4):
        entry = sector[446 + i * 16:462 + i * 16]
        ptype = entry[4]
        start = int.from_bytes(entry[8:12], "little")
        count = int.from_bytes(entry[12:16], "little")
        if ptype and count:
            entries.append((ptype, start, count))
    return entries


def scan_disk(number):
    handle = _open_disk(number)
    try:
        size = _disk_size(handle)
        sector0 = _read_at(handle, 0, 512)
        lines = [
            "Размер: %s (%d байт)" % (_human_size(size), size),
            "Режим доступа: только чтение.",
        ]
        if sector0[510:512] == b"\\x55\\xaa":
            lines.append("MBR: сигнатура 55 AA обнаружена.")
            mbr_entries = _parse_mbr(sector0)
            if not mbr_entries:
                lines.append("Основные записи MBR не найдены.")
            for idx, (ptype, start, count) in enumerate(mbr_entries, 1):
                offset = start * 512
                boot = _read_at(handle, offset, 512)
                label = "NTFS" if boot[3:11] == b"NTFS    " else "неизвестная/другая ФС"
                lines.append("Раздел MBR %d: тип 0x%02X, начало LBA %d, размер %d секторов; %s" %
                             (idx, ptype, start, count, label))
        else:
            lines.append("MBR-сигнатура 55 AA не обнаружена.")
        if sector0[3:11] == b"EFI PART":
            lines.append("GPT: заголовок GPT обнаружен в секторе 0 (нестандартное расположение).")
        else:
            try:
                sector1 = _read_at(handle, 512, 512)
                if sector1[0:8] == b"EFI PART":
                    lines.append("GPT: заголовок GPT обнаружен.")
                    entries_lba = int.from_bytes(sector1[72:80], "little")
                    entry_count = int.from_bytes(sector1[80:84], "little")
                    entry_size = int.from_bytes(sector1[84:88], "little")
                    lines.append("GPT: таблица записей LBA %d, записей %d, размер записи %d." %
                                 (entries_lba, entry_count, entry_size))
                    if 0 < entry_count <= 4096 and 128 <= entry_size <= 4096:
                        raw = _read_at(handle, entries_lba * 512,
                                       min(entry_count * entry_size, 1024 * 1024))
                        found = 0
                        for i in range(min(entry_count, len(raw) // entry_size)):
                            ent = raw[i * entry_size:(i + 1) * entry_size]
                            if ent[:16] == b"\\x00" * 16:
                                continue
                            first = int.from_bytes(ent[32:40], "little")
                            last = int.from_bytes(ent[40:48], "little")
                            boot = _read_at(handle, first * 512, 512)
                            label = "NTFS" if boot[3:11] == b"NTFS    " else "неизвестная/другая ФС"
                            found += 1
                            lines.append("Раздел GPT %d: LBA %d–%d; %s" %
                                         (found, first, last, label))
                else:
                    lines.append("GPT: заголовок не обнаружен в секторе 1.")
            except Exception as exc:
                lines.append("Проверка GPT: %s" % exc)
        lines.append("Сигнатуры загрузочных секторов проверены только в текущих разделах.")
        return lines
    finally:
        kernel32.CloseHandle(handle)
