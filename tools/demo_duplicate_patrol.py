"""Create a disposable housekeeping collection and overlapping invented history."""
import argparse
import json
from pathlib import Path
from PIL import Image
from tools.demo_carebloom_collection import make_demo as collection_demo
from tools.demo_integrated_pilot import illustration, native_record


def make_demo(base):
    collection,exports,pack=collection_demo(base)
    original=collection/'Moonstone Character Sheet.png'
    (collection/'Moonstone Character Sheet (1).png').write_bytes(original.read_bytes())
    Image.open(original).resize((280,170)).save(collection/'Moonstone small export.jpg',quality=75)
    illustration(collection/'Primrose Hinamori Character Sheet.png',(630,410),'#e88cbe')
    (collection/'project.ini').write_text('required=Heart Touchstone.png\n',encoding='utf-8')
    panel=('fixture-panel','user','CareBloomOS demonstration: `render_17.png` is a CareRail interface layout.',[])
    second=native_record('fixture-expanded',[panel,
        ('fixture-duo','user','Musicstone: Beat and Melody each have a reference sheet.',[]),
        ('fixture-opal','user','Corestone is Opalstone. Opalstone acts as the current Corestone.',[]),
        ('fixture-character','user','Heartstone aka Primrose Hinamori. `Primrose Hinamori Character Sheet.png` is a character reference.',[]),
        ('fixture-revision','user','`Moonstone small export.jpg` is derived from `Moonstone Character Sheet.png`.',[])],
        'CareBloomOS disposable housekeeping fixture')
    (exports/'conversations-002.json').write_text(json.dumps([second]),encoding='utf-8')
    return collection,exports,pack

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('output',type=Path)
    for path in make_demo(parser.parse_args().output.resolve()):print(path)
