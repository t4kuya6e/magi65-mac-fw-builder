"""IOKit HID 列挙・OtaDevice（macOS / IOKit 直叩き）。
Task 6: mac_ota/ota_flash.py の _load_iokit/OtaDevice を移設し、
外部ライブラリでの列挙(_discover_ota_regid)を IOKit の DeviceUsagePairs 走査へ置換。
ゼロ依存（ctypes のみ、外部 HID ライブラリ不使用）。
"""
import ctypes
import ctypes.util
from ctypes import (c_void_p, c_int, c_uint32, c_uint64, c_long, c_double,
                     c_uint8, c_char_p, byref, POINTER)

from .constants import VID, PID, USAGE_PAGE, REPORT_ID

kIOHIDOptionsTypeNone = 0
kIOHIDReportTypeOutput = 1
kCFNumberSInt32Type = 3
kCFStringEncodingUTF8 = 0x08000100


def _load_iokit():
    cf = ctypes.CDLL(ctypes.util.find_library("CoreFoundation"))
    iokit = ctypes.CDLL(ctypes.util.find_library("IOKit"))

    cf.CFStringCreateWithCString.restype = c_void_p
    cf.CFStringCreateWithCString.argtypes = [c_void_p, c_char_p, c_uint32]
    cf.CFSetGetCount.restype = c_long
    cf.CFSetGetCount.argtypes = [c_void_p]
    cf.CFSetGetValues.argtypes = [c_void_p, c_void_p]
    cf.CFArrayGetCount.restype = c_long
    cf.CFArrayGetCount.argtypes = [c_void_p]
    cf.CFArrayGetValueAtIndex.restype = c_void_p
    cf.CFArrayGetValueAtIndex.argtypes = [c_void_p, c_long]
    cf.CFDictionaryGetValue.restype = c_void_p
    cf.CFDictionaryGetValue.argtypes = [c_void_p, c_void_p]
    cf.CFNumberGetValue.restype = c_int
    cf.CFNumberGetValue.argtypes = [c_void_p, c_int, c_void_p]
    cf.CFStringGetCString.restype = c_int
    cf.CFStringGetCString.argtypes = [c_void_p, c_char_p, c_long, c_uint32]
    cf.CFGetTypeID.restype = c_long
    cf.CFGetTypeID.argtypes = [c_void_p]
    cf.CFStringGetTypeID.restype = c_long
    cf.CFStringGetTypeID.argtypes = []
    cf.CFRunLoopGetCurrent.restype = c_void_p
    cf.CFRunLoopRunInMode.restype = c_int
    cf.CFRunLoopRunInMode.argtypes = [c_void_p, c_double, c_int]
    cf.CFRunLoopStop.argtypes = [c_void_p]

    iokit.IOHIDManagerCreate.restype = c_void_p
    iokit.IOHIDManagerCreate.argtypes = [c_void_p, c_uint32]
    iokit.IOHIDManagerSetDeviceMatching.argtypes = [c_void_p, c_void_p]
    iokit.IOHIDManagerCopyDevices.restype = c_void_p
    iokit.IOHIDManagerCopyDevices.argtypes = [c_void_p]
    iokit.IOHIDDeviceGetProperty.restype = c_void_p
    iokit.IOHIDDeviceGetProperty.argtypes = [c_void_p, c_void_p]
    iokit.IOHIDDeviceOpen.restype = c_int
    iokit.IOHIDDeviceOpen.argtypes = [c_void_p, c_uint32]
    iokit.IOHIDDeviceClose.restype = c_int
    iokit.IOHIDDeviceClose.argtypes = [c_void_p, c_uint32]
    iokit.IOHIDDeviceGetService.restype = c_uint32
    iokit.IOHIDDeviceGetService.argtypes = [c_void_p]
    iokit.IORegistryEntryGetRegistryEntryID.restype = c_int
    iokit.IORegistryEntryGetRegistryEntryID.argtypes = [c_uint32, POINTER(c_uint64)]
    iokit.IOHIDDeviceSetReport.restype = c_int
    iokit.IOHIDDeviceSetReport.argtypes = [c_void_p, c_int, c_long, POINTER(c_uint8), c_long]
    iokit.IOHIDDeviceScheduleWithRunLoop.argtypes = [c_void_p, c_void_p, c_void_p]
    iokit.IOHIDDeviceUnscheduleFromRunLoop.argtypes = [c_void_p, c_void_p, c_void_p]
    iokit.IOHIDDeviceRegisterInputReportCallback.argtypes = [
        c_void_p, POINTER(c_uint8), c_long, c_void_p, c_void_p]
    return cf, iokit


