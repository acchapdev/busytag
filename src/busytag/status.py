"""Agent status board: many agents report state, the device shows the most urgent.

There is no daemon. Each update takes an exclusive lock on the state file, records the
agent's state, and pushes to the device only when what should be on screen has changed.
The lock also serializes device access between concurrent hook processes.
"""

import fcntl
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path

from busytag import config as user_config
from busytag.colors import scale_color

# Lowest to highest urgency; the most urgent agent decides the LEDs and headline
STATES = ['idle', 'working', 'done', 'error', 'attention']
PRIORITY = {state: rank for rank, state in enumerate(STATES)}
STALE_SECONDS = 12 * 3600

# Two names because the device refuses to overwrite the image it is showing
STATUS_FILES = ['bt_status0.png', 'bt_status1.png']

ERROR_COLOR = 'FF0000'
WORKING_PERCENT = 25
PULSE_LOW_PERCENT = 12


def led_plan(top, agent_color, brightness):
  """LED look for the most urgent agent: its color says who, the effect says what.

  Returns ('solid', RRGGBB) or ('pattern', steps), already scaled to `brightness`.
  Pulse steps mirror the built-in "Red Pulses" timing (speed 150, delay 10).
  """
  if top == 'error':
    return 'solid', scale_color(ERROR_COLOR, brightness)
  if top == 'attention':
    low = scale_color(agent_color, PULSE_LOW_PERCENT)
    steps = [(127, agent_color, 150, 10), (127, low, 150, 10)]
    return 'pattern', [(leds, scale_color(color, brightness), speed, delay) for leds, color, speed, delay in steps]
  percent = WORKING_PERCENT if top == 'working' else 100
  return 'solid', scale_color(agent_color, percent * brightness / 100)


def state_dir():
  path = Path(os.environ.get('BUSYTAG_STATE_DIR', Path.home() / '.cache' / 'busytag'))
  path.mkdir(parents=True, exist_ok=True)
  return path


@contextmanager
def device_lock():
  """Hold the lock that hooks take, so a manual device command doesn't collide with a
  status push on the exclusive serial port."""
  with open(state_dir() / 'lock', 'w') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    yield


def read_state(path):
  try:
    state = json.loads(path.read_text())
  except (FileNotFoundError, json.JSONDecodeError):
    state = {}
  state.setdefault('agents', {})
  return state


def peek():
  """Read the state without the lock (writes replace the file atomically)."""
  return read_state(state_dir() / 'state.json')


@contextmanager
def locked_state():
  """Yield the state dict under an exclusive lock; it is saved on exit."""
  with device_lock():
    path = state_dir() / 'state.json'
    state = read_state(path)
    yield state
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(state, indent=2))
    temp.replace(path)


def drop_stale(state, now):
  agents = state['agents']
  for name in [name for name, entry in agents.items() if now - entry['updated'] > STALE_SECONDS]:
    del agents[name]


def apply_update(state, agent, new_state, label=None, detail=None, timestamp=None, now=None):
  """Record one agent's report. Returns False if it was older than what we have."""
  now = time.time() if now is None else now
  timestamp = now if timestamp is None else timestamp
  agents = state['agents']
  drop_stale(state, now)

  current = agents.get(agent)
  # Hooks run in the background, so a late process must not undo a newer report
  if current and current['updated'] > timestamp:
    return False
  if new_state == 'clear':
    agents.pop(agent, None)
    return True
  if new_state not in PRIORITY:
    raise ValueError(f"unknown state '{new_state}'; use one of {', '.join(STATES)} or clear")
  agents[agent] = {
    'state': new_state,
    'label': label or (current or {}).get('label') or agent,
    'detail': detail or '',
    'updated': timestamp,
  }
  return True


def summarize(agents, settings):
  """Return (top_state, rows), most urgent first.

  Each row is (label, state, detail, color), where color is the agent type's LED color.
  """
  active = [(agent, entry) for agent, entry in agents.items() if entry['state'] != 'idle']
  if not active:
    return 'idle', []
  active.sort(key=lambda item: (-PRIORITY[item[1]['state']], -item[1]['updated']))
  rows = [
    (entry['label'], entry['state'], entry['detail'], user_config.agent_color(settings, agent))
    for agent, entry in active
  ]
  return rows[0][1], rows


def screen_key(top, rows, brightness):
  # Brightness is part of the key so changing it re-pushes the LEDs
  return None if top == 'idle' else json.dumps([top, rows, brightness])


def needs_push(state, top, rows, brightness):
  if top == 'idle':
    # 'home' means a status screen may still be up ('drawn': ESP32 state from before 'home')
    return 'home' in state or 'drawn' in state
  return screen_key(top, rows, brightness) != state.get('shown_key')


