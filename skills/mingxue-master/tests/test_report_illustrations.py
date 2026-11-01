"""Generated raster diagrams must keep current person/photo/result binding."""
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT=Path(os.environ.get("MINGXUE_TEST_SKILL_ROOT",Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(ROOT/"scripts"))
import agent_report
import report_illustrations as images
from test_personal_report_security import Document
from test_visual_intake import png,JPEG
from visual_annotations import illustration_html


def record(role,system):
    ref={"id":role.lower()*32,"sha256":("c" if role=="A" else "d")*64}
    photo={**ref,"person":role,"kind":"portrait" if system=="face" else "palm_left","include_in_report":False}
    panel={"system":system,"state":"intake_only","reading_status":"applied","result_sha256":role.lower()*64,
           "traditional_interpretation":{"text":"只说明本次照片里可见的轮廓。"},"facts":[],"title":system}
    report={"person":{"name":role},"panels":[panel],"revision":"v000001","topic":"生活",
            "question":"怎样认识自己的习惯？","question_hash":"e"*64,"selected_profile":"default",
            "effective_settings":{},"input_version_notice":"","interpretation":""}
    return {"role":role.lower(),"report":report,"packed":{"person":{"name":role}},"workspace":Path("/unused"),"photos":[photo],
            "payloads":{system:{"system":system,"status":"intake_only","observation_status":"agent_observed",
                "photo_refs":[ref],"user_reported_observations":{"features":[{"region":"outline","shape":"curved","visibility":"clear"}]}}}}


class IllustrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.records=[record("A","palm"),record("B","face")]
        self.entries=[]
        for person,system,raw,suffix in (("A","palm",png(),"png"),("B","face",JPEG,"jpg")):
            path=self.root/(person+"."+suffix);path.write_bytes(raw)
            self.entries.append({"person":person,"system":system,"result_sha256":person.lower()*64,
                "image":str(path),"sha256":hashlib.sha256(raw).hexdigest(),"caption":person+"的轮廓示意，不增加照片中未见的特征。"})

    def load(self,entries=None,records=None):
        manifest=self.root/"illustrations.json"
        manifest.write_text(json.dumps(self.entries if entries is None else entries,ensure_ascii=False),encoding="utf-8")
        return images.load_illustrations(manifest,self.records if records is None else records)

    def photo_entry(self):
        path=self.root/'original.jpg';path.write_bytes(JPEG)
        photo=self.records[0]['photos'][0]
        photo.update(file=str(path),sha256=hashlib.sha256(JPEG).hexdigest())
        payload=self.records[0]['payloads']['palm']
        payload['photo_refs']=[{'id':photo['id'],'sha256':photo['sha256']}]
        payload['user_reported_observations']['features']=[{'region':'thumb_arc','shape':'curved','visibility':'clear'}]
        return {'kind':'photo_annotation','person':'A','system':'palm','result_sha256':'a'*64,
                'photo_id':photo['id'],'photo_sha256':photo['sha256'],'use_original_photo':True,
                'caption':'本人原掌照','annotations':[{'region':'thumb_arc','label':'拇指根部弧线','observation':'只标出可见的一段弧线。',
                    'geometry':'polyline','points':[[1,1],[3,2],[6,4]]}]}

    def test_photo_annotation_preserves_exact_jpeg_and_only_safe_fields(self):
        entry=self.photo_entry();image=self.load([entry])[('A','palm')][0]
        self.assertEqual(set(image),{'kind','src','caption','overlay'})
        self.assertEqual(set(image['overlay']),{'width','height','annotations'})
        self.assertEqual((image['overlay']['width'],image['overlay']['height']),(8,6))
        self.assertEqual(base64.b64decode(image['src'].split(',',1)[1]),JPEG)
        self.assertNotIn(str(self.root),json.dumps(image))
        self.assertFalse(self.records[0]['photos'][0]['include_in_report'])

    def generated_photo_entry(self):
        photo=self.photo_entry()
        return {**self.entries[0],**{k:photo[k] for k in ('photo_id','photo_sha256','use_original_photo')}}

    def test_generated_original_annotation_has_explicit_source_binding_without_original_bytes(self):
        entry=self.generated_photo_entry();figure=self.load([entry])[('A','palm')][0]
        self.assertEqual(set(figure),{'src','caption','kind','source_photo_id'})
        self.assertEqual(figure['kind'],'generated_photo_annotation')
        self.assertEqual(figure['source_photo_id'],entry['photo_id'])
        self.assertEqual(base64.b64decode(figure['src'].split(',',1)[1]),Path(entry['image']).read_bytes())
        self.assertNotEqual(base64.b64decode(figure['src'].split(',',1)[1]),JPEG)
        self.assertIn('原图AI标注 · ',illustration_html(figure,'palm'))
        from personal_report import person_data
        self.assertEqual(person_data({'person':{'name':'A'},'reader_photos':[{'id':entry['photo_id'],'src':'original'}],
                                     'panels':[{'illustrations':[figure]}]})['photos'],[])

    def test_generated_original_annotation_rejects_missing_authorization_cross_person_stale_or_unedited(self):
        for key,value in [('use_original_photo',False),('use_original_photo',1),('use_original_photo','true'),
                          ('person','B'),('photo_id','b'*32),('photo_sha256','f'*64),('result_sha256','0'*64),('kind','generated_photo_annotation')]:
            entry=self.generated_photo_entry();entry[key]=value
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):self.load([entry])
        entry=self.generated_photo_entry();del entry['use_original_photo']
        with self.assertRaises(ValueError):self.load([entry])
        entry=self.generated_photo_entry();entry.update(image=self.records[0]['photos'][0]['file'],sha256=entry['photo_sha256'])
        with self.assertRaises(ValueError):self.load([entry])

    def test_photo_annotation_requires_explicit_authorization_current_person_and_sha(self):
        for key,value in [('use_original_photo',False),('use_original_photo',1),('use_original_photo','true'),
                          ('person','B'),('photo_id','b'*32),('photo_sha256','f'*64),('result_sha256','0'*64)]:
            entry=self.photo_entry();entry[key]=value
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):self.load([entry])
        entry=self.photo_entry();del entry['use_original_photo']
        with self.assertRaises(ValueError):self.load([entry])
        entry=self.photo_entry();Path(self.records[0]['photos'][0]['file']).write_bytes(png())
        with self.assertRaises(ValueError):self.load([entry])

    def test_photo_annotation_vectors_are_bound_to_visible_features_and_finite_pixels(self):
        patches=[('region','eye_outline'),('region','palm_outline'),('geometry','script'),
                 ('points',[[True,1],[2,2]]),('points',[[float('nan'),1],[2,2]]),('points',[[float('inf'),1],[2,2]]),
                 ('points',[[-1,1],[2,2]]),('points',[[9,1],[2,2]]),('points',[[1,7],[2,2]]),
                 ('points',[[1,1]]),('points',[[1,1],[1,1]]),('label',''),('observation','')]
        for key,value in patches:
            entry=self.photo_entry();entry['annotations'][0][key]=value
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):self.load([entry])
        entry=self.photo_entry();del entry['annotations'][0]['observation']
        with self.assertRaises(ValueError):self.load([entry])
        entry=self.photo_entry();entry['annotations'][0].update(geometry='polygon',points=[[1,1],[2,2]])
        with self.assertRaises(ValueError):self.load([entry])
        entry=self.photo_entry();self.records[0]['payloads']['palm']['user_reported_observations']['features'][0]['visibility']='not_visible'
        with self.assertRaises(ValueError):self.load([entry])

    def test_photo_annotation_rejects_exif_rotation_or_unreadable_exif(self):
        for changes,notes in [({'orientation':6},[]),({'exif_present':True},['EXIF structure could not be read'])]:
            entry=self.photo_entry();info,_=images.inspect_image(Path(self.records[0]['photos'][0]['file']));info.update(changes)
            with mock.patch.object(images,'inspect_image',return_value=(info,notes)),self.assertRaises(ValueError):self.load([entry])

    def test_photo_annotation_noscript_svg_escape_and_no_duplicate_photo_gallery(self):
        entry=self.photo_entry();entry['annotations'][0].update(label='弧线 <img onerror=坏> & 观察',observation='可见 <script>坏</script>，不补画。')
        bound=self.load([entry])[('A','palm')][0]
        markup=illustration_html(bound,'palm')
        self.assertIn('viewBox="0 0 8 6"',markup);self.assertIn('points="1,1 3,2 6,4"',markup)
        self.assertIn('&lt;img onerror=坏&gt;',markup);self.assertNotIn('<script>',markup)
        job=self.root/('c'*32);job.mkdir()
        current={'pending_photo_review':[],'synthesis_required':False,'people':[{'name':'A','needs_readings':[]}], 'pair_comparison':{}}
        with mock.patch.object(agent_report,'snapshot',return_value=(job,{'mode':'single','preferences':{}},self.records[:1])),mock.patch.object(agent_report,'describe_snapshot',return_value=current):
            result=agent_report.finalize(job,illustrations_file=self.root/'illustrations.json',allow_structural_only=True)
        raw=Path(result['files'][0]['path']).read_text(encoding='utf-8');parsed=Document();parsed.feed(raw)
        fallback=raw.split('</noscript>')[0]
        self.assertIn('<polyline points="1,1 3,2 6,4"',fallback)
        self.assertIn('原图标注 · 本人原掌照',fallback)
        self.assertNotIn('AI分析示意图 · 本人原掌照',fallback)
        self.assertEqual(parsed.data()['people'][0]['photos'],[])
        self.assertEqual(parsed.dangerous,[]);self.assertEqual(parsed.resources,[])
        from personal_report import person_data
        person=person_data({'person':{'name':'A'},'reader_photos':[{'src':bound['src']}],
                            'panels':[{'illustrations':[bound]}]})
        self.assertEqual(person['photos'],[])

    def test_png_jpeg_are_embedded_without_paths(self):
        result=self.load();self.assertEqual(set(result),{("A","palm"),("B","face")})
        for entry in self.entries:
            image=result[(entry["person"],entry["system"])][0]
            self.assertEqual(set(image),{"src","caption"})
            self.assertEqual(base64.b64decode(image["src"].split(",",1)[1]),Path(entry["image"]).read_bytes())
            self.assertNotIn(entry["image"],json.dumps(result[(entry["person"],entry["system"])]))

    def test_schema_hashes_and_caption_are_strict(self):
        bad=[{},self.entries*3]
        for key,value in (("extra",True),("person","C"),("system","tarot"),("result_sha256","0"*64),
                          ("sha256","0"*64),("caption",""),("caption",r"C:\private\photo.png")):
            entries=copy.deepcopy(self.entries);entries[0][key]=value;bad.append(entries)
        for entries in bad:
            with self.subTest(entries=str(entries)[:80]),self.assertRaises(ValueError):self.load(entries)

    def test_unobserved_empty_features_or_unreadable_panels_cannot_receive_images(self):
        for change in ("status","features","refs","reading","result","person","kind","photo_sha"):
            records=copy.deepcopy(self.records);a=records[0];payload=a["payloads"]["palm"]
            if change=="status":payload["observation_status"]="user_reported"
            elif change=="features":payload["user_reported_observations"]["features"]=[]
            elif change=="refs":payload["photo_refs"]=[]
            elif change=="reading":a["report"]["panels"][0]["reading_status"]="missing"
            elif change=="result":a["report"]["panels"][0]["result_sha256"]="0"*64
            elif change=="person":a["photos"][0]["person"]="B"
            elif change=="kind":a["photos"][0]["kind"]="portrait"
            else:a["photos"][0]["sha256"]="f"*64
            with self.subTest(change=change),self.assertRaises(ValueError):self.load(records=records)

    def test_original_photo_and_reused_generated_image_are_rejected(self):
        records=copy.deepcopy(self.records);records[1]["photos"][0]["sha256"]=self.entries[0]["sha256"]
        with self.assertRaises(ValueError):self.load(records=records)
        entries=copy.deepcopy(self.entries);entries[1].update(image=entries[0]["image"],sha256=entries[0]["sha256"])
        with self.assertRaises(ValueError):self.load(entries)

    def test_paths_remote_svg_fake_corrupt_and_oversize_are_rejected(self):
        for path in ("relative.png","https://example.test/a.png","file:///tmp/a.png",r"\\host\share\a.png",
                     str(ROOT/"assets"/"diagram.png"),str(self.root/"diagram.svg"),str(self.root/"a.png:secret")):
            entries=copy.deepcopy(self.entries);entries[0]["image"]=path
            with self.subTest(path=path),self.assertRaises(ValueError):self.load(entries)
        for raw in (b"<svg/>",png()[:-6],bytes(images.MAX_IMAGE_BYTES+1)):
            Path(self.entries[0]["image"]).write_bytes(raw)
            self.entries[0]["sha256"]=hashlib.sha256(raw).hexdigest()
            with self.assertRaises(ValueError):self.load()

    def test_link_in_any_path_component_is_rejected(self):
        with mock.patch("photo_uploads.Path.is_symlink",return_value=True):
            with self.assertRaises(ValueError):self.load()

    def test_four_distinct_images_allowed_fifth_rejected(self):
        entries=[]
        for n in range(4):
            path=self.root/(str(n)+".png");raw=png(width=9+n);path.write_bytes(raw)
            entries.append({**self.entries[0],"image":str(path),"sha256":hashlib.sha256(raw).hexdigest()})
        self.assertEqual(len(self.load(entries)[("A","palm")]),4)
        with self.assertRaises(ValueError):self.load(entries+[entries[0]])

    def test_finalize_keeps_single_pair_and_noscript_person_binding(self):
        job=self.root/("a"*32);job.mkdir()
        request={"mode":"pair","preferences":{"relationship":"朋友","depth":"brief"}}
        current={"pending_photo_review":[],"synthesis_required":False,"people":[{"name":"A","needs_readings":[]},{"name":"B","needs_readings":[]}],"pair_comparison":{}}
        self.load()
        with mock.patch.object(agent_report,"snapshot",return_value=(job,request,self.records)),mock.patch.object(agent_report,"describe_snapshot",return_value=current):
            result=agent_report.finalize(job,illustrations_file=self.root/"illustrations.json",allow_structural_only=True)
        self.assertEqual(result["status"],"exported")
        for entry in result["files"]:
            raw=Path(entry["path"]).read_text(encoding="utf-8");page=Document();page.feed(raw);data=page.data()
            self.assertEqual(page.dangerous,[]);self.assertEqual(page.resources,[])
            self.assertTrue(all(not person["photos"] for person in data["people"]))
            for panel in data["panels"]:
                role="A" if panel["system"]=="palm" else "B"
                self.assertTrue(panel["illustrations"][0]["caption"].startswith(role))
                self.assertIn(panel["illustrations"][0]["caption"],raw.split("</noscript>")[0])
                if entry["role"]=="pair":self.assertEqual(panel["person_index"],0 if role=="A" else 1)
            for original in self.entries:self.assertNotIn(original["image"],raw)

    def test_invalid_illustration_fails_before_delivery_is_created(self):
        job=self.root/("b"*32);job.mkdir();self.entries[0]["result_sha256"]="0"*64
        manifest=self.root/"bad.json";manifest.write_text(json.dumps(self.entries),encoding="utf-8")
        with mock.patch.object(agent_report,"snapshot",return_value=(job,{},self.records)):
            with self.assertRaises(ValueError):agent_report.finalize(job,illustrations_file=manifest)
        self.assertFalse((job/"deliveries").exists())


if __name__=="__main__":unittest.main()