def _cfstr(cf, s):
    return cf.CFStringCreateWithCString(None, s.encode(), kCFStringEncodingUTF8)


def _int_prop(cf, iokit, dev, key):
    ref = iokit.IOHIDDeviceGetProperty(dev, _cfstr(cf, key))
    if not ref:
        return None
    out = c_int(0)
    if cf.CFNumberGetValue(ref, kCFNumberSInt32Type, byref(out)):
        return out.value & 0xFFFFFFFF
    return None


def _str_prop(cf, iokit, dev, key):
    ref = iokit.IOHIDDeviceGetProperty(dev, _cfstr(cf, key))
    if not ref or cf.CFGetTypeID(ref) != cf.CFStringGetTypeID():
        return None
    buf = ctypes.create_string_buffer(256)
    if cf.CFStringGetCString(ref, buf, 256, kCFStringEncodingUTF8):
        return buf.value.decode(errors="replace")
    return None


def _registry_id(iokit, dev):
    svc = iokit.IOHIDDeviceGetService(dev)
    if not svc:
        return None
    out = c_uint64(0)
    if iokit.IORegistryEntryGetRegistryEntryID(svc, byref(out)) == 0:
        return out.value
    return None


def _usage_pages(cf, iokit, dev):
    """DeviceUsagePairs（CFArray of CFDictionary、キー DeviceUsagePage）の集合を返す。"""
    ref = iokit.IOHIDDeviceGetProperty(dev, _cfstr(cf, "DeviceUsagePairs"))
    if not ref:
        return set()
    pages = set()
    n = cf.CFArrayGetCount(ref)
    for i in range(n):
        item = cf.CFArrayGetValueAtIndex(ref, i)
        if not item:
            continue
        page_ref = cf.CFDictionaryGetValue(item, _cfstr(cf, "DeviceUsagePage"))
        if not page_ref:
            continue
        out = c_int(0)
        if cf.CFNumberGetValue(page_ref, kCFNumberSInt32Type, byref(out)):
            pages.add(out.value & 0xFFFFFFFF)
    return pages


def find_ota_devices(usage_page=USAGE_PAGE):
    """VID/PID 一致かつ DeviceUsagePairs に usage_page を含む IOHIDDevice を列挙する。

    RegID(IORegistryEntryGetRegistryEntryID) で重複排除し、
    [{"dev": IOHIDDeviceRef, "regid": int, "location": int|None, "serial": str|None}, ...]
    を返す。0件/複数件の判定は呼び出し側（CLI）が行う。
    """
    cf, iokit = _load_iokit()
    mgr = iokit.IOHIDManagerCreate(None, 0)
    iokit.IOHIDManagerSetDeviceMatching(mgr, None)
    devset = iokit.IOHIDManagerCopyDevices(mgr)
    # 注意: ここで mgr / devset を CFRelease しないのは意図的。
    # devset(CFSet) が各 IOHIDDevice を暗黙 retain しており、
    # それが返した dev ハンドルの生存を保証している。
    # リーク対策で CFRelease を足す場合は、返す各 dev に必ず CFRetain し、
    # OtaDevice.close() に対応する CFRelease を追加すること
    # （さもないと open 時に解放済み参照で UAF になる）。
    if not devset:
        return []
    n = cf.CFSetGetCount(devset)
    arr = (c_void_p * n)()
    cf.CFSetGetValues(devset, arr)
    seen_regids = set()
    result = []
    for i in range(n):
        d = arr[i]
        if _int_prop(cf, iokit, d, "VendorID") != VID:
            continue
        if _int_prop(cf, iokit, d, "ProductID") != PID:
            continue
        if usage_page not in _usage_pages(cf, iokit, d):
            continue
        regid = _registry_id(iokit, d)
        if regid is None or regid in seen_regids:
            continue
        seen_regids.add(regid)
        result.append({
            "dev": d,
            "regid": regid,
            "location": _int_prop(cf, iokit, d, "LocationID"),
            "serial": _str_prop(cf, iokit, d, "SerialNumber"),
        })
    return result


