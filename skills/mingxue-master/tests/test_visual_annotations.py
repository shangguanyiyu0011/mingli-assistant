import hashlib
import importlib.util
import json
import os
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
HERE = Path(__file__).resolve().parents[1]
ROOT = Path(os.environ.get('MINGXUE_TEST_SKILL_ROOT', HERE))
if not (ROOT / 'scripts/visual_annotations.py').is_file():
    ROOT = HERE / 'package/mingxue-master'
sys.path.insert(0, str(ROOT / 'scripts'))
import visual_annotations as V

def chunk(kind, data):
    return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
def png():
    w, h = 200, 120
    rows = []
    for y in range(h):
        row = bytearray()
        for x in range(w):
            row.extend((0, 0, 0) if abs(y-(20+x//2)) < 2 else (235, 235, 235))
        rows.append(b'\0'+row)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR', struct.pack('>IIBBBBB',w,h,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(b''.join(rows)))+chunk(b'IEND',b'')

class TestAnnotations(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.p=Path(self.tmp.name)
        self.image=self.p/'picture.png'; self.image.write_bytes(png())
        self.annotations=self.p/'input.json'; self.annotations.write_text('{}')
        self.data={'system':'palm','image_sha256':hashlib.sha256(self.image.read_bytes()).hexdigest(),'observation_source':'assistant_visual_observation','annotations':[{'region':'thumb_arc','geometry':'polyline','points':[[0,20],[100,70],[198,119]]}]}
    def tearDown(self): self.tmp.cleanup()
    def test_overlay_and_provenance(self):
        page=V.render(self.image,self.data,self.annotations)
        self.assertIn('viewBox="0 0 200 120"',page); self.assertIn('0.000,20.000 100.000,70.000',page)
        self.assertIn('default-src',page); self.assertIn(self.data['image_sha256'],page)
        self.assertIn('assistant_visual_observation',page)
    def test_unrecognizable_empty_allowed(self):
        self.data['annotations']=[]
        self.assertNotIn('<polyline',V.render(self.image,self.data,self.annotations))
    def test_bad_inputs_rejected(self):
        for patch in ({'image_sha256':'0'*64},{'observation_source':'auto'},{'system':'<script>'}):
            with self.subTest(patch=patch), self.assertRaises((ValueError,TypeError)):
                V.render(self.image,{**self.data,**patch},self.annotations)
        for point in ([-1,20],[201,1],[float('nan'),1],[True,1]):
            self.data['annotations'][0]['points'][0]=point
            with self.subTest(point=point), self.assertRaises(ValueError): V.render(self.image,self.data,self.annotations)
    def test_exif_rotation_rejected(self):
        from unittest.mock import patch
        real = V.inspect_image(self.image)[0]
        real['orientation'] = 6
        with patch.object(V, 'inspect_image', return_value=(real, [])):
            with self.assertRaisesRegex(ValueError, 'orientation'):
                V.render(self.image, self.data, self.annotations)
    def test_path_html_is_escaped(self):
        # Ampersands are legal in Windows paths and must not become markup.
        named = self.p / 'a&b.png'; named.write_bytes(self.image.read_bytes())
        page = V.render(named, self.data, self.annotations)
        self.assertIn('a&amp;b.png', page)
    def test_no_injected_label(self):
        self.data['annotations'][0]['region']='<script>alert(1)</script>'
        with self.assertRaises(ValueError): V.render(self.image,self.data,self.annotations)
    def test_cli_never_overwrites(self):
        import subprocess
        self.annotations.write_text(json.dumps(self.data), encoding='utf8')
        output=self.p/'out.html'; output.write_text('keep',encoding='utf8')
        result=subprocess.run([sys.executable,str(ROOT/'scripts'/'visual_annotations.py'),'--image',str(self.image),'--annotations',str(self.annotations),'--output',str(output)],capture_output=True,text=True,encoding='utf8')
        self.assertNotEqual(result.returncode,0); self.assertEqual(output.read_text(),'keep')

if __name__=='__main__': unittest.main()

