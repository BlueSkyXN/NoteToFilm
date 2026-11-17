"""动效的像素、时间、素材采用和重复运行检查。"""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from notetofilm_local.errors import NTFError
from notetofilm_local.media import probe
from notetofilm_local.motion import motion_project, plan_motion
from notetofilm_local.motion_render import Image, ImageDraw, MotionFrames
from notetofilm_local.project import init_project


@unittest.skipUnless(Image and shutil.which('ffmpeg') and shutil.which('ffprobe'), 'Pillow and FFmpeg required')
class MotionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ntf-motion-')
        self.addCleanup(self.temp.cleanup)
        self.project = init_project(Path(self.temp.name)/'project')
        self.source = self.project.root/'assets/base.png'
        Image.new('RGB',(160,90),'white').save(self.source)
        self.manifest = {'output':{'width':160,'height':90,'fps':10},'scenes':[{
            'id':'s1','duration_seconds':1,'background':'white','layers':[
                {'type':'image','path':'assets/base.png','rect':[0,0,160,90]},
                {'type':'draw','objects':[{'type':'rect','box':[0,40,20,60],'fill':'red'}],
                 'keyframes':[{'t':0,'offset':[0,0]},{'t':1,'offset':[100,0],'ease':'linear'}]},
                {'type':'draw','objects':[{'type':'rect','box':[60,10,110,30],'fill':'blue'}],
                 'reveal':{'start':.2,'end':.8,'box':[60,10,110,30],'direction':'right','ease':'linear'}},
                {'type':'draw','objects':[{'type':'line','points':[[10,75],[150,75]],'fill':'black','width':3,
                                         'reveal_start':0,'reveal_end':1}]}]}]}

    def test_keyframes_mask_and_path_have_expected_pixels(self):
        plan = plan_motion(self.project,self.manifest)
        frames = MotionFrames(plan['scenes'][0],plan['settings'])
        try:
            early, mid, late = [frames.frame(t) for t in (.25,.5,.9)]
            self.assertEqual(early.getpixel((35,50))[:3],(255,0,0))
            self.assertEqual(mid.getpixel((60,50))[:3],(255,0,0))
            self.assertEqual(mid.getpixel((10,50))[:3],(255,255,255))
            self.assertEqual(mid.getpixel((70,20))[:3],(0,0,255))
            self.assertEqual(mid.getpixel((100,20))[:3],(255,255,255))
            self.assertEqual(late.getpixel((100,20))[:3],(0,0,255))
            self.assertEqual(early.getpixel((35,75))[:3],(0,0,0))
            self.assertEqual(early.getpixel((100,75))[:3],(255,255,255))
            self.assertEqual(late.getpixel((100,75))[:3],(0,0,0))
        finally: frames.close()

    def test_crop_rect_and_opacity_interpolate_without_random_motion(self):
        image=Image.new('RGB',(160,90),'red')
        ImageDraw.Draw(image).rectangle((80,0,159,89),fill='blue')
        image.save(self.source)
        self.manifest['scenes'][0]['layers']=[{'type':'image','path':'assets/base.png','rect':[0,0,80,90],
            'keyframes':[{'t':0,'crop':[0,0,80,90],'opacity':.5},
                         {'t':1,'crop':[80,0,160,90],'opacity':1,'rect':[80,0,80,90],'ease':'linear'}]}]
        plan=plan_motion(self.project,self.manifest);frames=MotionFrames(plan['scenes'][0],plan['settings'])
        try:
            first,last=frames.frame(0),frames.frame(.9)
            self.assertEqual(first.getpixel((40,45))[:3],(255,127,127))
            self.assertGreater(last.getpixel((112,45))[2],240)
            self.assertLess(last.getpixel((112,45))[0],30)
            self.assertEqual(last.tobytes(),frames.frame(.9).tobytes())
        finally:frames.close()

    def test_render_register_reuse_and_force_preserve_sources(self):
        source_hash=hashlib.sha256(self.source.read_bytes()).hexdigest()
        first=motion_project(self.project,self.manifest)
        row=first['scenes'][0];asset=self.project.state['assets'][row['asset_id']]
        self.assertEqual(self.project.state['selection']['motion.s1'],row['asset_id'])
        info=probe(self.project.path(asset['path']))
        self.assertEqual((info['width'],info['height'],info['fps']),(160,90,10))
        self.assertAlmostEqual(info['duration_seconds'],1,delta=.05)
        self.assertFalse(info['has_audio'])
        second=motion_project(self.project,self.manifest)
        self.assertEqual(second['scenes'][0]['status'],'reused')
        self.assertEqual(second['scenes'][0]['asset_id'],row['asset_id'])
        third=motion_project(self.project,self.manifest,force=True)
        self.assertNotEqual(third['scenes'][0]['asset_id'],row['asset_id'])
        self.assertTrue(self.project.path(asset['path']).is_file())
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(),source_hash)

    def test_plan_and_jpeg_preview_do_not_adopt_assets(self):
        before=self.project.state
        result=motion_project(self.project,self.manifest,plan_only=True)
        self.assertEqual(result['status'],'planned')
        self.assertEqual(self.project.state,before)
        result=motion_project(self.project,self.manifest,preview_only=True,preview_time=.5)
        self.assertEqual(self.project.state,before)
        path=self.project.path(result['scenes'][0]['preview_path'])
        with Image.open(path) as image:
            self.assertEqual(image.format,'JPEG');self.assertLessEqual(max(image.size),960)

    def test_picture_and_annotation_stages_reuse_clean_picture(self):
        picture=motion_project(self.project,self.manifest,stage='picture')
        pid=picture['scenes'][0]['asset_id']
        annotated=motion_project(self.project,self.manifest,stage='annotate')
        self.assertNotEqual(annotated['scenes'][0]['asset_id'],pid)
        self.manifest['scenes'][0]['layers'][1]['objects'][0]['fill']='green'
        again=motion_project(self.project,self.manifest,stage='picture')
        self.assertEqual(again['scenes'][0]['asset_id'],pid)
        self.assertEqual(again['scenes'][0]['status'],'reused')

    def test_video_layer_speed_uses_ffmpeg_and_outputs_silent_video(self):
        path=self.project.root/'assets/clip.mp4'
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=red:s=160x90:r=10:d=1',
                        '-f','lavfi','-i','color=c=blue:s=160x90:r=10:d=1','-filter_complex',
                        '[0:v][1:v]concat=n=2:v=1:a=0[v]','-map','[v]','-c:v','libx264',str(path)],
                       check=True,capture_output=True)
        self.manifest['scenes'][0]['layers']=[{'type':'video','path':'assets/clip.mp4','speed':2}]
        plan=plan_motion(self.project,self.manifest)
        frames=MotionFrames(plan['scenes'][0],plan['settings'])
        try:
            red,blue=frames.frame(.2).getpixel((80,45)),frames.frame(.7).getpixel((80,45))
            self.assertGreater(red[0],200);self.assertLess(red[2],30)
            self.assertGreater(blue[2],200);self.assertLess(blue[0],30)
        finally:frames.close()
        result=motion_project(self.project,self.manifest)
        self.assertFalse(probe(self.project.path(result['scenes'][0]['path']))['has_audio'])

    def test_invalid_parameters_fail_before_registering_any_scene(self):
        bad=copy.deepcopy(self.manifest['scenes'][0]);bad['id']='bad'
        bad['layers'][1]['keyframes'][1]['t']=-1
        self.manifest['scenes'].append(bad)
        before=self.project.state
        with self.assertRaises(NTFError):motion_project(self.project,self.manifest)
        self.assertEqual(self.project.state,before)
        result=motion_project(self.project,self.manifest,scene_ids=['s1'],plan_only=True)
        self.assertEqual(len(result['scenes']),1)
        with self.assertRaises(NTFError):motion_project(self.project,self.manifest,scene_ids=['missing'])


if __name__=='__main__':unittest.main()
