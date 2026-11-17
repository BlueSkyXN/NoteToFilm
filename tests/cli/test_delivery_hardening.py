"""Offline regression for stale settings, audio post and machine-readable checks."""
import contextlib
import copy
import io
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import types
import unittest
import wave
from unittest.mock import Mock, patch

from notetofilm_local.cli import main
from notetofilm_local.compose import compose
from notetofilm_local.errors import NTFError
from notetofilm_local.inspection import inspect_media
from notetofilm_local.io import atomic_json
from notetofilm_local.project import init_project
from notetofilm_local.runner import run
from notetofilm_local.workflow import action_request, make_plan, save_plan, status


class PlanFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.project=init_project(Path(self.tmp.name)/'project','Fixture')
        self.project.put_storyboard({'scenes':[{'id':'s1','narration':'Fixture speech','visual_type':'video',
            'video_mode':'text_to_video','visual_prompt':'Fixture'}]})
        save_plan(self.project,make_plan(self.project))
    def settings(self,*args):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['settings',str(self.project.root),*args]),0)
    def test_voice_change_stops_new_work_before_any_attempt(self):
        self.settings('--voice','zh-CN-YunxiNeural')
        self.assertEqual(status(self.project)['stale_action_ids'],['s1.audio'])
        with self.assertRaises(NTFError) as error:run(self.project,kind='audio')
        self.assertEqual(error.exception.code,'stale_plan')
        self.assertFalse(self.project.state['attempts'])
        save_plan(self.project,make_plan(self.project))
        action=next(a for a in self.project.plan['actions'] if a['kind']=='audio')
        self.assertEqual(action_request(self.project,action)['voice'],'zh-CN-YunxiNeural')
        self.assertTrue(status(self.project)['plan_current'])
    def test_output_change_only_stales_composition(self):
        self.settings('--width','640')
        self.assertEqual(status(self.project)['stale_action_ids'],['film.compose'])
    def test_old_remote_job_can_still_be_polled(self):
        adapter=types.SimpleNamespace(submit=Mock(return_value={'status':'submitted','job':{'remote_id':'fixture-job'}}),
            poll=Mock(side_effect=lambda job:{'status':'submitted','job':job}))
        with patch('notetofilm_local.config.resolve_route',return_value={'model':'fixture','adapter':'fixture','connection':{}}), patch('notetofilm_local.capabilities.check_request'), patch('notetofilm_local.adapters.get_adapter',return_value=adapter):
            run(self.project,kind='video',submit_only=True)
            self.settings('--video-route','changed-fixture-route')
            save_plan(self.project,make_plan(self.project))
            result=run(self.project,kind='video',poll_only=True)
        self.assertEqual(adapter.submit.call_count,1)
        self.assertEqual(adapter.poll.call_count,1)
        self.assertEqual(result['new_actions_started'],0)


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg required')
class AudioDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=blue:s=160x90','-frames:v','1','-y',str(self.root/'still.png')],check=True)
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=440:duration=1.2','-y',str(self.root/'tone.wav')],check=True)
        self.manifest={'output':{'width':160,'height':90,'fps':10},'scenes':[{'id':'silent','audio_policy':'silent',
            'duration_seconds':4,'visuals':[{'path':'still.png'}]}],
            'background_audio':{'path':'tone.wav','volume':.5,'start_seconds':1,'duration_seconds':2.5,
                'loop':True,'fade_in_seconds':.2,'fade_out_seconds':.5}}
    def rms(self,path,start,duration):
        raw=subprocess.run(['ffmpeg','-v','error','-ss',str(start),'-i',str(path),'-t',str(duration),'-vn','-ac','1','-ar','48000','-f','s16le','-'],capture_output=True,check=True).stdout
        values=struct.unpack('<'+'h'*(len(raw)//2),raw)
        return (sum(v*v for v in values)/len(values))**.5
    def test_background_start_loop_and_fade_leave_expected_silence(self):
        result=compose(self.root,self.manifest,self.root/'with-background')
        self.assertLess(self.rms(result['video_path'],.2,.2),5)
        self.assertGreater(self.rms(result['video_path'],1.5,.2),500)
        self.assertGreater(self.rms(result['video_path'],2.7,.2),500)
        self.assertLess(self.rms(result['video_path'],3.7,.2),5)
        self.assertAlmostEqual(result['duration_seconds'],4,delta=.05)
    def test_short_background_requires_explicit_loop(self):
        self.manifest['background_audio']['loop']=False
        with self.assertRaises(NTFError) as error:compose(self.root,self.manifest,self.root/'too-short',render=False)
        self.assertEqual(error.exception.code,'background_audio_short')
    def test_normalization_and_structured_media_acceptance(self):
        self.manifest['output'].update(audio_loudness_lufs=-20,audio_true_peak_db=-2)
        result=compose(self.root,self.manifest,self.root/'normalized')
        inspected=inspect_media(result['video_path'],decode=True,expected_width=160,expected_height=90,
            expected_fps=10,expected_duration=4,expect_audio=True,audio_check=True,
            expected_loudness_lufs=-20,loudness_tolerance=2)
        self.assertTrue(inspected['verification']['passed'])
        self.assertAlmostEqual(inspected['audio_loudness']['integrated_lufs'],-20,delta=2)
    def call_inspect(self,*args):
        stdout=io.StringIO()
        with contextlib.redirect_stdout(stdout):code=main(['inspect',*map(str,args)])
        return code,json.loads(stdout.getvalue())
    def test_failed_specs_and_silent_audio_return_nonzero(self):
        code,result=self.call_inspect(self.root/'still.png','--expect-width','320')
        self.assertEqual(code,2);self.assertFalse(result['verification']['passed'])
        silence=self.root/'silence.wav'
        with wave.open(str(silence),'wb') as f:
            f.setparams((1,2,48000,0,'NONE','not compressed'));f.writeframes(b'\0\0'*24000)
        code,result=self.call_inspect(silence,'--audio-check')
        self.assertEqual(code,2)
        self.assertTrue(any(c['name']=='mean_volume_dbfs' and not c['passed'] for c in result['verification']['checks']))
    def test_clipped_audio_returns_nonzero(self):
        clipped=self.root/'clipped.wav'
        with wave.open(str(clipped),'wb') as f:
            f.setparams((1,2,48000,0,'NONE','not compressed'));f.writeframes(struct.pack('<h',32767)*24000)
        code,result=self.call_inspect(clipped,'--audio-check')
        self.assertEqual(code,2)
        self.assertTrue(any(c['name']=='max_volume_dbfs' and not c['passed'] for c in result['verification']['checks']))

if __name__=='__main__':unittest.main()
