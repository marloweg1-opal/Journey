"""Actual Inkscape renders and independently decoded icon files, with unchanged imports."""
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase,main
from xml.etree import ElementTree as ET
import json,os,struct
from PIL import Image
from journey_icon_studio.core import Library,SIZES,safe_svg,verify_ico
from journey_icon_studio.templates import tag,make

class IconStudioTests(TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory(prefix='journey-icon-studio-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.library=Library(self.root/'Workspace',os.environ.get('JOURNEY_ICON_INKSCAPE'))
    def test_independent_folder_variations_preserve_native_geometry_and_master(self):
        a=self.library.new('Folder master','Folder',master=True);original=self.library.svg(a).read_bytes()
        one=self.library.copy(a,'Jade clover');root=safe_svg(self.library.svg(one).read_bytes())
        body=root.find('.//*[@id="studio-body"]');body.set('transform','translate(3 2) rotate(2 128 128)')
        root.find('.//*[@id="studio-symbol"]').set('transform','matrix(.9,0,0,.9,12,15)')
        ET.SubElement(root,tag('circle'),{'id':'personally-added-object','cx':'50','cy':'50','r':'8','fill':'#ee5522'})
        self.library.svg(one).write_bytes(ET.tostring(root))
        before=self.library.svg(one).read_bytes()
        two=self.library.variation(one,'Cobalt star',body='#355eb4',accent='#d3eaff',glyph='Star',texture='Lines',lighting='Glow',border=3,opacity=.9)
        self.assertEqual(self.library.svg(one).read_bytes(),before);self.assertEqual(self.library.svg(a).read_bytes(),original)
        modified=safe_svg(self.library.svg(two).read_bytes())
        self.assertEqual(modified.find('.//*[@id="studio-body"]').get('transform'),body.get('transform'))
        self.assertIsNotNone(modified.find('.//*[@id="personally-added-object"]'))
        self.assertEqual(modified.find('.//*[@id="studio-symbol"]').get('transform'),'matrix(.9,0,0,.9,12,15)')
        for p in (one,two):
            out=self.library.export(p);self.assertTrue(out['report']['verification']['verified'])
            with Image.open(out['ico']) as icon:
                for size in SIZES:
                    frame=icon.ico.getimage((size,size));self.assertEqual(frame.size,(size,size));self.assertEqual(frame.getextrema()[3][0],0)
        self.assertNotEqual(self.library.inspect(one)['hash'],self.library.inspect(two)['hash'])
    def test_svg_and_bitmap_imports_leave_originals_intact_and_embed_the_bitmap(self):
        source=self.root/'original.svg';source.write_text(make('Drive'),encoding='utf-8')
        png=self.root/'original.png';Image.new('RGBA',(400,200),(12,120,83,140)).save(png)
        before={p:(p.read_bytes(),p.stat().st_mtime_ns) for p in (source,png)}
        vector=self.library.import_file(source);bitmap=self.library.import_file(png)
        self.assertEqual(vector['design'],'Drive');self.assertIn('bitmap',bitmap['source']['kind'])
        self.assertIn('data:image/png;base64,',self.library.svg(bitmap).read_text())
        self.assertEqual(before,{p:(p.read_bytes(),p.stat().st_mtime_ns) for p in (source,png)})
        out=self.library.export(bitmap)
        with Image.open(out['png']) as im:self.assertEqual(im.size,(256,256));self.assertEqual(im.getpixel((128,1))[3],0)
    def test_non_square_artboard_is_fitted_without_stretching(self):
        svg='<svg xmlns="http://www.w3.org/2000/svg" width="400" height="200" viewBox="0 0 400 200"><circle cx="200" cy="100" r="80" fill="#ff0000"/></svg>'
        p=self.library.create('Non-square artwork',svg);out=self.library.export(p)
        with Image.open(out['png']) as im:
            box=im.getbbox();self.assertLessEqual(abs((box[2]-box[0])-(box[3]-box[1])),1)
        self.assertEqual(self.library.inspect(p)['viewBox'],'0 0 400 200')
    def test_independent_drive_assignment_and_custom_svg_recolor(self):
        folder=self.library.new('R folder','Folder');drive=self.library.new('C drive','Drive')
        self.library.assign(folder,'R:');self.library.assign(drive,'C:')
        self.assertEqual(self.library.load(folder['folder'])['assignment'],'R:')
        self.assertNotEqual(self.library.inspect(folder)['hash'],self.library.inspect(drive)['hash'])
        p=self.library.create('Custom vector','<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"><rect x="30" y="30" width="90" height="90" fill="#ff0000"/></svg>')
        q=self.library.replace_color(p,'My own recolor','#ff0000','#00ff00')
        self.assertIn('#ff0000',self.library.svg(p).read_text());self.assertIn('#00ff00',self.library.svg(q).read_text())
        exported=self.library.export(drive);self.assertTrue(verify_ico(exported['ico'])['verified'])
    def test_unsafe_linked_svg_and_invalid_icon_are_refused(self):
        for content in ('<script/>','<image href="file:///private.png"/>','<image href="https://example.com/x.png"/>','<rect style="fill:url(https://example.com/x)"/>'):
            with self.assertRaises(ValueError):safe_svg('<svg xmlns="http://www.w3.org/2000/svg">'+content+'</svg>')
        path=self.root/'bad.ico';path.write_bytes(b'not-an-icon')
        with self.assertRaises(ValueError):verify_ico(path)
    def test_restructured_template_is_not_silently_recreated(self):
        p=self.library.new('Reworked folder','Folder');root=safe_svg(self.library.svg(p).read_bytes())
        group=root.find('.//*[@id="studio-emblem"]');root.remove(group);self.library.svg(p).write_bytes(ET.tostring(root))
        before=self.library.svg(p).read_bytes()
        with self.assertRaisesRegex(ValueError,'restructured'):self.library.variation(p,'Variation',body='#00ff00',accent='#ffffff',glyph='Star')
        self.assertEqual(self.library.svg(p).read_bytes(),before)

if __name__=='__main__':main()
