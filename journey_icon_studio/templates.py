"""Small editable starting points. Every visual component remains an SVG object."""
from math import cos,sin,pi
from xml.etree import ElementTree as ET
S='http://www.w3.org/2000/svg';I='http://www.inkscape.org/namespaces/inkscape'
ET.register_namespace('',S);ET.register_namespace('inkscape',I)
def tag(name):return '{'+S+'}'+name
SYMBOLS=('Clover','Star','Heart','Hexagon','Moon','Spark','None')

def symbol(kind,color):
    g=ET.Element(tag('g'),{'id':'studio-symbol','fill':color,'stroke':color,'stroke-width':'2','stroke-linejoin':'round'})
    if kind=='Clover':
        for x,y in ((112,134),(144,134),(112,166),(144,166)):
            ET.SubElement(g,tag('circle'),cx=str(x),cy=str(y),r='22')
        ET.SubElement(g,tag('path'),d='M132 163 Q145 192 121 195',fill='none',stroke=color,**{'stroke-width':'9','stroke-linecap':'round'})
    elif kind=='Star':
        points=[]
        for k in range(10):
            a=-pi/2+k*pi/5;r=42 if k%2==0 else 19
            points.append(f'{128+r*cos(a):.3f},{151+r*sin(a):.3f}')
        ET.SubElement(g,tag('polygon'),points=' '.join(points))
    elif kind=='Heart':ET.SubElement(g,tag('path'),d='M128 187 C92 163 79 144 91 128 C105 113 121 122 128 134 C139 114 160 119 169 132 C182 154 151 177 128 187Z')
    elif kind=='Hexagon':ET.SubElement(g,tag('path'),d='M128 109 164 130 164 172 128 193 92 172 92 130Z')
    elif kind=='Moon':ET.SubElement(g,tag('path'),d='M151 112 A41 41 0 1 0 158 180 A36 36 0 0 1 151 112Z')
    elif kind=='Spark':ET.SubElement(g,tag('path'),d='M128 104 139 139 174 151 139 163 128 198 117 163 82 151 117 139Z')
    return g


