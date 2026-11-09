"""`busytag tui`: a live dashboard of agents, with device controls.

The agent table is read from state.json every second without the lock, so the screen
never waits on a status push. Device commands run in worker threads under the same lock
the hooks use, because the serial port is exclusive.
"""

import time

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Header, Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from busytag import config, status as board
from busytag.colors import parse_color, scale_color
from busytag.device import BusyTagError

STATE_STYLES = {
  'attention': 'bold magenta',
  'error': 'bold red',
  'done': 'green',
  'working': 'yellow',
  'idle': 'dim',
}


def age(seconds):
  seconds = int(seconds)
  if seconds < 60:
    return f'{seconds}s'
  if seconds < 3600:
    return f'{seconds // 60}m'
  return f'{seconds // 3600}h{seconds % 3600 // 60:02d}m'


class PickScreen(ModalScreen):
  """Choose one item from a list; dismisses with its id, or None on Escape."""

  BINDINGS = [Binding('escape', 'dismiss', 'Cancel')]

  def __init__(self, title, items):
    super().__init__()
    self.title_text = title
    self.items = items

  def compose(self) -> ComposeResult:
    with Vertical(classes='dialog'):
      yield Label(self.title_text)
      yield OptionList(*[Option(text, id=str(item_id)) for item_id, text in self.items])

  @on(OptionList.OptionSelected)
  def picked(self, event):
    self.dismiss(event.option.id)


class AskScreen(ModalScreen):
  """Ask for one line of text; dismisses with it, or None on Escape."""

  BINDINGS = [Binding('escape', 'dismiss', 'Cancel')]

  def __init__(self, title, placeholder=''):
    super().__init__()
    self.title_text = title
    self.placeholder = placeholder

  def compose(self) -> ComposeResult:
    with Vertical(classes='dialog'):
      yield Label(self.title_text)
      yield Input(placeholder=self.placeholder)

  @on(Input.Submitted)
  def submitted(self, event):
    self.dismiss(event.value.strip() or None)


