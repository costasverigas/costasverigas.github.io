import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('sync_spotify', Path(__file__).resolve().parents[1] / 'scripts/sync_spotify.py')
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


class SpotifySyncTests(unittest.TestCase):
    def test_all_pages_and_newest_first(self):
        rows = [{'added_at':f'2026-10-{1+i%7:02}', 'item':{
            'id':f'{i:022}', 'type':'track', 'name':str(i), 'artists':[{'name':'Artist'}],
            'album':{'id':str(i), 'images':[{'url':f'https://i.scdn.co/image/{i}', 'width':300}]}}}
            for i in range(125)]
        pages = [{'items':rows[:50], 'next':'https://api.spotify.com/page2'},
                 {'items':rows[50:100], 'next':'https://api.spotify.com/page3'},
                 {'items':rows[100:], 'next':None}]
        with tempfile.TemporaryDirectory() as directory, patch.object(sync,'ROOT',Path(directory)), \
             patch.dict(os.environ,{'SPOTIFY_CLIENT_ID':'test','SPOTIFY_REFRESH_TOKEN':'private'}), \
             patch.object(sync,'refresh',return_value='access'), \
             patch.object(sync,'get_json',side_effect=pages) as request, \
             patch.object(sync,'fingerprint',return_value=(0,[])), \
             patch.object(sync,'visually_same',return_value=False):
            sync.main()
            data = json.loads((Path(directory)/'playlist-covers.json').read_text())
            self.assertEqual(len(data),125)
            self.assertEqual(request.call_count,3)
            self.assertEqual(data[0]['track_id'],f'{6:022}')

    def test_empty_response_keeps_previous_covers(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(sync,'ROOT',Path(directory)), \
             patch.dict(os.environ,{'SPOTIFY_CLIENT_ID':'test','SPOTIFY_REFRESH_TOKEN':'private'}), \
             patch.object(sync,'refresh',return_value='access'), \
             patch.object(sync,'get_json',return_value={'items':[], 'next':None}):
            previous = Path(directory)/'playlist-covers.js'
            previous.write_text('previous valid data')
            with self.assertRaises(RuntimeError):
                sync.main()
            self.assertEqual(previous.read_text(),'previous valid data')

    def test_token_rotation_is_encrypted_and_reused(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(sync,'VAULT',Path(directory)/'vault.json'), \
             patch.object(sync,'get_json',side_effect=[{'access_token':'access', 'refresh_token':'rotated-private'},
                                                       {'access_token':'next-access'}]) as request:
            self.assertEqual(sync.refresh('client','initial-private'),'access')
            self.assertNotIn('rotated-private',sync.VAULT.read_text())
            self.assertNotIn('initial-private',sync.VAULT.read_text())
            self.assertEqual(sync.refresh('client','initial-private'),'next-access')
            self.assertEqual(request.call_args.kwargs['form']['refresh_token'],'rotated-private')

    def test_visual_duplicates_require_both_shape_and_color(self):
        black = (0,[(0,0,0)]*256)
        white = (0,[(255,255,255)]*256)
        self.assertTrue(sync.visually_same(black,black))
        self.assertFalse(sync.visually_same(black,white))


if __name__ == '__main__':
    unittest.main()
