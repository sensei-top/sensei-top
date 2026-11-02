// The hero's video. The labels are in the page, in its language, on data
// attributes. Without this file the page still works: poster, native controls,
// and chapters that are links to the feature rows.

const stage = document.querySelector('.stage')
const frame = stage.querySelector('.frame')
const video = stage.querySelector('video')
const playButton = stage.querySelector('.play')
const captionsButton = stage.querySelector('.captions')
const links = [...stage.querySelectorAll('.chapters a')]
const starts = links.map((link) => Number(link.dataset.start))
const captions = video.textTracks[0]

function label(button, text) {
  button.setAttribute('aria-label', text)
  button.title = text
}

function syncPlaying() {
  frame.classList.toggle('playing', !video.paused)
  if (!video.paused) frame.classList.remove('idle')
  label(playButton, video.paused ? playButton.dataset.play : playButton.dataset.pause)
}

function syncChapter() {
  const index = starts.filter((start) => start <= video.currentTime).length - 1
  links.forEach((link, i) => {
    if (i === index) link.setAttribute('aria-current', 'true')
    else link.removeAttribute('aria-current')
  })
  const end = starts[index + 1] ?? video.duration
  const share = (video.currentTime - starts[index]) / (end - starts[index])
  stage.style.setProperty('--progress', Math.min(share, 1) || 0)
}

// `preload="none"` holds the download back until here; a refused play stays on the poster.
function start() {
  video.preload = 'auto'
  video.play().catch(() => {})
}

function toggle() {
  if (video.paused) start()
  else video.pause()
}

// Before the metadata a seek has nothing to land on, so it waits for it.
function seek(time) {
  if (video.readyState > 0) video.currentTime = time
  else video.addEventListener('loadedmetadata', () => { video.currentTime = time }, { once: true })
}

video.removeAttribute('controls')
stage.querySelector('.ctl').hidden = false
frame.classList.add('idle')
video.addEventListener('play', syncPlaying)
video.addEventListener('pause', syncPlaying)
video.addEventListener('timeupdate', syncChapter)
video.addEventListener('click', toggle)
playButton.addEventListener('click', toggle)

// A full-width cue runs under the buttons; a narrower box wraps it short of them.
stage.querySelector('track').addEventListener('load', () => {
  for (const cue of captions.cues) cue.size = 70
})

captionsButton.addEventListener('click', () => {
  const show = captions.mode !== 'showing'
  captions.mode = show ? 'showing' : 'disabled'
  captionsButton.toggleAttribute('data-on', show)
  label(captionsButton, show ? captionsButton.dataset.hide : captionsButton.dataset.show)
})

links.forEach((link, i) => {
  link.addEventListener('click', (event) => {
    event.preventDefault()
    seek(starts[i])
    // Pressing a chapter on the poster is asking to watch; a paused video stays paused.
    if (frame.classList.contains('idle')) start()
  })
})

syncPlaying()
syncChapter()

const motionAllowed = matchMedia('(prefers-reduced-motion: no-preference)').matches
const wideEnough = matchMedia('(min-width: 700px)').matches
if (motionAllowed && wideEnough && !navigator.connection?.saveData) start()
