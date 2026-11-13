"""Local project library and a rendering/export bridge. No deployment capabilities."""
from base64 import b64encode
from copy import deepcopy
from datetime import datetime,timezone
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
from tempfile import TemporaryDirectory
from uuid import uuid4
from xml.etree import ElementTree as ET
from PIL import Image
from .templates import make,symbol,tag,S,I,SYMBOLS

SIZES=(16,24,32,48,64,128,256)
LIMIT=32*1024*1024
PACKAGE=Path(__file__).resolve().parents[2]

def timestamp():return datetime.now(timezone.utc).isoformat()
def name(value):
    value=str(value).strip()
    if not value or len(value)>80 or re.search(r'[\x00-\x1f<>:"/\\|?*]',value) or value.endswith(('.', ' ')) or value.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}:
        raise ValueError('Use a name of 1–80 characters without Windows filename punctuation.')
    return value

def safe_svg(data):
    if isinstance(data,str):data=data.encode('utf-8')
    if len(data)>LIMIT or b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():raise ValueError('SVG exceeds the import budget or includes unsupported document declarations.')
    root=ET.fromstring(data)
    if root.tag!=tag('svg'):raise ValueError('Choose an SVG document.')
    for element in root.iter():
        local=element.tag.rsplit('}',1)[-1]
        if local in ('script','foreignObject','animate','set','animateTransform','animateMotion'):raise ValueError('Interactive or animated SVG content is not supported. Save a static copy in Inkscape.')
        strings=[element.text or ''] if local=='style' else []
        for key,value in element.attrib.items():
            key=key.rsplit('}',1)[-1]
            if key.lower().startswith('on'):raise ValueError('SVG event handlers are unsupported.')
            if key=='href' and not (value.startswith('#') or re.match(r'^data:image/(?:png|jpeg|webp);base64,',value)):
                raise ValueError('Embed linked images in Inkscape before importing. Studio does not read adjacent files or remote links.')
            if key in ('style','fill','stroke','filter','clip-path','mask','marker-start','marker-end'):strings.append(value)
        for text in strings:
            if '@import' in text.lower() or any(not x.strip().strip(chr(39)+chr(34)).startswith('#') for x in re.findall(r'url\(([^)]*)\)',text,re.I)):raise ValueError('External SVG resources are unsupported. Embed them before importing.')
    return root

def atomic(path,data):
    path=Path(path)
    if path.is_symlink():raise ValueError('A linked studio file cannot be replaced.')
    temporary=path.parent/('.save-'+uuid4().hex)
    try:
        with temporary.open('xb') as f:f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(temporary,path)
    finally:temporary.unlink(missing_ok=True)

def encode(root):return ET.tostring(root,encoding='utf-8',xml_declaration=True)
def paint(value):
    if not re.fullmatch(r'#[0-9a-fA-F]{6}',value):raise ValueError('Choose a six-digit color using the color picker.')
    return value.lower()

def engine_path(explicit=None):
    choices=[explicit,PACKAGE/'inkscape/bin/inkscape.exe',PACKAGE/'inkscape/inkscape.exe',shutil.which('inkscape')]
    if os.name=='nt':
        choices.extend([Path(os.environ.get('ProgramFiles','C:/Program Files'))/'Inkscape/bin/inkscape.exe'])
    for item in choices:
        if item and Path(item).is_file():return Path(item).resolve()
    raise FileNotFoundError('Inkscape is unavailable. Use the complete portable Studio package, or choose an existing Inkscape executable in Studio.')