class OtaDevice:
    """与えられた IOHIDDevice を open(None) し、report_id=REPORT_ID の送受信を行う。"""

    def __init__(self, dev, timeout=2.0):
        self.cf, self.iokit = _load_iokit()
        self.dev = dev
        self.timeout = timeout
        self._last = None
        self._cb = None
        self.max_output_report = None
        self.max_input_report = None
        self._mode = ctypes.c_void_p.in_dll(self.cf, "kCFRunLoopDefaultMode")

    def open(self):
        r = self.iokit.IOHIDDeviceOpen(self.dev, kIOHIDOptionsTypeNone) & 0xFFFFFFFF
        if r != 0:
            raise RuntimeError(f"open(None) 失敗 0x{r:08X}"
                                + (" (0xE00002E2=入力監視権限が必要)" if r == 0xE00002E2 else ""))
        self.max_output_report = _int_prop(self.cf, self.iokit, self.dev, "MaxOutputReportSize")
        self.max_input_report = _int_prop(self.cf, self.iokit, self.dev, "MaxInputReportSize")
        self._in_buf = (c_uint8 * 64)()
        REPORT_CB = ctypes.CFUNCTYPE(
            None, c_void_p, c_int, c_void_p, c_int,
            c_uint32, POINTER(c_uint8), c_long)

        def _on_report(context, result, sender, rtype, rid, report, rlen):
            data = bytes(report[i] for i in range(rlen))
            # keyboard 同居インターフェースのため report_id!=REPORT_ID の入力レポートが
            # 届きうる。OTA 応答以外は無視して待機を継続する（RunLoop は止めない）。
            if rid != REPORT_ID and not (rlen >= 1 and report[0] == REPORT_ID):
                return
            self._last = (rid, data)
            self.cf.CFRunLoopStop(self.cf.CFRunLoopGetCurrent())

        self._cb = REPORT_CB(_on_report)
        self.iokit.IOHIDDeviceRegisterInputReportCallback(
            self.dev, self._in_buf, 64, self._cb, None)
        self.iokit.IOHIDDeviceScheduleWithRunLoop(
            self.dev, self.cf.CFRunLoopGetCurrent(), self._mode)

    def send_and_wait(self, report: bytes):
        """レポート送信→入力レポート1つを待つ。戻り値 (report_id, data) or None。"""
        self._last = None
        buf = (c_uint8 * len(report))(*report)
        sr = self.iokit.IOHIDDeviceSetReport(
            self.dev, kIOHIDReportTypeOutput, REPORT_ID, buf, len(report)) & 0xFFFFFFFF
        if sr != 0:
            raise RuntimeError(f"SetReport 失敗 0x{sr:08X}")
        self.cf.CFRunLoopRunInMode(self._mode, c_double(self.timeout), False)
        return self._last

    def vendor_id(self):
        """接続中デバイスの実 VendorID（プロパティ未提供時は None）。"""
        return _int_prop(self.cf, self.iokit, self.dev, "VendorID")

    def product_id(self):
        """接続中デバイスの実 ProductID（プロパティ未提供時は None）。"""
        return _int_prop(self.cf, self.iokit, self.dev, "ProductID")

    def close(self):
        if self.dev:
            # runloop から外してからクローズ。残留コールバックが後続 send_and_wait 中に
            # 発火して誤 ACK になるのを防ぐ。
            self.iokit.IOHIDDeviceUnscheduleFromRunLoop(
                self.dev, self.cf.CFRunLoopGetCurrent(), self._mode)
            self.iokit.IOHIDDeviceClose(self.dev, kIOHIDOptionsTypeNone)
            self.dev = None
            self._cb = None
