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
             patch.object(sync,'refresh_popularity',return_value={}), \
             patch.object(sync,'get_json',side_effect=pages) as request, \
             patch.object(sync,'fingerprint',return_value=(0,[])), \
             patch.object(sync,'visually_same',return_value=False):
            sync.main()
            data = json.loads((Path(directory)/'playlist-covers.json').read_text())
            self.assertEqual(len(data),125)
            self.assertEqual(request.call_count,3)
            self.assertEqual(data[0]['track_id'],f'{6:022}')

    def test_popularity_before_dedup_and_newest_ties(self):
        def row(i, album, date):
            return {'added_at': date, 'item': {'id': f'{i:022}', 'type': 'track',
                    'name': str(i), 'artists': [], 'album': {'id': album,
                    'images': [{'url': 'https://i.scdn.co/image/' + album}]}}}
        rows = [row(1, 'a', '2026-10-24'), row(2, 'a', '2026-01-01'),
                row(3, 'b', '2026-10-23'), row(4, 'c', '2026-10-24'),
                row(5, 'd', '2026-10-24'), row(6, 'e', '2026-10-24')]
        cache = {'tracks': {f'{1:022}': 5, f'{2:022}': 30, f'{3:022}': 20,
                            f'{4:022}': 20, f'{5:022}': 0}}
        result = sync.normalize(rows, cache)
        self.assertEqual([int(x['track_id']) for x in result], [2, 4, 3, 5, 6])
        self.assertNotIn('popularity', result[-1])

    def test_artwork_scores_ignore_image_size_and_missing_scores(self):
        image = 'https://i.scdn.co/image/ab67616d00004851342d383ed35828657442ead1'
        cache = sync.popularity_cache([
            {'track': {'spotifyId': '1'*22, 'popularity': 39}, 'album': {'avatarUrl': image}},
            {'track': {'spotifyId': '2'*22, 'popularity': None}},
            {'track': {'spotifyId': '3'*22, 'popularity': 0}}])
        track = {'id': '9'*22, 'album': {'images': [{'url': image.replace('00004851', '00001e02')}]}}
        self.assertEqual(sync.score_for(track, cache), 39)
        self.assertNotIn('2'*22, cache['tracks'])
        self.assertEqual(cache['tracks']['3'*22], 0)

    def test_muso_pages_and_failure_preserve_cache(self):
        pages = [{'result': 'ok', 'data': {'items': [{'track': {'spotifyId': '1'*22,
                  'popularity': 25}}], 'hasMoreToLoad': True, 'totalCount': 2}},
                 {'result': 'ok', 'data': {'items': [{'track': {'spotifyId': '2'*22,
                  'popularity': 0}}], 'hasMoreToLoad': False, 'totalCount': 2}}]
        with tempfile.TemporaryDirectory() as directory, patch.object(sync, 'ROOT', Path(directory)):
            with patch.object(sync, 'get_json', side_effect=pages) as request:
                cache = sync.refresh_popularity()
                self.assertEqual(len(cache['tracks']), 2)
                self.assertIn('offset=1', request.call_args.args[0])
            before = (Path(directory)/'portfolio-popularity.json').read_text()
            with patch.object(sync, 'get_json', side_effect=RuntimeError('unavailable')):
                self.assertEqual(sync.refresh_popularity(), cache)
            # A partially successful response must never replace the full cache.
            with patch.object(sync, 'get_json', side_effect=[pages[0], RuntimeError('unavailable')]):
                self.assertEqual(sync.refresh_popularity(), cache)
            self.assertEqual((Path(directory)/'portfolio-popularity.json').read_text(), before)

    def test_empty_response_keeps_previous_covers(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(sync,'ROOT',Path(directory)), \
             patch.dict(os.environ,{'SPOTIFY_CLIENT_ID':'test','SPOTIFY_REFRESH_TOKEN':'private'}), \
             patch.object(sync,'refresh',return_value='access'), \
             patch.object(sync,'refresh_popularity',return_value={}), \
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