class BusyTagApp(App):
  TITLE = 'busytag'
  ENABLE_COMMAND_PALETTE = False
  CSS = """
  #device { height: auto; padding: 0 1; border: round $primary; }
  #agents { height: 1fr; border: round $primary; }
  .dialog { width: 60; height: auto; max-height: 80%; padding: 1 2;
            border: thick $primary; background: $surface; }
  PickScreen, AskScreen { align: center middle; }
  OptionList { height: auto; max-height: 20; }
  """
  BINDINGS = [
    Binding('x', 'clear_agent', 'Clear agent'),
    Binding('R', 'reset', 'Clear all'),
    Binding('i', 'image', 'Image'),
    Binding('f', 'fill', 'Fill'),
    Binding('c', 'led_color', 'LED color'),
    Binding('p', 'pattern', 'Pattern'),
    Binding('o', 'led_off', 'LEDs off'),
    # Listed in the Display panel instead; the footer has no room for them
    Binding('left_square_bracket', 'display_brightness(-10)', 'Screen -', show=False),
    Binding('right_square_bracket', 'display_brightness(10)', 'Screen +', show=False),
    Binding('minus', 'led_brightness(-10)', 'LED -', show=False),
    Binding('plus,equals_sign', 'led_brightness(10)', 'LED +', show=False),
    Binding('d', 'device_info', 'Refresh'),
    Binding('q', 'quit', 'Quit'),
  ]

  def __init__(self, open_device=board.default_device, read_state=board.peek, poll=1.0):
    super().__init__()
    self.open_device = open_device
    self.read_state = read_state
    self.poll = poll
    self.device_text = 'Looking for a display...'
    self.last_error = None

  def compose(self) -> ComposeResult:
    # Kept as attributes: query_one searches the active screen, which may be a dialog
    self.device_panel = Static(self.device_text, id='device')
    self.table = DataTable(id='agents', cursor_type='row', zebra_stripes=True)
    yield Header()
    yield self.device_panel
    yield self.table
    yield Footer()

  def on_mount(self):
    table = self.table
    table.border_title = 'Agents'
    self.device_panel.border_title = 'Display'
    table.add_columns('State', 'Agent', 'Last report', 'Detail', 'ID')
    self.refresh_agents()
    self.set_interval(self.poll, self.refresh_agents)
    self.action_device_info()

  # --- agents ----------------------------------------------------------------

  def refresh_agents(self):
    state = self.read_state()
    now = time.time()
    entries = sorted(
      state['agents'].items(),
      key=lambda item: (-board.PRIORITY[item[1]['state']], -item[1]['updated']),
    )
    table = self.table
    selected = self.selected_agent()
    table.clear()
    for agent, entry in entries:
      style = STATE_STYLES.get(entry['state'], '')
      table.add_row(
        f'[{style}]{entry["state"]}[/]',
        entry['label'],
        age(now - entry['updated']),
        entry['detail'],
        agent,
        key=agent,
      )
    if selected in state['agents']:
      table.move_cursor(row=table.get_row_index(selected))
    table.border_subtitle = f'{len(entries)} reporting' if entries else 'no agents reporting'
    self.last_error = state.get('last_error')
    self.show_device()

  def selected_agent(self):
    table = self.table
    if not table.row_count:
      return None
    return table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value

  @work(thread=True, group='device')
  def action_clear_agent(self):
    agent = self.selected_agent()
    if not agent:
      return
    error = board.update(agent, 'clear', open_device=self.open_device)
    self.report(f'Cleared {agent}', error)

  @work(thread=True, group='device')
  def action_reset(self):
    self.report('All agents cleared', board.reset(open_device=self.open_device))

  # --- device ----------------------------------------------------------------

  def show_device(self):
    text = self.device_text + '\n[dim]brightness: [b][ ][/b] screen   [b]- +[/b] LEDs[/]'
    if self.last_error:
      text += f'\n[yellow]Last status push failed: {self.last_error}[/]'
    self.device_panel.update(text)

  def report(self, done, error=None):
    """Show an action's result (safe to call from a worker thread)."""
    message, severity = (f'{done}, but: {error}', 'warning') if error else (done, 'information')
    self.call_from_thread(self.notify, message, severity=severity)
    self.call_from_thread(self.refresh_agents)

  def run_device(self, action, done):
    """Run `action(device)` under the hooks' lock, in a worker thread.

    Returns the action's result (True if it returned nothing), or None on error.
    """
    try:
      with board.device_lock(), self.open_device() as device:
        result = action(device)
    except (BusyTagError, OSError) as error:
      self.call_from_thread(self.notify, str(error), severity='error', timeout=8)
      return None
    if done:
      self.call_from_thread(self.notify, done)
    return True if result is None else result

  @work(thread=True, group='device')
  def action_device_info(self):
    def read(device):
      info = device.info()
      return device.name, device.port, info

    result = self.run_device(read, None)
    if result is None:
      self.device_text = '[red]No display connected[/] (press d to look again)'
    else:
      name, port, info = result
      parts = [f'[b]{name}[/] on {port}']
      if info.get('firmware'):
        parts.append(f'firmware {info["firmware"]}')
      if info.get('image'):
        parts.append(f'showing {info["image"]}')
      parts.append(f'screen brightness {info.get("brightness")}')
      parts.append(f'LED brightness {config.load()["brightness"]}%')
      self.device_text = ' | '.join(parts)
    self.call_from_thread(self.show_device)

  def action_image(self):
    self.pick_image()

  @work(thread=True, group='device')
  def pick_image(self):
    def read(device):
      current = device.current_image()
      return [
        (name, f'{"* " if name == current else "  "}{name}  ({size // 1024} KB)')
        for name, size in device.images() if name not in board.STATUS_FILES
      ]

    items = self.run_device(read, None)
    if items:
      self.call_from_thread(self.push_screen, PickScreen('Show image', items), self.show_image)

  @work(thread=True, group='device')
  def show_image(self, name):
    if name and self.run_device(lambda device: device.show_image(name), f'Showing {name}'):
      self.call_from_thread(self.action_device_info)

  @work(group='ask')
  async def action_fill(self):
    color = await self.ask_color('Fill the screen with a color')
    if color:
      self.device_command(lambda device: device.fill_display(color), f'Screen filled with {color}')

  @work(group='ask')
  async def action_led_color(self):
    color = await self.ask_color('LED color')
    if color:
      self.set_led_color(color)

  async def ask_color(self, title):
    value = await self.push_screen_wait(AskScreen(title, 'RRGGBB or a name like red'))
    if not value:
      return None
    try:
      return parse_color(value)
    except ValueError as error:
      self.notify(str(error), severity='error', timeout=8)
      return None

  @work(thread=True, group='device')
  def set_led_color(self, color):
    brightness = config.load()['brightness']
    if self.run_device(lambda device: device.solid_color(scale_color(color, brightness)), f'LEDs set to {color}'):
      board.remember_led_color(color)

  @work(thread=True, group='device')
  def device_command(self, action, done):
    self.run_device(action, done)

  def action_led_off(self):
    self.device_command(lambda device: device.solid_color('000000'), 'LEDs off')

  @work(thread=True, group='device')
  def action_pattern(self):
    patterns = self.run_device(lambda device: device.builtin_patterns(), None)
    if not patterns:
      return
    self.pattern_names = dict(patterns)
    items = [(pattern_id, f'{pattern_id:>3}  {name}') for pattern_id, name in patterns]
    self.call_from_thread(self.push_screen, PickScreen('Play LED pattern', items), self.play_pattern)

  @work(thread=True, group='device')
  def play_pattern(self, choice):
    if choice is None:
      return
    pattern_id = int(choice)
    brightness = config.load()['brightness']
    self.run_device(
      lambda device: device.play_builtin_pattern(pattern_id, 255, brightness),
      f'Playing {self.pattern_names[pattern_id]}',
    )

  @work(thread=True, group='device')
  def action_display_brightness(self, step):
    def change(device):
      level = max(1, min(100, int(device.brightness()) + step))
      device.set_brightness(level)
      return level

    level = self.run_device(change, None)
    if level is not None:
      self.call_from_thread(self.notify, f'Screen brightness {level}')
      self.call_from_thread(self.action_device_info)

  @work(thread=True, group='device')
  def action_led_brightness(self, step):
    level = max(1, min(100, config.load()['brightness'] + step))
    config.set_brightness(level)
    _, error = board.apply_brightness(open_device=self.open_device)
    self.report(f'LED brightness {level}%', error)
    self.call_from_thread(self.action_device_info)


def run():
  BusyTagApp().run()
