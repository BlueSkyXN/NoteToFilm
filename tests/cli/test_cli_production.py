"""Controlled CLI production, external credentials and no-resubmit boundaries."""
import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from notetofilm_local.cli import main
from notetofilm_local.config import connection_environment
from notetofilm_local.errors import NTFError
from notetofilm_local.io import atomic_json
from notetofilm_local.project import init_project
from notetofilm_local.runner import run
from notetofilm_local.workflow import save_plan

class ControlledRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.project=init_project(self.root/'p','Fixture')
        self.posts=self.polls=0;owner=self
        class Adapter:
            def submit(self,request,root):
                owner.posts+=1
                if getattr(owner,'fail_submission',False):raise NTFError('submission_unknown','Fixture uncertain submission')
                return {'status':'submitted','job':{'task_id':str(owner.posts),'kind':request['kind']}}
            def poll(self,job):
                owner.polls+=1
                return {'status':'succeeded','job':job}
            def fetch(self,result,directory):
                kind=result['job']['kind'];path=directory/('fixture.mp4' if kind=='video' else 'fixture.png');path.write_bytes(b'fixture')
                return [{'kind':kind,'path':str(path)}]
        for target,kwargs in [
            ('notetofilm_local.adapters.get_adapter',{'return_value':Adapter()}),
            ('notetofilm_local.config.resolve_route',{'return_value':{'model':'fixture','adapter':'fixture','connection':{}}}),
            ('notetofilm_local.capabilities.check_request',{}),
            ('notetofilm_local.media.probe',{'side_effect':lambda p:{'kind':'video' if str(p).endswith('.mp4') else 'image','duration_seconds':1,'width':160,'height':90}})]:
            patcher=patch(target,**kwargs);patcher.start();self.addCleanup(patcher.stop)
        save_plan(self.project,{'actions':[{'id':f'{sid}.{kind}','scene_id':sid,'kind':kind,'needs':[],
            'request':{'mode':'text_to_video' if kind=='video' else 'text_to_image','prompt':'Fixture'},
            'selection_slot':f'{sid}.{kind}'} for sid,kind in [('a','video'),('b','image'),('c','video')]]})
    def test_submit_limit_kind_and_poll_never_create_new_attempts(self):
        result=run(self.project,kind='video',submit_only=True,max_new_actions=1)
        self.assertEqual(self.posts,1);self.assertEqual(result['new_actions_started'],1)
        self.assertEqual(self.project.state['actions']['b.image']['status'],'pending')
        count=len(self.project.state['attempts']);result=run(self.project,kind='video',poll_only=True)
        self.assertEqual(self.posts,1);self.assertEqual(self.polls,1)
        self.assertEqual(len(self.project.state['attempts']),count)
        self.assertEqual(self.project.state['actions']['c.video']['status'],'pending')
        self.assertEqual(result['new_actions_started'],0)
    def test_fixed_scene_scope_and_stop_after_uncertain_submission(self):
        self.fail_submission=True;result=run(self.project,scene_ids=['a','c'],stop_on_error=True)
        self.assertEqual(self.posts,1);self.assertTrue(result['stopped_on_error'])
        self.assertEqual(self.project.state['actions']['c.video']['status'],'pending')
        with self.assertRaises(NTFError):run(self.project,poll_only=True,retry=True)

class ExternalConnectionTests(unittest.TestCase):
    def test_external_values_are_ephemeral_and_never_change_models_or_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'external.private.json'
            atomic_json(p,{'connections':{'fixture':{'base_url':'https://gateway.invalid/prefix','credentials':{'api_key':'LOCAL_FIXTURE_CREDENTIAL'}}}})
            config={'connections':{'fixture':{'base_url_env':'NTF_FIXTURE_BASE','auth':{'type':'bearer','env':'NTF_FIXTURE_KEY'}}},'routes':{'r':{'model':'unchanged-fixture'}}}
            before=copy.deepcopy(config);digest=hashlib.sha256(p.read_bytes()).hexdigest()
            with patch.dict(os.environ,{'NTF_FIXTURE_KEY':'original'}):
                with connection_environment(config,p) as bound:
                    self.assertEqual(os.environ['NTF_FIXTURE_KEY'],'LOCAL_FIXTURE_CREDENTIAL')
                    self.assertEqual(bound['connections']['fixture']['base_url'],'https://gateway.invalid/prefix')
                    self.assertNotIn('LOCAL_FIXTURE_CREDENTIAL',json.dumps(bound))
                    self.assertEqual(bound['routes'],before['routes'])
                self.assertEqual(os.environ['NTF_FIXTURE_KEY'],'original')
            self.assertEqual(config,before);self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),digest)

