"""Windows Core Audio — lê o pico de áudio do endpoint de saída padrão.

Usa IAudioMeterInformation::GetPeakValue() via ctypes/COM.
Sem dependências externas, sem subprocess, sem delay.
"""

import ctypes
import ctypes.wintypes as wt
import math
import sys

_AVAILABLE = sys.platform == "win32"

if _AVAILABLE:
    _VoidP  = ctypes.c_void_p
    _VoidPP = ctypes.POINTER(ctypes.c_void_p)
    _FloatP = ctypes.POINTER(ctypes.c_float)

    class _GUID(ctypes.Structure):
        _fields_ = [("d", ctypes.c_byte * 16)]

    def _g(s: str) -> "_GUID":
        import uuid
        b = uuid.UUID(s).bytes_le
        g = _GUID()
        ctypes.memmove(g.d, (ctypes.c_byte * 16)(*b), 16)
        return g

    _CLSID_MMDE = _g("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
    _IID_MMDE   = _g("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
    _IID_IAMI   = _g("{C02216F6-8C67-4B5B-9D00-D008E73E0064}")

    _ole32 = ctypes.windll.ole32
    _ole32.CoInitializeEx.argtypes  = [ctypes.c_void_p, ctypes.c_uint]
    _ole32.CoInitializeEx.restype   = ctypes.HRESULT
    _ole32.CoCreateInstance.argtypes = [
        ctypes.POINTER(_GUID), ctypes.c_void_p, ctypes.c_uint,
        ctypes.POINTER(_GUID), _VoidPP,
    ]
    _ole32.CoCreateInstance.restype = ctypes.HRESULT

    def _vtbl_fn(obj, slot, restype, *argtypes):
        table = ctypes.cast(ctypes.cast(obj, _VoidPP)[0], _VoidPP)
        proto = ctypes.WINFUNCTYPE(restype, _VoidP, *argtypes)
        return proto(table[slot])

    _enumerator = None
    _meter_obj  = None
    _GetPeak    = None   # função COM em cache para evitar recriação a 12 Hz

    def _init() -> bool:
        global _enumerator
        if _enumerator is not None:
            return True
        p = _VoidP()
        hr = _ole32.CoCreateInstance(
            ctypes.byref(_CLSID_MMDE), None, 1,
            ctypes.byref(_IID_MMDE), ctypes.byref(p)
        )
        if hr == 0:
            _enumerator = p
        return hr == 0

    def _get_meter():
        global _meter_obj
        if _meter_obj is not None:
            return _meter_obj
        if not _init():
            return None
        # IMMDeviceEnumerator vtable[4] = GetDefaultAudioEndpoint(flow, role, ppDevice)
        GetDef = _vtbl_fn(_enumerator, 4, ctypes.HRESULT,
                          ctypes.c_uint, ctypes.c_uint, _VoidPP)
        device = _VoidP()
        if GetDef(_enumerator, 0, 0, ctypes.byref(device)) != 0:  # eRender, eConsole
            return None
        # IMMDevice vtable[3] = Activate(riid, clsctx, params, ppInterface)
        Activate = _vtbl_fn(device, 3, ctypes.HRESULT,
                            ctypes.POINTER(_GUID), ctypes.c_uint,
                            ctypes.c_void_p, _VoidPP)
        meter = _VoidP()
        hr = Activate(device, ctypes.byref(_IID_IAMI), 1, None, ctypes.byref(meter))
        if hr == 0:
            _meter_obj = meter
        return _meter_obj if hr == 0 else None

    def get_peak_db() -> "float | None":
        """Retorna o pico atual da saída de áudio padrão em dBFS, ou None."""
        global _meter_obj, _enumerator, _GetPeak
        try:
            # CoInitializeEx é no-op se já chamado nesta thread; garante thread safety
            _ole32.CoInitializeEx(None, 0)
            m = _get_meter()
            if m is None:
                return None
            # IAudioMeterInformation vtable[3] = GetPeakValue(pfPeak)
            if _GetPeak is None:
                _GetPeak = _vtbl_fn(m, 3, ctypes.HRESULT, _FloatP)
            peak = ctypes.c_float(0.0)
            if _GetPeak(m, ctypes.byref(peak)) != 0:
                return None
            v = max(float(peak.value), 1e-10)
            return 20.0 * math.log10(v)
        except Exception:
            _meter_obj = None
            _enumerator = None
            _GetPeak = None
            return None

else:
    def get_peak_db() -> "float | None":
        return None
