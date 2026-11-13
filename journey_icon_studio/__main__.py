"""Launch the local graphical Icon Studio, independently from Navigator and deployment."""
import argparse
import os
from pathlib import Path
import sys

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--workspace',type=Path);parser.add_argument('--inkscape',type=Path);args=parser.parse_args()
    if os.name=='nt':
        import ctypes
        try:ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except (AttributeError,OSError):pass
    runtime=Path(sys.executable).parent
    if (runtime/'tcl/tcl9.0/init.tcl').exists():
        os.environ['TCL_LIBRARY']=str(runtime/'tcl/tcl9.0');os.environ['TK_LIBRARY']=str(runtime/'tcl/tk9.0')
    import tkinter as tk
    from tkinter import messagebox,filedialog
    from .core import Library,PACKAGE
    from .gui import Studio
    root=tk.Tk()
    try:
        workspace=args.workspace or (PACKAGE/'Studio Workspace' if os.name=='nt' else Path.home()/'Journey Icon Studio')
        try:library=Library(workspace,args.inkscape)
        except FileNotFoundError:
            root.withdraw();messagebox.showinfo('Choose Inkscape','Choose an existing Inkscape executable. This does not install anything. Use the complete portable package to include the editor.')
            selected=filedialog.askopenfilename(title='Choose Inkscape executable')
            if not selected:root.destroy();return
            library=Library(workspace,selected);root.deiconify()
        Studio(root,library);root.mainloop()
    except Exception as error:
        messagebox.showerror('Icon Studio could not start',str(error));root.destroy()

if __name__=='__main__':main()
