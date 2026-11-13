"""Verify the shipped runtime/GUI and use Windows itself to decode every ICO frame."""
import ctypes
from ctypes import wintypes as W
import json,os
from pathlib import Path
import sys,time
package=Path(sys.argv[1]);base=Path(sys.argv[2]);base.mkdir(parents=True,exist_ok=True)
runtime=package/'runtime'
os.environ['TCL_LIBRARY']=str(runtime/'tcl/tcl9.0');os.environ['TK_LIBRARY']=str(runtime/'tcl/tk9.0')
from journey_icon_studio.core import Library,SIZES
from journey_icon_studio.gui import Studio
import tkinter as tk
from tkinter import font

class ICONINFO(ctypes.Structure):
    _fields_=[('fIcon',W.BOOL),('xHotspot',W.DWORD),('yHotspot',W.DWORD),('hbmMask',W.HBITMAP),('hbmColor',W.HBITMAP)]
class BITMAP(ctypes.Structure):
    _fields_=[('bmType',W.LONG),('bmWidth',W.LONG),('bmHeight',W.LONG),('bmWidthBytes',W.LONG),('bmPlanes',W.WORD),('bmBitsPixel',W.WORD),('bmBits',W.LPVOID)]
user,gdi=ctypes.windll.user32,ctypes.windll.gdi32
user.LoadImageW.argtypes=[W.HINSTANCE,W.LPCWSTR,W.UINT,ctypes.c_int,ctypes.c_int,W.UINT];user.LoadImageW.restype=W.HANDLE
user.GetIconInfo.argtypes=[W.HANDLE,ctypes.POINTER(ICONINFO)];user.GetIconInfo.restype=W.BOOL
user.DestroyIcon.argtypes=[W.HANDLE];gdi.GetObjectW.argtypes=[W.HANDLE,ctypes.c_int,W.LPVOID];gdi.DeleteObject.argtypes=[W.HANDLE]

def native_decode(path):
    result=[]
    for size in SIZES:
        handle=user.LoadImageW(None,str(path),1,size,size,0x10)
        assert handle,('Windows LoadImageW rejected the exported ICO',size,ctypes.get_last_error())
        info=ICONINFO()
        try:
            assert user.GetIconInfo(handle,ctypes.byref(info))
            bitmap=BITMAP();assert gdi.GetObjectW(info.hbmColor,ctypes.sizeof(bitmap),ctypes.byref(bitmap))
            assert (bitmap.bmWidth,bitmap.bmHeight)==(size,size),(size,bitmap.bmWidth,bitmap.bmHeight)
            assert bitmap.bmBitsPixel==32
            result.append({'size':size,'windows_decoded':True,'bits':bitmap.bmBitsPixel})
        finally:
            if info.hbmColor:gdi.DeleteObject(info.hbmColor)
            if info.hbmMask:gdi.DeleteObject(info.hbmMask)
            user.DestroyIcon(handle)
    return result

library=Library(base,package/'inkscape/bin/inkscape.exe')
folder=library.new('Jade clover folder','Folder');second=library.variation(folder,'Cobalt star folder',body='#355eb4',accent='#d3eaff',glyph='Star',texture='Lines',lighting='Soft gloss',border=2,opacity=1)
drive=library.new('Independent copper drive','Drive');drive=library.variation(drive,'Copper drive',body='#c66a35',accent='#ffe6b1',glyph='Hexagon');library.assign(drive,'C:')
reports=[]
for project in (folder,second,drive):
    exported=library.export(project);reports.append({'project':project['name'],'native_frames':native_decode(exported['ico']),'ico':exported['ico']})
root=tk.Tk();studio=Studio(root,library)
assert root.tk.call('set','unicode_probe','Choose…')=='Choose…'
assert 'Segoe UI' in font.families(root)
end=time.monotonic()+90
while time.monotonic()<end:
    root.update()
    if studio.last_hash and not studio.busy:break
    time.sleep(.03)
assert studio.last_hash and len(studio.frame_paths)==8,'The packaged GUI failed to finish its first preview.'
assert studio.fields['Variation name'].get()
root.destroy()
print(json.dumps({'portable_gui_started':True,'unicode_round_trip':True,'native_windows_icons':reports,'deployment':False}),flush=True)
