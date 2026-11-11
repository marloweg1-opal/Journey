"""Create disposable CareBloomOS workflow fixtures, never project canon or real assets."""

import argparse
import json
from pathlib import Path

from core.project_registry import PATTERN_FORMAT
from tools.demo_integrated_pilot import illustration, native_record


NAMES = ('Beat Character Sheet.png', 'Melody Character Sheet.png', 'render_17.png',
         'Heart Corestone Crystal.png', 'Heart Touchstone.png', 'Wishstone Wallpaper.png',
         'Cloudstone Armory Sheet.png', 'Cloverstone Character Sheet.png',
         'Moonstone Character Sheet.png', 'Opalstone Chibi.png')


def make_demo(base):
    base.mkdir()
    collection, exports = base / 'Collection copies', base / 'Local exports'
    collection.mkdir()
    exports.mkdir()
    colors = ('#439eba', '#ae67c1', '#6a9b52', '#c45890', '#c779a2')
    for index, name in enumerate(NAMES):
        illustration(collection / name, (560 + index * 23, 340 + index * 7), colors[index % len(colors)])
    profile = {'format': PATTERN_FORMAT, 'project': 'CareBloomOS',
               'signals': ['CareBloomOS', 'Moonstone', 'Cloverstone', 'Heartstone', 'Wishstone',
                           'Cloudstone', 'Musicstone', 'Corestone', 'Opalstone'], 'rules': []}
    pack = base / 'CareBloom-fixture-pack.json'
    pack.write_text(json.dumps({'format': 'journey-project-pack-1', 'profile': profile}), encoding='utf-8')
    panel = ('fixture-panel', 'user', 'CareBloomOS demonstration: `render_17.png` is a CareRail interface layout.', [])
    first = native_record('fixture-original', [panel], 'CareBloomOS disposable workflow fixture')
    second = native_record('fixture-expanded', [panel,
        ('fixture-duo', 'user', 'Musicstone: Beat and Melody each have a reference sheet.', []),
        ('fixture-opal', 'user', 'Corestone is Opalstone. Opalstone acts as the current Corestone.', [])],
        'CareBloomOS disposable workflow fixture')
    (exports / 'conversations-001.json').write_text(json.dumps([first]), encoding='utf-8')
    (exports / 'conversations-002.json').write_text(json.dumps([second]), encoding='utf-8')
    return collection, exports, pack


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path, help='A new directory for invented fixture material')
    for path in make_demo(parser.parse_args().output.resolve()):
        print(path)
