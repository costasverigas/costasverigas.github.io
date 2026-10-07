(() => {
  const root = document.getElementById('costas-dark-work');
  if (!root || !Array.isArray(window.COSTAS_PLAYLIST)) return;
  const group = root.querySelector('.cv-group');
  const track = root.querySelector('.cv-track');
  const items = window.COSTAS_PLAYLIST.filter(item => /^[A-Za-z0-9]{22}$/.test(item.track_id));
  if (!items.length) return;
  group.replaceChildren();
  for (const item of items) {
    const cover = document.createElement('div');
    cover.className = 'cv-cover';
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'cv-cover-choice';
    button.dataset.trackId = item.track_id;
    button.setAttribute('aria-label', 'Play ' + item.artist + ' — ' + item.title);
    button.setAttribute('aria-pressed', 'false');
    const image = document.createElement('img');
    image.src = item.image;
    image.alt = item.artist + ' — ' + item.title;
    image.width = image.height = 240;
    image.loading = 'lazy';
    const label = document.createElement('span');
    label.className = 'cv-cover-label';
    label.textContent = '▶ Play';
    button.append(image, label);
    const external = document.createElement('a');
    external.className = 'cv-cover-external';
    external.href = 'https://open.spotify.com/track/' + item.track_id;
    external.target = '_blank';
    external.rel = 'noopener noreferrer';
    external.textContent = 'Spotify ↗';
    external.setAttribute('aria-label', 'Open ' + item.artist + ' — ' + item.title + ' in Spotify');
    cover.append(button, external);
    group.append(cover);
  }
  track.querySelectorAll('.cv-group[aria-hidden]').forEach(copy => copy.remove());
  const duplicate = group.cloneNode(true);
  duplicate.setAttribute('aria-hidden', 'true');
  duplicate.querySelectorAll('button,a').forEach(control => control.tabIndex = -1);
  track.append(duplicate);
  track.style.animationDuration = Math.max(items.length * 5, 50) + 's';

  const pause = root.querySelector('#cv-pause');
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  function setPaused(value) {
    root.dataset.paused = String(value);
    pause.setAttribute('aria-pressed', String(value));
    pause.textContent = value ? 'Resume motion' : 'Pause motion';
  }
  function updateMotion() {
    setPaused(reduced.matches);
    pause.disabled = reduced.matches;
    if (reduced.matches) pause.textContent = 'Motion reduced';
  }
  pause.addEventListener('click', () => setPaused(root.dataset.paused !== 'true'));
  reduced.addEventListener('change', updateMotion);
  updateMotion();

  const mount = document.getElementById('cv-spotify-player');
  const selectedLabel = document.getElementById('cv-selected-track');
  const external = document.getElementById('cv-selected-external');
  const hint = document.getElementById('cv-player-hint');
  let selected = null;
  let controller = null;
  let controllerReady = false;
  let requestedApi = false;
  let api = null;

  function fallbackPlayer() {
    const frame = document.createElement('iframe');
    frame.src = 'https://open.spotify.com/embed/track/' + selected.track_id + '?theme=0';
    frame.title = 'Spotify player: ' + selected.artist + ' — ' + selected.title;
    frame.width = '100%';
    frame.height = '152';
    frame.allow = 'autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture';
    frame.setAttribute('allowfullscreen', '');
    mount.replaceChildren(frame);
  }
  function createPlayer() {
    if (!api || !selected || controller) return;
    mount.replaceChildren();
    api.createController(mount, {url: external.href, width: '100%', height: 152}, ctrl => {
      controller = ctrl;
      ctrl.addListener('ready', () => {
        controllerReady = true;
        ctrl.loadEntity(external.href);
        ctrl.play();
      });
      ctrl.addListener('playback_started', () => { hint.textContent = 'Playing on Spotify'; });
    });
  }
  window.onSpotifyIframeApiReady = value => { api = value; createPlayer(); };

  track.addEventListener('click', event => {
    const button = event.target.closest('button[data-track-id]');
    if (!button) return;
    selected = items.find(item => item.track_id === button.dataset.trackId);
    if (!selected) return;
    setPaused(true);
    if (reduced.matches) pause.textContent = 'Motion reduced';
    selectedLabel.textContent = selected.artist + ' — ' + selected.title;
    external.href = 'https://open.spotify.com/track/' + selected.track_id;
    external.textContent = 'Open in Spotify ↗';
    hint.textContent = 'If playback does not start, press Play in the player.';
    track.querySelectorAll('button[data-track-id]').forEach(control => {
      control.setAttribute('aria-pressed', String(control.dataset.trackId === selected.track_id));
    });
    if (controller && controllerReady) {
      controller.loadEntity(external.href);
      controller.play();
    } else if (!controller) {
      fallbackPlayer();
      if (api) createPlayer();
      else if (!requestedApi) {
        requestedApi = true;
        const script = document.createElement('script');
        script.src = 'https://open.spotify.com/embed/iframe-api/v1';
        script.async = true;
        script.onerror = () => { hint.textContent = 'Press Play in the player, or open the track in Spotify.'; };
        document.head.append(script);
      }
    }
  });
})();