def make(kind='Folder',body='#38a375',accent='#baffd8',glyph='Clover'):
    root=ET.Element(tag('svg'),{'width':'256','height':'256','viewBox':'0 0 256 256','data-studio-template':kind,
        'data-body':body,'data-accent':accent,'data-symbol':glyph,'data-texture':'None','data-lighting':'Soft gloss','data-border':'2','data-opacity':'1'})
    defs=ET.SubElement(root,tag('defs'))
    grad=ET.SubElement(defs,tag('linearGradient'),id='studio-color',x1='0',y1='0',x2='1',y2='1',gradientUnits='objectBoundingBox')
    ET.SubElement(grad,tag('stop'),offset='0',**{'stop-color':accent,'data-role':'accent'})
    ET.SubElement(grad,tag('stop'),offset='.48',**{'stop-color':body,'data-role':'body'})
    ET.SubElement(grad,tag('stop'),offset='1',**{'stop-color':'#102c29'})
    shine=ET.SubElement(defs,tag('linearGradient'),id='studio-shine',x1='0',y1='0',x2='0',y2='1')
    ET.SubElement(shine,tag('stop'),offset='0',**{'stop-color':'#ffffff','stop-opacity':'.56'})
    ET.SubElement(shine,tag('stop'),offset='1',**{'stop-color':'#ffffff','stop-opacity':'0'})
    glow=ET.SubElement(defs,tag('filter'),id='studio-glow',x='-.5',y='-.5',width='2',height='2',**{'color-interpolation-filters':'sRGB'})
    ET.SubElement(glow,tag('feGaussianBlur'),stdDeviation='2.4',result='glow')
    merge=ET.SubElement(glow,tag('feMerge'))
    ET.SubElement(merge,tag('feMergeNode'),{'in':'glow'})
    ET.SubElement(merge,tag('feMergeNode'),{'in':'SourceGraphic'})
    pattern=ET.SubElement(defs,tag('pattern'),id='studio-texture',width='12',height='12',patternUnits='userSpaceOnUse')
    ET.SubElement(pattern,tag('path'),d='M0 12 12 0 M-3 3 3 -3 M9 15 15 9',stroke=accent,**{'stroke-width':'.8','opacity':'.30'})
    def layer(id,label):return ET.SubElement(root,tag('g'),{'id':id,'{'+I+'}groupmode':'layer','{'+I+'}label':label})
    back=layer('studio-back','01 · Backplate')
    chassis=layer('studio-body','02 · Body — editable paths')
    texture=layer('studio-texture-layer','03 · Texture')
    light=layer('studio-light','04 · Lighting')
    emblem=layer('studio-emblem','05 · Symbol — replace or draw your own')
    if kind=='Folder':
        ET.SubElement(back,tag('path'),d='M27 72 Q27 55 44 55 H94 L111 72 H211 Q228 72 228 89 V185 Q228 204 209 204 H44 Q27 204 27 187Z',fill='#142e2d',stroke=body,**{'stroke-width':'2','data-role':'body-stroke'})
        shape='M28 99 Q28 86 43 86 H215 Q230 86 227 102 L211 202 Q210 216 194 216 H43 Q28 216 28 201Z'
        ET.SubElement(chassis,tag('path'),d=shape,fill='url(#studio-color)',stroke=accent,**{'stroke-width':'2','id':'studio-surface'})
        ET.SubElement(texture,tag('path'),d=shape,fill='url(#studio-texture)',opacity='0')
        ET.SubElement(light,tag('path'),d='M34 102 Q34 92 47 92 H211 L204 121 Q105 137 34 180Z',fill='url(#studio-shine)')
    elif kind=='Drive':
        shape='M51 43 Q51 28 67 28 H189 Q205 28 205 43 V215 Q205 230 189 230 H67 Q51 230 51 215Z'
        ET.SubElement(chassis,tag('path'),d=shape,fill='#192933',stroke=accent,**{'stroke-width':'2','id':'studio-surface'})
        ET.SubElement(chassis,tag('path'),d='M61 45 Q61 38 69 38 H187 Q195 38 195 45 V188 H61Z',fill='url(#studio-color)')
        ET.SubElement(chassis,tag('rect'),x='65',y='204',width='111',height='7',rx='3.5',fill='#071216')
        ET.SubElement(chassis,tag('circle'),cx='187',cy='207',r='4',fill=accent,**{'data-role':'accent'})
        ET.SubElement(chassis,tag('path'),d='M76 59 H103 M76 68 H119 M76 77 H94',stroke=accent,**{'stroke-width':'3','opacity':'.7','data-role':'accent'})
        ET.SubElement(texture,tag('path'),d=shape,fill='url(#studio-texture)',opacity='0')
        ET.SubElement(light,tag('path'),d='M61 46 Q61 38 69 38 H187 Q195 38 195 46 V93 L61 158Z',fill='url(#studio-shine)')
    elif kind=='Project':
        shape='M128 24 220 77 V183 L128 236 36 183 V77Z'
        ET.SubElement(chassis,tag('path'),d=shape,fill='url(#studio-color)',stroke=accent,**{'stroke-width':'2','id':'studio-surface'})
        ET.SubElement(texture,tag('path'),d=shape,fill='url(#studio-texture)',opacity='0')
        ET.SubElement(light,tag('path'),d='M128 30 213 81 43 178 V81Z',fill='url(#studio-shine)')
    elif kind=='Blank':
        root.set('data-studio-template','Blank');return ET.tostring(root,encoding='unicode')
    else:raise ValueError('Choose Folder, Drive, Project or Blank.')
    emblem.append(symbol(glyph,accent))
    return ET.tostring(root,encoding='unicode')