def push(device, state, top, rows, brightness=100):
  """Make the device show `top`/`rows`, recording what is shown in `state`."""
  from busytag.render import render_status

  if getattr(device, 'draws_status', False):
    push_drawn(device, state, top, rows, brightness)
    return
  if top == 'idle':
    home = state.pop('home', None)
    if home:
      device.stop_pattern()
      if home.get('pattern'):
        device.set_custom_pattern(home['pattern'])
      device.show_image(home['image'])
      device.solid_color(home['color'])
    state.pop('shown_key', None)
    return

  if 'home' not in state:
    # Remember what the user had on screen so we can put it back when all agents finish
    color = device.query('AT+SC?').split(',')[1]
    image = device.current_image()
    # A leftover status screen (e.g. state file deleted) is not the user's own image
    state['home'] = {
      'image': 'def.png' if image in STATUS_FILES else image,
      'color': color,
      # The device has one pattern slot, and the attention pulse overwrites it
      'pattern': device.custom_pattern(),
    }

  # Ask the device rather than trusting state.json: if the state was reset while a status
  # screen is up, uploading to the file on screen would fail (ERROR:3) on every retry
  next_file = STATUS_FILES[1] if device.current_image() == STATUS_FILES[0] else STATUS_FILES[0]
  device.upload(next_file, render_status(top, rows))
  device.show_image(next_file)

  kind, value = led_plan(top, rows[0][3], brightness)
  if kind == 'solid':
    # AT+SC alone leaves AT+PP reporting the old pattern as playing
    device.stop_pattern()
    device.solid_color(value)
  else:
    device.set_custom_pattern(value)
    device.play_pattern(255)

  state['shown_file'] = next_file
  state['shown_key'] = screen_key(top, rows, brightness)


def push_drawn(device, state, top, rows, brightness):
  """Push to a display whose firmware draws the status screen (the ESP32)."""
  if top == 'idle':
    home = state.pop('home', None)
    if home and 'screen' in home:
      device.restore_screen(home)
    else:
      # No ESP32 home: state from before ESP32 home screens ('drawn'), or a Busy Tag's home
      device.show_idle()
    state.pop('drawn', None)
    state.pop('shown_key', None)
    return
  if 'home' not in state:
    # Remember the screen (idle, a fill color) and the LED to put back when all agents
    # finish. Saved before pushing, so a failed push is still restored later.
    home = device.current_screen()
    # A leftover status screen (e.g. state file deleted) is not the user's own screen
    if home['screen'].get('cmd') == 'status':
      home = {'screen': {'cmd': 'idle'}, 'led': {'effect': 'off'}}
    state['home'] = home
  kind, value = led_plan(top, rows[0][3], brightness)
  if kind == 'solid':
    led = {'effect': 'solid', 'color': value}
  else:
    # The attention pattern alternates full and low; the firmware fades between them
    led = {'effect': 'pulse', 'color': value[0][1], 'low': value[1][1]}
  device.show_status(top, rows, led)
  state['shown_key'] = screen_key(top, rows, brightness)


def refresh(state, open_device):
  """Push to the device if needed. Device problems are recorded, not raised, so the
  agent's report is still saved and the next update retries the screen."""
  from busytag.device import BusyTagError

  settings = user_config.load()
  brightness = settings['brightness']
  top, rows = summarize(state['agents'], settings)
  if not needs_push(state, top, rows, brightness):
    return
  try:
    with open_device() as device:
      push(device, state, top, rows, brightness)
    state.pop('last_error', None)
  except (BusyTagError, OSError) as error:
    state.pop('shown_key', None)
    state['last_error'] = f'{time.strftime("%Y-%m-%d %H:%M:%S")} {error}'


def default_device():
  from busytag.device import open_device
  return open_device()


def update(agent, new_state, label=None, detail=None, timestamp=None, open_device=default_device):
  """Record a report and refresh the device if the screen should change."""
  with locked_state() as state:
    if apply_update(state, agent, new_state, label, detail, timestamp):
      refresh(state, open_device)
    return state.get('last_error')


def reset(open_device=default_device):
  """Forget every agent and put the user's own image and LEDs back."""
  with locked_state() as state:
    state['agents'] = {}
    refresh(state, open_device)
    return state.get('last_error')


def redraw(open_device=default_device):
  """Push the current status even if it looks unchanged: a display that was just plugged
  in may show an old status (Busy Tag) or its boot screen (ESP32)."""
  with locked_state() as state:
    drop_stale(state, time.time())
    state.pop('shown_key', None)
    refresh(state, open_device)
    return state.get('last_error')


def remember_led_color(color):
  """Record the unscaled color of `busytag led color`, so a brightness change can redo it."""
  with locked_state() as state:
    state['manual_color'] = color


def apply_brightness(open_device=default_device):
  """Re-send the LEDs at the configured brightness.

  With agents active the status LEDs are redrawn (brightness is part of the screen
  key); otherwise the last `busytag led color` is re-sent. Returns (what, error).
  """
  with locked_state() as state:
    top, _ = summarize(state['agents'], user_config.load())
    if top != 'idle':
      refresh(state, open_device)
      return 'status', state.get('last_error')
    color = state.get('manual_color')
    if not color:
      return None, None
  from busytag.device import BusyTagError
  try:
    with open_device() as device:
      device.solid_color(scale_color(color, user_config.load()['brightness']))
  except (BusyTagError, OSError) as error:
    return 'color', str(error)
  return 'color', None


def agents():
  """Return ([(agent, entry)] most urgent first, last device error)."""
  with locked_state() as state:
    entries = sorted(
      state['agents'].items(),
      key=lambda item: (-PRIORITY[item[1]['state']], -item[1]['updated']),
    )
    return entries, state.get('last_error')