class Library:
    def __init__(self,root,inkscape=None):
        self.root=Path(root).resolve();self.root.mkdir(parents=True,exist_ok=True)
        if self.root.is_symlink():raise ValueError('Choose a regular workspace folder.')
        self.projects=self.root/'Projects';self.masters=self.root/'Masters';self.state=self.root/'.studio'
        for path in (self.projects,self.masters,self.state):
            if path.is_symlink():raise ValueError('Linked workspace directories are unsupported.')
            path.mkdir(exist_ok=True)
        self.engine=engine_path(inkscape);self.editors=[]
    def environment(self):
        return os.environ|{'INKSCAPE_PROFILE_DIR':str(self.state/'inkscape-profile'),'XDG_CACHE_HOME':str(self.state/'cache')}
    def _owned(self,path):
        path=Path(path)
        if not path.resolve().is_relative_to(self.root) or path.is_symlink() or any(p.is_symlink() for p in [path.parent,*path.parents] if p.is_relative_to(self.root)):
            raise ValueError('The project is outside this workspace or contains a filesystem link.')
        return path
    def list(self,masters=False):
        items=[]
        for folder in (self.masters if masters else self.projects).iterdir():
            if folder.is_symlink() or not folder.is_dir():continue
            try:items.append(self.load(folder))
            except (OSError,ValueError,KeyError,json.JSONDecodeError):continue
        return sorted(items,key=lambda p:p['updated'],reverse=True)
    def load(self,folder):
        folder=self._owned(folder);manifest=self._owned(folder/'project.json');art=self._owned(folder/'artwork.svg')
        data=json.loads(manifest.read_text(encoding='utf-8'))
        if data['format']!='journey-icon-project-1' or not art.is_file():raise ValueError('This folder is not an editable Studio project.')
        return data|{'folder':str(folder)}
    def create(self,title,svg,*,parent=None,assignment='Unassigned',source=None,master=False):
        title=name(title);root=safe_svg(svg)
        target=(self.masters if master else self.projects)/(title+'-'+uuid4().hex[:8]);target.mkdir()
        self._owned(target)
        data={'format':'journey-icon-project-1','id':uuid4().hex,'name':title,'parent':parent,'assignment':assignment,
            'created':timestamp(),'updated':timestamp(),'master':master,'source':source,'artwork':'artwork.svg','design':root.get('data-studio-template','Imported / custom')}
        try:
            atomic(target/'artwork.svg',encode(root));atomic(target/'project.json',json.dumps(data,indent=2).encode())
        except Exception:
            # Preserve partial work for inspection; never remove user originals.
            raise
        return self.load(target)
    def new(self,title,kind='Folder',**kwargs):return self.create(title,make(kind),**kwargs)
    def svg(self,project):return self._owned(Path(project['folder'])/'artwork.svg')
    def inspect(self,project):
        root=safe_svg(self.svg(project).read_bytes())
        layers=[{'id':e.get('id',''),'name':e.get('{'+I+'}label',e.get('id','Layer')),'hidden':'display:none' in e.get('style','')} for e in root.iter() if e.get('{'+I+'}groupmode')=='layer']
        colors=set()
        for e in root.iter():
            for k in ('fill','stroke','stop-color'):
                if re.fullmatch(r'#[0-9a-fA-F]{6}',e.get(k,'')):colors.add(e.get(k).lower())
            colors.update(x.lower() for x in re.findall(r'#[0-9a-fA-F]{6}\b',e.get('style','')))
        return {'template':root.get('data-studio-template'),'body':root.get('data-body','#38a375'),'accent':root.get('data-accent','#baffd8'),
            'symbol':root.get('data-symbol','None'),'texture':root.get('data-texture','None'),'lighting':root.get('data-lighting','Soft gloss'),
            'border':root.get('data-border','2'),'opacity':root.get('data-opacity','1'),'layers':layers,'colors':sorted(colors),
            'width':root.get('width','256'),'height':root.get('height','256'),'viewBox':root.get('viewBox',''),'hash':sha256(encode(root)).hexdigest()}
    def import_file(self,path,title=None):
        path=Path(path).resolve()
        if not path.is_file() or path.stat().st_size>LIMIT:raise ValueError('Choose a regular SVG or image no larger than 32 MiB.')
        raw=path.read_bytes();source={'name':path.name,'sha256':sha256(raw).hexdigest(),'imported':timestamp(),'original_modified':False}
        if path.suffix.lower()=='.svg':return self.create(title or path.stem,raw,source=source)
        if path.suffix.lower() not in ('.png','.jpg','.jpeg','.webp','.ico'):raise ValueError('Import SVG, PNG, JPEG, WebP or ICO.')
        with Image.open(BytesIO(raw)) as im:
            if im.width*im.height>40_000_000:raise ValueError('The reference exceeds the 40-megapixel budget.')
            im=im.convert('RGBA');stream=BytesIO();im.save(stream,format='PNG');w,h=im.size
        root=ET.Element(tag('svg'),{'width':'256','height':'256','viewBox':'0 0 256 256'})
        layer=ET.SubElement(root,tag('g'),{'id':'imported-image','{'+I+'}groupmode':'layer','{'+I+'}label':'Imported bitmap · move/resize or trace in Inkscape'})
        scale=min(256/w,256/h)
        ET.SubElement(layer,tag('image'),{'x':str((256-w*scale)/2),'y':str((256-h*scale)/2),'width':str(w*scale),'height':str(h*scale),'href':'data:image/png;base64,'+b64encode(stream.getvalue()).decode()})
        source['kind']='embedded bitmap; not automatically reconstructed vector layers'
        return self.create(title or path.stem,encode(root),source=source)
    def copy(self,project,title,master=False):return self.create(title,self.svg(project).read_bytes(),parent=project['id'],assignment=project['assignment'],master=master,source=project.get('source'))
    def assign(self,project,assignment):
        if assignment not in ('Unassigned','Folder','C:','R:','D:','Other drive','Project','Application','Custom'):raise ValueError('Choose an assignment in Studio.')
        data=self.load(project['folder']);data.pop('folder');data.update(assignment=assignment,updated=timestamp())
        atomic(Path(project['folder'])/'project.json',json.dumps(data,indent=2).encode())
        return self.load(project['folder'])
    def variation(self,project,title,*,body,accent,glyph,texture='None',lighting='Soft gloss',border=2,opacity=1):
        body,accent=paint(body),paint(accent);border=float(border);opacity=float(opacity)
        if not 0<=border<=16 or not 0<=opacity<=1:raise ValueError('Border must be 0–16 px; opacity must be 0–1.')
        if glyph not in SYMBOLS or texture not in ('None','Lines','Dots') or lighting not in ('Flat','Soft gloss','Glow'):
            raise ValueError('Choose listed symbol, texture and lighting settings.')
        root=safe_svg(self.svg(project).read_bytes())
        if not root.get('data-studio-template') or root.get('data-studio-template')=='Blank':raise ValueError('Use Inkscape to edit custom artwork, or use Replace color to make a variation.')
        required=('studio-symbol','studio-surface','studio-texture-layer','studio-light','studio-texture')
        by_id={e.get('id'):e for e in root.iter() if e.get('id')}
        if any(k not in by_id for k in required):raise ValueError('This template was restructured in the editor. Use native editing or Replace color; Studio will not rebuild your layers.')
        old_body=root.get('data-body');old_accent=root.get('data-accent')
        for e in root.iter():
            role=e.get('data-role')
            if role:
                for key in ('fill','stroke','stop-color'):
                    if key in e.attrib and (not role.endswith('-stroke') or key=='stroke'):e.set(key,body if role.startswith('body') else accent)
            # Only tagged paints are modified; arbitrary new objects are preserved.
        by_id['studio-surface'].set('stroke',accent);by_id['studio-surface'].set('stroke-width',str(border))
        by_id['studio-body'].set('opacity',str(opacity))
        group=by_id['studio-emblem'];old=by_id['studio-symbol'];index=list(group).index(old)
        replacement=symbol(glyph,accent)
        for key in ('transform','opacity'):
            if key in old.attrib:replacement.set(key,old.get(key))
        group.remove(old);group.insert(index,replacement)
        overlay=by_id['studio-texture-layer']
        for e in overlay:e.set('opacity','0' if texture=='None' else '.6')
        pattern=by_id['studio-texture'];pattern.clear();pattern.attrib.update(id='studio-texture',width='12',height='12',patternUnits='userSpaceOnUse')
        if texture=='Dots':ET.SubElement(pattern,tag('circle'),cx='3',cy='3',r='1',fill=accent)
        else:ET.SubElement(pattern,tag('path'),d='M0 12 12 0 M-3 3 3 -3 M9 15 15 9',stroke=accent,**{'stroke-width':'.8'})
        by_id['studio-light'].set('opacity','0' if lighting=='Flat' else '1')
        if lighting=='Glow':group.set('filter','url(#studio-glow)')
        else:group.attrib.pop('filter',None)
        for k,v in {'body':body,'accent':accent,'symbol':glyph,'texture':texture,'lighting':lighting,'border':border,'opacity':opacity}.items():root.set('data-'+k,str(v))
        return self.create(title,encode(root),parent=project['id'],assignment=project['assignment'],source=project.get('source'))
    def replace_color(self,project,title,old,new):
        old,new=paint(old),paint(new);root=safe_svg(self.svg(project).read_bytes());count=0
        for e in root.iter():
            for key,value in list(e.attrib.items()):
                changed=re.sub(re.escape(old)+r'(?![0-9a-f])',new,value,flags=re.I)
                if changed!=value:e.set(key,changed);count+=1
            if e.tag==tag('style') and e.text:
                changed=re.sub(re.escape(old)+r'(?![0-9a-f])',new,e.text,flags=re.I)
                if changed!=e.text:e.text=changed;count+=1
        if not count:raise ValueError('That color is absent from this saved SVG. Choose a color from its palette.')
        return self.create(title,encode(root),parent=project['id'],assignment=project['assignment'],source=project.get('source'))
    def render(self,project,size,output):
        if size not in (*SIZES,512):raise ValueError('Choose a supported preview size.')
        source=self.svg(project);root=safe_svg(source.read_bytes());output=self._owned(output)
        # Icon canvases are square; fit the saved artboard proportionally rather than stretch it.
        if not root.get('viewBox'):
            dimensions=[]
            factors={'':1,'px':1,'mm':96/25.4,'cm':96/2.54,'in':96,'pt':96/72,'pc':16}
            for key in ('width','height'):
                match=re.fullmatch(r'([0-9.]+)(px|mm|cm|in|pt|pc)?',root.get(key,''))
                if not match:raise ValueError('Set an explicit artboard size in Inkscape Document Properties before exporting.')
                dimensions.append(float(match[1])*factors[match[2] or ''])
            root.set('viewBox','0 0 '+str(dimensions[0])+' '+str(dimensions[1]))
        values=[float(x) for x in re.split('[ ,]+',root.get('viewBox').strip())]
        if len(values)!=4 or min(values[2:])<=0:raise ValueError('Set a valid artboard in Inkscape before exporting.')
        root.set('width','256');root.set('height','256');root.set('preserveAspectRatio','xMidYMid meet')
        fitted=output.parent/('.render-'+uuid4().hex+'.svg');atomic(fitted,encode(root))
        executable=self.engine.with_suffix('.com') if os.name=='nt' and self.engine.with_suffix('.com').exists() else self.engine
        flags={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}
        result=subprocess.run([str(executable),'--app-id-tag=journey-icon-render',str(fitted),'--export-area-page','--export-background-opacity=0',f'--export-width={size}',f'--export-height={size}',f'--export-filename={output}'],
            env=self.environment(),capture_output=True,timeout=90,**flags)
        fitted.unlink(missing_ok=True)
        if result.returncode or not output.is_file():raise RuntimeError('Inkscape could not render this saved project. '+result.stderr.decode(errors='replace')[-700:])
        with Image.open(output) as image:
            if image.size!=(size,size):raise ValueError('The renderer returned unexpected dimensions.')
        return output
    def preview(self,project):
        info=self.inspect(project);cache=Path(project['folder'])/'.preview';self._owned(cache);cache.mkdir(exist_ok=True)
        for size in (*SIZES,512):
            target=cache/f'{info["hash"]}-{size}.png'
            if not target.exists():self.render(project,size,target)
        return {size:cache/f'{info["hash"]}-{size}.png' for size in (*SIZES,512)}
    def export(self,project):
        frames=self.preview(project);directory=Path(project['folder'])/'Exports'/timestamp().replace(':','-');self._owned(directory);directory.mkdir(parents=True)
        source=self.svg(project);raw=source.read_bytes();safe_svg(raw)
        svg=directory/(name(project['name'])+'.svg');atomic(svg,raw)
        png=directory/(project['name']+'.png');shutil.copyfile(frames[256],png)
        frame_dir=directory/'PNG sizes';frame_dir.mkdir()
        chunks=[]
        for size in SIZES:
            data=frames[size].read_bytes()
            with Image.open(BytesIO(data)) as image:
                image=image.convert('RGBA');stream=BytesIO();image.save(stream,format='PNG');data=stream.getvalue()
            (frame_dir/f'{size}.png').write_bytes(data);chunks.append(data)
        offset=6+16*len(SIZES);header=struct.pack('<HHH',0,1,len(SIZES));entries=[]
        for size,data in zip(SIZES,chunks):
            entries.append(struct.pack('<BBBBHHII',size if size<256 else 0,size if size<256 else 0,0,0,1,32,len(data),offset));offset+=len(data)
        ico=directory/(project['name']+'.ico');atomic(ico,header+b''.join(entries)+b''.join(chunks))
        verification=verify_ico(ico)
        for size in SIZES:
            assert verification['hashes'][str(size)]==sha256((frame_dir/f'{size}.png').read_bytes()).hexdigest()
        report={'format':'journey-icon-export-1','project':project['id'],'source_sha256':sha256(raw).hexdigest(),'exported':timestamp(),
            'files':[svg.name,png.name,ico.name],'sizes':list(SIZES),'verification':verification,'deployment':False,
            'note':'SVG retains vectors where present and embeds imported bitmap layers. ICO frames use PNG compression supported by modern Windows.'}
        atomic(directory/'verification.json',json.dumps(report,indent=2).encode())
        return {'directory':str(directory),'ico':str(ico),'svg':str(svg),'png':str(png),'report':report}
    def open_editor(self,project,dialog=None):
        source=self.svg(project);safe_svg(source.read_bytes())
        args=[str(self.engine),'--with-gui','--app-id-tag=journey-icon-studio',str(source)]
        allowed={'Fill and stroke':'FillStroke','Layers and objects':'Objects','Align and distribute':'AlignDistribute',
            'Transform':'Transformation','Symbols':'Symbols','Filters and lighting':'FilterEffects','Document size':'DocumentProperties','Trace bitmap':'Trace'}
        actions=['window-set-geometry:0,0,1280,900']
        if dialog:
            if dialog not in allowed:raise ValueError('Choose an editor tool in Studio.')
            actions.append('dialog-open:'+allowed[dialog])
        args+=['--actions='+(';'.join(actions))]
        self.editors=[p for p in self.editors if p.poll() is None]
        self.editors.append(subprocess.Popen(args,env=self.environment(),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL))
        return source


