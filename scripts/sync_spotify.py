"""Read the owner's playlist with PKCE OAuth and publish unique cover metadata."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from PIL import Image

PLAYLIST = '678SGbiRp7tvQMNKfcauMO'
ROOT = Path(__file__).resolve().parents[1]
VAULT = ROOT / 'spotify-refresh.enc.json'


def get_json(url, token=None, form=None):
    headers = {'Accept': 'application/json'}
    if token:
        if urllib.parse.urlsplit(url).netloc != 'api.spotify.com':
            raise RuntimeError('Unexpected Spotify pagination host.')
        headers['Authorization'] = 'Bearer ' + token
    data = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        # Never print bodies or exception representations: they may include credentials.
        raise RuntimeError('Spotify request failed: HTTP ' + str(error.code)) from None


def fingerprint(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname not in ('i.scdn.co', 'image-cdn-fa.spotifycdn.com', 'image-cdn-ak.spotifycdn.com'):
        raise RuntimeError('Unexpected album image host.')
    with urllib.request.urlopen(url, timeout=30) as response:
        body = response.read(5 * 1024 * 1024 + 1)
    if len(body) > 5 * 1024 * 1024:
        raise RuntimeError('Album image exceeded size limit.')
    image = Image.open(io.BytesIO(body)).convert('RGB')
    gray = list(image.convert('L').resize((9, 8)).getdata())
    difference = sum((gray[y * 9 + x] > gray[y * 9 + x + 1]) << (y * 8 + x)
                     for y in range(8) for x in range(8))
    return difference, list(image.resize((16, 16)).getdata())


def visually_same(left, right):
    if (left[0] ^ right[0]).bit_count() > 5:
        return False
    error = sum(abs(a - b) for pixel, old in zip(left[1], right[1])
                for a, b in zip(pixel, old)) / (256 * 3)
    return error < 12


def normalize(rows):
    items, albums, images = [], set(), set()
    # New additions appear at the start, including songs appended to the playlist.
    for row in sorted(rows, key=lambda value: value.get('added_at') or '', reverse=True):
        track = row.get('item') or row.get('track')
        if not track or row.get('is_local') or track.get('type') != 'track':
            continue
        track_id = track.get('id') or ''
        if not re.fullmatch(r'[A-Za-z0-9]{22}', track_id):
            continue
        album = track.get('album') or {}
        available = album.get('images') or []
        if not available:
            continue
        image = min(available, key=lambda entry: abs((entry.get('width') or 300) - 300))['url']
        album_id = album.get('id')
        if (album_id and album_id in albums) or image in images:
            continue
        if album_id:
            albums.add(album_id)
        images.add(image)
        items.append({'track_id': track_id, 'title': track.get('name') or 'Untitled',
                      'artist': ', '.join(artist['name'] for artist in track.get('artists', [])),
                      'image': image, 'url': 'https://open.spotify.com/track/' + track_id})
    return items


def refresh(client_id, initial):
    # PKCE can rotate refresh tokens. Persist only authenticated ciphertext in Git.
    key = hashlib.sha256(b'costas-spotify-refresh-v1:' + initial.encode()).digest()
    key_id = hashlib.sha256(key).hexdigest()[:16]
    current = initial
    if VAULT.exists():
        vault = json.loads(VAULT.read_text())
        if vault.get('key_id') == key_id:
            encrypted = base64.b64decode(vault['ciphertext'])
            current = AESGCM(key).decrypt(encrypted[:12], encrypted[12:], client_id.encode()).decode()
    result = get_json('https://accounts.spotify.com/api/token', form={
        'grant_type': 'refresh_token', 'refresh_token': current, 'client_id': client_id})
    access = result.get('access_token')
    if not access:
        raise RuntimeError('Spotify did not return an access token.')
    rotated = result.get('refresh_token')
    if rotated and rotated != current:
        nonce = os.urandom(12)
        ciphertext = nonce + AESGCM(key).encrypt(nonce, rotated.encode(), client_id.encode())
        VAULT.write_text(json.dumps({'key_id': key_id, 'ciphertext': base64.b64encode(ciphertext).decode()}) + '\n')
    return access


def main():
    client_id = os.environ.get('SPOTIFY_CLIENT_ID', '').strip()
    initial = os.environ.get('SPOTIFY_REFRESH_TOKEN', '').strip()
    if not client_id or not initial:
        raise RuntimeError('Setup needed: add SPOTIFY_CLIENT_ID and SPOTIFY_REFRESH_TOKEN to GitHub Actions secrets.')
    access = refresh(client_id, initial)
    url = f'https://api.spotify.com/v1/playlists/{PLAYLIST}/items?limit=50'
    rows, visited = [], set()
    while url:
        if url in visited:
            raise RuntimeError('Repeated pagination URL.')
        visited.add(url)
        page = get_json(url, token=access)
        rows.extend(page['items'])
        url = page.get('next')
    unique, fingerprints = [], []
    for item in normalize(rows):
        value = fingerprint(item['image'])
        if any(visually_same(value, old) for old in fingerprints):
            continue
        fingerprints.append(value)
        unique.append(item)
    if not unique:
        raise RuntimeError('No usable covers returned. Existing portfolio was preserved.')
    serialized = json.dumps(unique, ensure_ascii=False, indent=2)
    # Escape '<' as defense in depth for the JavaScript data file.
    script = 'window.COSTAS_PLAYLIST = ' + serialized.replace('<', '\\u003c') + ';\n'
    (ROOT / 'playlist-covers.json').write_text(serialized + '\n')
    (ROOT / 'playlist-covers.js').write_text(script)
    print(f'Playlist read: {len(rows)} items; {len(unique)} visually distinct covers published.')


if __name__ == '__main__':
    try:
        main()
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
    except Exception:
        print('Sync failed safely; existing covers retained. No credentials logged.', file=sys.stderr)
        sys.exit(1)
