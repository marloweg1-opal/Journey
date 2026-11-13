"""A graphical library around the mature Inkscape editor; no shell customization."""
import os
from pathlib import Path
import queue
import shutil
import subprocess
from threading import Thread
import tkinter as tk
from tkinter import ttk,filedialog,messagebox,colorchooser,simpledialog
from PIL import Image,ImageTk,ImageDraw
from .core import Library,SIZES
from .templates import SYMBOLS

BG='#101b21';PANEL='#192930';INK='#e7f4ee';MUTED='#9ebbb0';GREEN='#79e3b2';EDGE='#30474d'
FONT='Segoe UI' if os.name=='nt' else 'DejaVu Sans'
ASSETS=Path(__file__).parent/'assets'
if (ASSETS/'references').is_dir():ASSETS=ASSETS/'references'

class Studio:
    def __init__(self,root,library):
        self.root=root;self.library=library;self.current=None;self.items=[];self.photos=[];self.busy=False;self.results=queue.Queue();self.preview_generation=0;self.last_hash=None
        root.title('Journey Icon Studio · Design, keep, remix');root.geometry('1370x940');root.minsize(1080,780);root.configure(bg=BG)
        self.style();self.build();self.seed();self.refresh();root.after(100,self.poll);root.after(1600,self.watch)
        def select_all(event):
            event.widget.selection_range(0,'end');event.widget.icursor('end');return 'break'
        root.bind_class('TEntry','<Control-a>',select_all)
    def style(self):
        style=ttk.Style();style.theme_use('clam')
        style.configure('.',background=BG,foreground=INK,font=(FONT,10),bordercolor=EDGE)
        style.configure('TFrame',background=BG);style.configure('TLabel',background=BG,foreground=INK)
        style.configure('Muted.TLabel',foreground=MUTED);style.configure('Title.TLabel',font=(FONT,23,'bold'))
        style.configure('TButton',background='#243b43',foreground=INK,padding=(10,7),borderwidth=0)
        style.map('TButton',background=[('active','#39555e')],foreground=[('disabled','#708984')])
        style.configure('Accent.TButton',background=GREEN,foreground='#102a20',font=(FONT,10,'bold'))
        style.map('Accent.TButton',background=[('active','#a1f7ce')])
        style.configure('TEntry',fieldbackground='#24353c',foreground=INK,insertcolor=INK,padding=6)
        style.configure('TSpinbox',fieldbackground='#24353c',foreground=INK,insertcolor=INK)
        style.configure('TCombobox',fieldbackground='#24353c',foreground=INK,arrowsize=16,padding=4)
        style.map('TCombobox',fieldbackground=[('readonly','#24353c')],foreground=[('readonly',INK)])
        style.configure('TNotebook.Tab',padding=(13,7),background='#20343c');style.map('TNotebook.Tab',background=[('selected','#35534c')])
        style.configure('TLabelframe',background=BG,bordercolor=EDGE);style.configure('TLabelframe.Label',background=BG,foreground=GREEN)
    def button(self,parent,text,command,accent=False,**kw):
        b=ttk.Button(parent,text=text,command=lambda:self.guard(command),style='Accent.TButton' if accent else 'TButton',**kw);return b
    def build(self):
        head=ttk.Frame(self.root,padding=(22,15));head.pack(fill='x')
        ttk.Label(head,text='ICON STUDIO',style='Title.TLabel').pack(side='left')
        ttk.Label(head,text='  JOURNEY / HEXSEED  ·  YOUR DESIGN WORKSPACE',style='Muted.TLabel').pack(side='left',padx=16)
        self.button(head,'Workspace…',self.choose_workspace).pack(side='right')
        self.button(head,'Walkthrough',self.help).pack(side='right',padx=8)
        bar=ttk.Frame(self.root,padding=(22,0,22,12));bar.pack(fill='x')
        for text,fn in [('New design',self.new_design),('Import artwork',self.import_art),('Duplicate project',self.duplicate),('Save as master',self.master)]:self.button(bar,text,fn).pack(side='left',padx=(0,7))
        self.button(bar,'Export PNG + SVG + ICO',self.export,True).pack(side='right')
        self.button(bar,'Open visual editor',self.editor,True).pack(side='right',padx=8)
        content=ttk.PanedWindow(self.root,orient='horizontal');content.pack(fill='both',expand=True,padx=18)
        left=ttk.Frame(content,width=250,padding=(4,4,12,4));content.add(left,weight=1)
        ttk.Label(left,text='YOUR ASSET LIBRARY',font=(FONT,11,'bold')).pack(anchor='w',pady=(0,8))
        self.tabs=ttk.Notebook(left);self.tabs.pack(fill='both',expand=True)
        self.lists={}
        for key,label in (('projects','Projects'),('masters','Master templates')):
            pane=ttk.Frame(self.tabs);self.tabs.add(pane,text=label)
            listing=tk.Listbox(pane,bg=PANEL,fg=INK,selectbackground='#355f50',selectforeground='#ffffff',borderwidth=0,highlightthickness=0,
                exportselection=False,font=(FONT,11),activestyle='none',width=26)
            listing.pack(fill='both',expand=True);listing.bind('<<ListboxSelect>>',lambda e,k=key:self.select(k));self.lists[key]=listing
        ttk.Label(left,text='Masters are reusable starting points.\nYour variations are independent files.\nNo icon deployment is included.',style='Muted.TLabel',wraplength=235).pack(anchor='w',pady=12)
        self.button(left,'Import supplied reference…',self.import_reference).pack(fill='x')
        center=ttk.Frame(content,padding=(8,4));content.add(center,weight=3)
        self.title=ttk.Label(center,text='Create something that feels like you',font=(FONT,15,'bold'));self.title.pack(anchor='w')
        self.subtitle=ttk.Label(center,text='Choose a master or start with a blank artboard.',style='Muted.TLabel',wraplength=620);self.subtitle.pack(anchor='w',pady=(4,10))
        self.canvas=tk.Canvas(center,width=512,height=400,bg=PANEL,highlightthickness=0);self.canvas.pack(fill='both',expand=True)
        self.canvas.bind('<Configure>',lambda e:self.redraw_large())
        row=ttk.Frame(center);row.pack(fill='x',pady=(9,5))
        self.background=tk.StringVar(value='Dark');ttk.Label(row,text='Canvas').pack(side='left')
        for text in ('Dark','Light','Checkerboard'):
            ttk.Radiobutton(row,text=text,value=text,variable=self.background,command=self.redraw_large).pack(side='left',padx=5)
        self.button(row,'Refresh saved artwork',self.reload).pack(side='right')
        self.previews=ttk.Frame(center);self.previews.pack(fill='x',pady=(2,8))
        ttk.Label(center,text='Actual 16–64 px frames below, on light + dark. Inspect 128 / 256 px separately.',style='Muted.TLabel',wraplength=620).pack(anchor='w')
        self.size_canvas=tk.Canvas(center,height=190,bg=BG,highlightthickness=0);self.size_canvas.pack(fill='x')
        self.button(center,'Inspect 128 / 256 px light / dark',self.preview_256).pack(anchor='e')
        right_host=ttk.Frame(content,width=290);content.add(right_host,weight=1)
        right_canvas=tk.Canvas(right_host,bg=BG,width=290,highlightthickness=0)
        scroll=ttk.Scrollbar(right_host,orient='vertical',command=right_canvas.yview);scroll.pack(side='right',fill='y')
        right_canvas.configure(yscrollcommand=scroll.set);right_canvas.pack(side='left',fill='both',expand=True)
        right=ttk.Frame(right_canvas,padding=(12,4,4,4));window=right_canvas.create_window((0,0),window=right,anchor='nw')
        right.bind('<Configure>',lambda e:right_canvas.configure(scrollregion=right_canvas.bbox('all')))
        right_canvas.bind('<Configure>',lambda e:right_canvas.itemconfigure(window,width=e.width))
        ttk.Label(right,text='REMIX A SAVED DESIGN',font=(FONT,11,'bold')).pack(anchor='w')
        ttk.Label(right,text='These controls create a new variation.\nSave in Inkscape first to include edits.',style='Muted.TLabel',wraplength=270).pack(anchor='w',pady=7)
        self.fields={}
        def entry(label,initial):
            ttk.Label(right,text=label).pack(anchor='w',pady=(7,2));v=tk.StringVar(value=initial);ttk.Entry(right,textvariable=v).pack(fill='x');self.fields[label]=v
        entry('Variation name','My folder')
        for label,color in (('Body color','#38a375'),('Accent / symbol','#baffd8')):
            frame=ttk.Frame(right);frame.pack(fill='x',pady=(8,0));ttk.Label(frame,text=label).pack(side='left');v=tk.StringVar(value=color);self.fields[label]=v
            self.button(frame,'Choose…',lambda l=label:self.color(l)).pack(side='right');ttk.Entry(right,textvariable=v).pack(fill='x',pady=(3,0))
        for label,values,initial in [('Symbol',SYMBOLS,'Clover'),('Texture',('None','Lines','Dots'),'None'),('Lighting',('Flat','Soft gloss','Glow'),'Soft gloss')]:
            ttk.Label(right,text=label).pack(anchor='w',pady=(7,2));v=tk.StringVar(value=initial);ttk.Combobox(right,textvariable=v,values=values,state='readonly').pack(fill='x');self.fields[label]=v
        numeric=ttk.Frame(right);numeric.pack(fill='x',pady=(8,0))
        for label,initial,lo,hi,step in [('Border px','2',0,16,.5),('Opacity','1',0,1,.05)]:
            box=ttk.Frame(numeric);box.pack(side='left',fill='x',expand=True,padx=(0,8));ttk.Label(box,text=label).pack(anchor='w');v=tk.StringVar(value=initial);ttk.Spinbox(box,textvariable=v,from_=lo,to=hi,increment=step,width=8).pack();self.fields[label]=v
        self.remix=self.button(right,'Create independent variation',self.variation,True);self.remix.pack(fill='x',pady=12)
        assignment=ttk.Frame(right);assignment.pack(fill='x');ttk.Label(assignment,text='Library assignment (design label only)').pack(anchor='w')
        self.assignment=tk.StringVar(value='Unassigned');pick=ttk.Combobox(assignment,textvariable=self.assignment,values=('Unassigned','Folder','C:','R:','D:','Other drive','Project','Application','Custom'),state='readonly');pick.pack(fill='x',pady=4);pick.bind('<<ComboboxSelected>>',lambda e:self.guard(self.assign))
        self.button(right,'Bulk color / symbol variations…',self.bulk).pack(fill='x',pady=6)
        self.button(right,'Replace any saved color…',self.replace_color).pack(fill='x')
        self.button(right,'Layers and design tools…',self.tools).pack(fill='x',pady=6)
        self.status=tk.StringVar(value='Ready · editable source projects stay in this workspace. No Windows settings are changed.')
        ttk.Label(self.root,textvariable=self.status,style='Muted.TLabel',padding=(22,10),wraplength=1300).pack(side='bottom',fill='x',before=content)
        self.root.bind('<Control-q>',lambda e:self.root.destroy())
        self.root.bind('<Control-o>',lambda e:self.guard(self.import_art));self.root.bind('<Control-e>',lambda e:self.guard(self.editor));self.root.bind('<Control-d>',lambda e:self.guard(self.duplicate))
        self.large=None;self.frame_paths={}
    def seed(self):
        if not self.library.list(masters=True):
            for kind in ('Folder','Drive','Project','Blank'):self.library.new(kind+' master',kind,master=True)
    def refresh(self,select=None,masters=False):
        self.items_by={key:self.library.list(key=='masters') for key in self.lists}
        for key,listing in self.lists.items():
            listing.delete(0,'end')
            for p in self.items_by[key]:listing.insert('end',f'{p["name"]}   ·   {p["assignment"]}')
        if select:
            key='masters' if masters else 'projects';self.tabs.select(1 if masters else 0)
            for i,p in enumerate(self.items_by[key]):
                if p['id']==select['id']:self.lists[key].selection_set(i);self.lists[key].see(i);self.select(key);break
        elif not self.current and self.items_by['masters']:
            self.tabs.select(1);index=next((i for i,p in enumerate(self.items_by['masters']) if p['design']=='Folder'),0);self.lists['masters'].selection_set(index);self.select('masters')
    def select(self,key):
        selected=self.lists[key].curselection()
        if not selected:return
        self.current=self.items_by[key][selected[0]];self.last_hash=None;self.load_controls();self.reload()
    def load_controls(self):
        info=self.library.inspect(self.current);self.title.configure(text=self.current['name']);self.assignment.set(self.current['assignment'])
        self.fields['Variation name'].set(self.current['name'].removesuffix(' master')+' variation')
        for key,field in [('body','Body color'),('accent','Accent / symbol'),('symbol','Symbol'),('texture','Texture'),('lighting','Lighting'),('border','Border px'),('opacity','Opacity')]:self.fields[field].set(str(info[key]))
        self.remix.configure(state='normal' if info['template'] not in (None,'Blank') else 'disabled')
        detail=f'{info["width"]} × {info["height"]} · {len(info["layers"])} layers · {self.current["design"]}'
        if self.current.get('source',{}):detail+=' · original preserved'
        self.subtitle.configure(text=detail)
    def guard(self,fn):
        try:return fn()
        except Exception as error:self.status.set('Stopped · '+str(error));messagebox.showerror('Journey Icon Studio',str(error),parent=self.root)
    def need(self):
        if not self.current:raise ValueError('Choose a project or master first.')
        return self.current
    def work(self,message,fn,done):
        if self.busy:raise ValueError('A preview or export is still running. Its progress appears at the bottom.')
        self.busy=True;self.status.set(message);self.root.configure(cursor='watch')
        def run():
            try:self.results.put((done,fn(),None))
            except Exception as e:self.results.put((done,None,e))
        Thread(target=run,daemon=True).start()
    def poll(self):
        try:
            done,value,error=self.results.get_nowait();self.busy=False;self.root.configure(cursor='')
            if error:self.guard(lambda:(_ for _ in ()).throw(error))
            else:self.guard(lambda:done(value))
        except queue.Empty:pass
        self.root.after(100,self.poll)
    def reload(self):
        project=dict(self.need());generation=self.preview_generation=self.preview_generation+1
        if self.busy:self.preview_generation-=1;return
        def done(paths):
            if generation!=self.preview_generation or not self.current or project['id']!=self.current['id']:return
            self.frame_paths=paths;self.last_hash=self.library.inspect(project)['hash']
            with Image.open(paths[512]) as im:self.large=im.convert('RGBA').copy()
            self.redraw_large();self.redraw_sizes();self.status.set('Preview ready · all seven saved-source frames rendered. Ctrl+S in Inkscape updates this workspace automatically.')
        self.work('Rendering saved SVG at seven Windows sizes and 512 px…',lambda:self.library.preview(project),done)
    def watch(self):
        if self.current and not self.busy:
            try:
                digest=self.library.inspect(self.current)['hash']
                if self.last_hash and digest!=self.last_hash:self.load_controls();self.reload()
            except (OSError,ValueError):self.status.set('Artwork is being saved or is temporarily unreadable. The previous preview is retained.')
        self.root.after(1800,self.watch)
    def redraw_large(self):
        if self.large is None:return
        w=max(100,self.canvas.winfo_width());h=max(100,self.canvas.winfo_height());size=min(w-30,h-25,512)
        art=self.large.copy();art.thumbnail((size,size),Image.Resampling.LANCZOS)
        bg=self.background.get();color='#14252d' if bg=='Dark' else '#f2f1ed'
        base=Image.new('RGBA',(size,size),color)
        if bg=='Checkerboard':
            d=ImageDraw.Draw(base)
            for y in range(0,size,14):
                for x in range(0,size,14):d.rectangle((x,y,x+13,y+13),fill='#cbd3d0' if (x//14+y//14)%2 else '#edf2ef')
        base.alpha_composite(art,((size-art.width)//2,(size-art.height)//2));self.poster=ImageTk.PhotoImage(base)
        self.canvas.delete('all');self.canvas.create_image(w//2,h//2,image=self.poster);self.canvas.create_text(w//2,h-8,text='Preview of last saved SVG · create and edit visually in Inkscape',fill=MUTED,font=(FONT,9),anchor='s')
    def redraw_sizes(self):
        self.photos=[];self.size_canvas.configure(height=184)
        self.size_canvas.delete('all');x=6
        for size in SIZES[:-2]:
            tile=max(28,size+8)
            for row,color in enumerate(('#edf1ed','#111c24')):
                with Image.open(self.frame_paths[size]) as im:art=im.convert('RGBA')
                bg=Image.new('RGBA',(tile,tile),color);bg.alpha_composite(art,((tile-size)//2,(tile-size)//2));photo=ImageTk.PhotoImage(bg);self.photos.append(photo)
                self.size_canvas.create_image(x,20+row*80,image=photo,anchor='nw')
            self.size_canvas.create_text(x+tile//2,3,text=f'{size} px',fill=MUTED,anchor='n',font=(FONT,9));x+=tile+8
    def preview_256(self):
        if not self.frame_paths:raise ValueError('Wait for the preview to finish.')
        window=tk.Toplevel(self.root);window.title('Actual 128 / 256 px frames · light and dark');photos=[]
        for size in (128,256):
            ttk.Label(window,text=f'{size} px · native pixels · light and dark',padding=(12,10)).pack(anchor='w')
            row=ttk.Frame(window);row.pack(fill='x')
            with Image.open(self.frame_paths[size]) as im:art=im.convert('RGBA')
            for color in ('#f0f3ef','#111c24'):
                bg=Image.new('RGBA',(size+24,size+24),color);bg.alpha_composite(art,(12,12));photo=ImageTk.PhotoImage(bg);photos.append(photo);ttk.Label(row,image=photo).pack(side='left',padx=12,pady=(0,10))
        window.photos=photos
    def color(self,key):
        value=colorchooser.askcolor(self.fields[key].get(),title=key,parent=self.root)[1]
        if value:self.fields[key].set(value)
    def title_prompt(self,initial):return simpledialog.askstring('Name your editable project','Project name',initialvalue=initial,parent=self.root)
    def new_design(self):
        win=tk.Toplevel(self.root);win.title('Choose a starting point');win.configure(bg=BG);win.transient(self.root)
        ttk.Label(win,text='A starting point, not a fixed design',font=(FONT,15,'bold'),padding=20).pack()
        for kind in ('Folder','Drive','Project','Blank'):
            def choose(k=kind):
                title=self.title_prompt('My '+k.lower())
                if title:
                    project=self.library.new(title,k);win.destroy();self.refresh(project)
            self.button(win,kind,choose).pack(fill='x',padx=20,pady=5)
    def import_art(self):
        path=filedialog.askopenfilename(title='Import a copy of artwork',filetypes=[('Artwork','*.svg *.png *.jpg *.jpeg *.webp *.ico'),('All files','*')])
        if path:self.import_path(path)
    def import_reference(self):
        path=filedialog.askopenfilename(title='Choose supplied reference artwork to import as a copy',initialdir=ASSETS,filetypes=[('Artwork','*.svg *.png')])
        if path:self.import_path(path)
    def import_path(self,path):
        title=self.title_prompt(Path(path).stem)
        if title:
            project=self.library.import_file(path,title);self.refresh(project)
            if project.get('source',{}).get('kind'):messagebox.showinfo('Bitmap reference imported','The original is unchanged. This is an embedded bitmap layer, not reconstructed vector objects. Move, crop, overlay or use Path → Trace Bitmap in Inkscape.',parent=self.root)
    def duplicate(self):
        p=self.need();title=self.title_prompt(p['name']+' copy')
        if title:self.refresh(self.library.copy(p,title))
    def master(self):
        p=self.need();title=self.title_prompt(p['name']+' master')
        if title:self.refresh(self.library.copy(p,title,master=True),masters=True)
    def editor(self,dialog=None):
        p=self.need()
        if p['master']:
            title=self.title_prompt(p['name'].removesuffix(' master')+' design')
            if not title:return
            p=self.library.copy(p,title);self.refresh(p)
        path=self.library.open_editor(p,dialog);self.status.set('Opened visual editor · '+str(path)+' · save with Ctrl+S to update Studio previews.')
    def variation(self):
        p=self.need();f={k:v.get() for k,v in self.fields.items()}
        project=self.library.variation(p,f['Variation name'],body=f['Body color'],accent=f['Accent / symbol'],glyph=f['Symbol'],texture=f['Texture'],lighting=f['Lighting'],border=f['Border px'],opacity=f['Opacity']);self.refresh(project)
    def assign(self):
        p=self.need();self.current=self.library.assign(p,self.assignment.get());self.refresh(self.current,masters=p['master']);self.status.set('Saved design assignment only. Windows drive and folder settings were not changed.')
    def replace_color(self):
        p=self.need();colors=self.library.inspect(p)['colors'];win=tk.Toplevel(self.root);win.title('Replace a color in an independent variation');win.configure(bg=BG)
        ttk.Label(win,text='Choose an existing paint, then its replacement.',padding=16).pack();old=tk.StringVar(value=colors[0] if colors else '#000000');ttk.Combobox(win,textvariable=old,values=colors,state='readonly').pack(padx=16,pady=8)
        def create():
            new=colorchooser.askcolor(old.get(),parent=win,title='Replacement color')[1]
            if not new:return
            title=self.title_prompt(p['name']+' recolor')
            if title:
                project=self.library.replace_color(p,title,old.get(),new);win.destroy();self.refresh(project)
        self.button(win,'Choose replacement and save variation',create,True).pack(padx=16,pady=16)
    def bulk(self):
        p=self.need();info=self.library.inspect(p)
        tagged=bool(info['template'] and info['template']!='Blank')
        if not tagged and not info['colors']:raise ValueError('No explicit six-digit paints were found. Set a fill in Inkscape, save, then retry bulk color variants.')
        win=tk.Toplevel(self.root);win.title('Bulk variations · independent editable projects');win.configure(bg=BG)
        ttk.Label(win,text='Choose colors and symbols. Each combination is a separate project.',padding=16).pack()
        palette=[];symbols={}
        old_color=tk.StringVar(value=info['colors'][0] if info['colors'] else info['body'])
        if not tagged:
            ttk.Label(win,text='Replace this saved paint in each custom variation:').pack(pady=5)
            ttk.Combobox(win,textvariable=old_color,values=info['colors'],state='readonly').pack(pady=5)
            ttk.Label(win,text='Custom geometry is preserved. Edit arbitrary symbols in Inkscape.').pack(pady=5)
        palette_box=ttk.Frame(win);palette_box.pack(fill='x',padx=16)
        status=tk.StringVar(value='No colors selected.');ttk.Label(win,textvariable=status).pack(pady=8)
        def add():
            value=colorchooser.askcolor(info['body'],parent=win)[1]
            if value and value not in palette:
                palette.append(value);status.set(' · '.join(palette));self.button(palette_box,value,lambda:None).pack(side='left',padx=3)
        self.button(win,'Add a color…',add).pack(pady=5)
        box=ttk.Frame(win);box.pack(padx=16,pady=10)
        for glyph in (SYMBOLS if tagged else ('Keep custom symbols',)):
            v=tk.BooleanVar(value=glyph==info['symbol'] or not tagged);symbols[glyph]=v;ttk.Checkbutton(box,text=glyph,variable=v).pack(side='left',padx=4)
        def generate():
            glyphs=[k for k,v in symbols.items() if v.get()]
            if not palette or not glyphs or len(palette)*len(glyphs)>32:raise ValueError('Choose 1–32 color/symbol combinations.')
            made=[]
            for color in palette:
                for glyph in glyphs:
                    title=p['name'][:40]+' '+color[1:]+(' '+glyph if tagged else '')
                    made.append(self.library.variation(p,title,body=color,accent=info['accent'],glyph=glyph,texture=info['texture'],lighting=info['lighting'],border=info['border'],opacity=info['opacity']) if tagged else self.library.replace_color(p,title,old_color.get(),color))
            win.destroy();self.refresh(made[-1]);self.status.set(f'Saved {len(made)} independently editable variants. No originals were overwritten.')
        self.button(win,'Generate editable projects',generate,True).pack(padx=16,pady=16)
    def tools(self):
        p=self.need();info=self.library.inspect(p);win=tk.Toplevel(self.root);win.title('Visual editing tools');win.configure(bg=BG)
        ttk.Label(win,text='All artwork is edited visually in Inkscape.',font=(FONT,14,'bold'),padding=16).pack(anchor='w')
        ttk.Label(win,text='Select objects on the canvas. Use the controls below to open the relevant editor panel.\nThe toolbar provides exact X / Y / width / height values. Click an object twice to rotate.',padding=(16,0,16,12)).pack(anchor='w')
        for tool in ('Layers and objects','Fill and stroke','Align and distribute','Transform','Symbols','Filters and lighting','Document size','Trace bitmap'):
            self.button(win,tool,lambda t=tool:self.editor(t)).pack(fill='x',padx=16,pady=3)
        ttk.Label(win,text='Saved SVG layers:\n'+'\n'.join(layer['name'] for layer in info['layers']),padding=16).pack(anchor='w')
    def export(self):
        p=dict(self.need())
        def done(value):
            self.status.set('Export verified · seven sizes, 32-bit alpha · '+value['directory'])
            if messagebox.askyesno('Export complete','PNG, editable SVG, seven-size ICO and verification report saved.\n\nOpen the export folder?\n\n'+value['directory'],parent=self.root):self.open_folder(Path(value['directory']))
        self.work('Exporting saved artwork and independently verifying all seven ICO frames…',lambda:self.library.export(p),done)
    def open_folder(self,path):
        if os.name=='nt':os.startfile(path)
        else:subprocess.Popen(['xdg-open',str(path)])
    def choose_workspace(self):
        if self.busy:raise ValueError('Wait for the current preview/export to finish.')
        path=filedialog.askdirectory(title='Choose an Icon Studio workspace',initialdir=self.library.root)
        if path:
            self.library=Library(path,self.library.engine);self.current=None;self.large=None;self.seed();self.refresh()
    def help(self):
        win=tk.Toplevel(self.root);win.title('A practical icon design walkthrough');win.configure(bg=BG)
        text='''1   NEW DESIGN → FOLDER. Name it and select it in your library.
2   OPEN VISUAL EDITOR. Inkscape is the canvas: draw, select and reshape objects.
     Layers: Shift+Ctrl+L. Fill/gradients/border: Shift+Ctrl+F. Transform: Shift+Ctrl+M.
     Align: Shift+Ctrl+A. Symbols and filters are in the Object / Filters menus.
3   SAVE WITH CTRL+S IN INKSCAPE. Studio refreshes the saved SVG automatically.
4   PICK BODY / ACCENT COLORS AND A SYMBOL. Give the variation its own name.
     CREATE INDEPENDENT VARIATION saves another fully editable project.
5   Repeat with a different color and symbol. Each project can be edited separately.
6   NEW DESIGN → DRIVE starts separate geometry. C:, R: and D: assignments are
     optional library labels. They do not link palettes or change Windows settings.
7   EXPORT PNG + SVG + ICO. Seven verified icon frames are included: 16, 24, 32,
     48, 64, 128 and 256 px. Light / dark previews show actual exported-size frames.
8   SAVE AS MASTER keeps a reusable design. BULK VARIATIONS creates independent
     color / symbol combinations. Blank and imported SVG projects use the full editor.

Imported bitmap artwork remains a bitmap layer until you trace or redraw it.
SVG retains vector objects and supported effects. Originals are imported as copies.
Preview and export use the last SAVED artwork. Save editor changes first.
Your project folder contains artwork.svg and project.json; keep both for the library.
Create and export only: no drive assignments, desktop.ini edits, registry changes,
shortcuts, system icon changes or icon deployment are performed.'''
        ttk.Label(win,text=text,justify='left',padding=22,font=(FONT,11)).pack()