@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg required')
class ProductionCLITests(unittest.TestCase):
    def call(self,*args):
        stdout,stderr=io.StringIO(),io.StringIO()
        with contextlib.redirect_stdout(stdout),contextlib.redirect_stderr(stderr):code=main(list(map(str,args)))
        self.assertEqual(code,0,stderr.getvalue()+stdout.getvalue())
        return json.loads(stdout.getvalue())
    def test_real_video_metadata_is_not_an_explicit_edit_duration(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);project=base/'p';video=base/'source.mp4'
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=blue:s=160x90:r=24',
                '-frames:v','25','-an','-c:v','libx264','-y',str(video)],check=True)
            self.call('init',project)
            self.call('settings',project,'--width','160','--height','90','--fps','24')
            asset=self.call('import',project,video)
            self.assertGreater(asset['metadata']['duration_seconds'],1)
            board=base/'board.json'
            atomic_json(board,{'scenes':[{'id':'clip','duration_seconds':1,'audio_policy':'silent',
                'visuals':[{'asset_id':asset['id']}]}]})
            self.call('storyboard',project,'--file',board);self.call('plan',project)
            result=self.call('run',project,'--kind','compose')
            self.assertTrue(result['complete'])
            rendered=list(result['renders'].values())[-1]
            self.assertAlmostEqual(rendered['duration_seconds'],1,delta=.05)
    def test_real_cli_import_timing_plan_run_inspect_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);project=base/'project';self.call('init',project,'--title','OFFLINE CLI fixture')
            tone=base/'tone.wav';image=base/'still.png'
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=440:duration=1.2','-y',str(tone)],check=True)
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=blue:s=160x90','-frames:v','1','-y',str(image)],check=True)
            a=self.call('import',project,tone);v=self.call('import',project,image);board=base/'board.json'
            atomic_json(board,{'scenes':[{'id':'s07','narration':'Offline fixture','duration_seconds':2,'audio_policy':'edge_tts',
                'audio':{'asset_id':a['id']},'visuals':[{'asset_id':v['id']}]}]})
            self.call('storyboard',project,'--file',board)
            estimate=self.call('timing',project,'--mode','estimate');self.assertFalse(estimate['scenes'][0]['measured'])
            self.call('timing',project,'--apply','--lead-seconds','.2','--tail-seconds','.6','--min-seconds','2','--max-seconds','15')
            original=(project/'storyboard.json').read_bytes()
            from notetofilm_local.timing import narration_timing
            from notetofilm_local.project import Project
            with self.assertRaises(NTFError):narration_timing(Project(project),apply=True,max_seconds=1)
            self.assertEqual((project/'storyboard.json').read_bytes(),original)
            self.call('plan',project)
            result=self.call('run',project,'--kind','compose','--max-new-actions','1','--stop-on-error');self.assertTrue(result['complete'])
            state=json.loads((project/'state.json').read_text());render=list(state['renders'].values())[-1];final=project/render['video_path']
            checked=self.call('inspect',final,'--decode','--frames','3','--output',base/'frames','--max-width','320')
            self.assertEqual(checked['full_decode'],'passed');self.assertEqual(len(checked['previews']),3)
            (project/'do-not-export.private.json').write_text('LOCAL_ONLY_FIXTURE')
            exported=self.call('preview',project,'--output',base/'preview','--max-width','320')
            self.assertEqual(exported['scene_count'],1);self.assertTrue((base/'preview/movie.mp4').is_file())
            for path in (base/'preview').rglob('*'):
                if path.is_file() and path.suffix in ('.html','.json'):
                    content=path.read_text();self.assertNotIn('LOCAL_ONLY_FIXTURE',content);self.assertNotIn(str(project),content)
            self.assertEqual([r['scene_id'] for r in exported['scenes']],['s07'])

if __name__=='__main__':unittest.main()
