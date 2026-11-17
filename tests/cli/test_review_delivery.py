"""最终媒体、明确时间表和 CLI Range 服务的集成验证。"""
import hashlib
import http.client
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from urllib.parse import urlsplit

from notetofilm_local.errors import NTFError
from notetofilm_local.preview import export_preview
from notetofilm_local.project import init_project


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
class ReviewDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='ntf-final-preview-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.project=init_project(self.root/'project')
        self.project.put_storyboard({'scenes':[{'id':'a','narration':'First description'}, {'id':'b','narration':'Second description'}]})
        self.movie=self.root/'postprocessed.mp4'
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=red:s=160x90:r=10:d=2',
                        '-c:v','libx264','-pix_fmt','yuv420p',str(self.movie)],check=True,capture_output=True)
        self.timeline=self.root/'timeline.json'
        self.data={'duration_seconds':2,'scenes':[{'id':'b','start_seconds':0,'end_seconds':1},
                                                {'id':'a','start_seconds':1,'end_seconds':2}]}
        self.timeline.write_text(json.dumps(self.data))

    def test_final_file_timeline_order_and_launchable_server(self):
        result=export_preview(self.project,output=self.root/'review',video=self.movie,timeline_file=self.timeline)
        self.assertEqual([r['scene_id'] for r in result['scenes']],['b','a'])
        self.assertEqual([r['start_seconds'] for r in result['scenes']],[0,1])
        self.assertEqual((self.root/'review/movie.mp4').read_bytes(),self.movie.read_bytes())
        self.assertFalse((self.root/'review/state.json').exists())
        environment=dict(os.environ);environment.pop('PYTHONPATH',None)
        process=subprocess.Popen(result['serve_argv'],cwd=self.root,env=environment,
                                 stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            started=json.loads(process.stdout.readline());url=urlsplit(started['url'])
            self.assertEqual(url.hostname,'127.0.0.1')
            connection=http.client.HTTPConnection(url.hostname,url.port,timeout=5)
            connection.request('GET','/movie.mp4',headers={'Range':'bytes=10-99'})
            response=connection.getresponse()
            self.assertEqual(response.status,206)
            self.assertEqual(response.read(),self.movie.read_bytes()[10:100])
            connection.close()
        finally:
            process.terminate();process.communicate(timeout=5)

    def test_wrong_timeline_does_not_create_review_directory(self):
        for change in ('duration','ids','window'):
            with self.subTest(change=change):
                data=json.loads(json.dumps(self.data))
                if change=='duration':data['duration_seconds']=3
                elif change=='ids':data['scenes'][0]['id']='unknown'
                else:data['scenes'][1]['end_seconds']=3
                self.timeline.write_text(json.dumps(data))
                destination=self.root/f'bad-{change}'
                with self.assertRaises(NTFError):
                    export_preview(self.project,output=destination,video=self.movie,timeline_file=self.timeline)
                self.assertFalse(destination.exists())

    def test_existing_media_without_formal_storyboard_can_use_timeline(self):
        project=init_project(self.root/'assembly')
        result=export_preview(project,output=self.root/'assembly-review',video=self.movie,timeline_file=self.timeline)
        self.assertEqual([r['scene_id'] for r in result['scenes']],['b','a'])
        self.assertEqual(result['scene_count'],2)


if __name__=='__main__':unittest.main()