def verify_ico(path):
    data=Path(path).read_bytes()
    if len(data)<6 or struct.unpack_from('<HH',data)!=(0,1):raise ValueError('Invalid ICO header.')
    count=struct.unpack_from('<H',data,4)[0]
    if count!=len(SIZES):raise ValueError('ICO frame count differs from the requested sizes.')
    sizes=[];hashes={};ranges=[]
    for n in range(count):
        w,h,palette,reserved,planes,bpp,length,offset=struct.unpack_from('<BBBBHHII',data,6+16*n);w=w or 256;h=h or 256
        if reserved or palette or planes!=1 or bpp!=32 or offset<6+16*count or offset+length>len(data):raise ValueError('Invalid ICO directory entry.')
        payload=data[offset:offset+length]
        with Image.open(BytesIO(payload)) as im:
            im.load()
            if im.size!=(w,h) or im.mode!='RGBA':raise ValueError('ICO frame dimensions/alpha are invalid.')
        sizes.append(w);ranges.append((offset,offset+length));hashes[str(w)]=sha256(payload).hexdigest()
    if tuple(sizes)!=SIZES or any(a[1]>b[0] for a,b in zip(ranges,ranges[1:])):raise ValueError('ICO sizes or payload ranges are invalid.')
    with Image.open(BytesIO(data)) as im:
        if sorted(im.ico.sizes())!=[(n,n) for n in SIZES]:raise ValueError('Pillow could not independently decode the complete icon.')
        for size in SIZES:im.ico.getimage((size,size)).load()
    return {'verified':True,'sizes':sizes,'bits_per_pixel':32,'alpha':True,'hashes':hashes,'ico_sha256':sha256(data).hexdigest()}
