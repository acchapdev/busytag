"""busytag command-line interface."""

from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Optional

import typer

from busytag.colors import parse_color, parse_leds, scale_color
from busytag.device import BusyTagError, open_device
from busytag import images as image_tools

app = typer.Typer(help='Control a Busy Tag or busytag ESP32 display over USB.', no_args_is_help=True)
image_app = typer.Typer(help='List, show, upload and delete images.', no_args_is_help=True)
led_app = typer.Typer(help='Control the LEDs (7 on a Busy Tag, 1 on the ESP32).', no_args_is_help=True)
app.add_typer(image_app, name='image')
app.add_typer(led_app, name='led')

PortOption = Annotated[
  Optional[str],
  typer.Option('--port', '-p', envvar='BUSYTAG_PORT', help='Serial port (auto-detected by default).'),
]


@app.callback()
def main(ctx: typer.Context, port: PortOption = None):
  ctx.obj = {'port': port}


@contextmanager
def connect(ctx):
  try:
    with open_device(ctx.obj['port']) as device:
      yield device
  except BusyTagError as error:
    typer.secho(f'Error: {error}', fg='red', err=True)
    raise typer.Exit(1)


def color_arg(value):
  try:
    return parse_color(value)
  except ValueError as error:
    raise typer.BadParameter(str(error))


def leds_arg(value):
  try:
    return parse_leds(value)
  except ValueError as error:
    raise typer.BadParameter(str(error))


def human_size(size):
  return f'{size / 1024:,.1f} KB' if size >= 1024 else f'{size} B'


# --- device ------------------------------------------------------------------

@app.command()
def info(ctx: typer.Context):
  """Show device identity, firmware, storage and current display state."""
  with connect(ctx) as device:
    details = device.info()
  total = details.pop('storage_total', None)
  free = details.pop('storage_free', None)
  width = max(len(key) for key in details) + 1
  for key, value in details.items():
    typer.echo(f'{key.replace("_", " ") + ":":<{width + 1}} {value}')
  if total is not None:
    typer.echo(f'{"storage:":<{width + 1}} {human_size(int(free))} free of {human_size(int(total))}')


@app.command()
def rotate(
  ctx: typer.Context,
  value: Annotated[Optional[int], typer.Argument(min=0, max=3, help='0-3 in 90 degree steps; 1 and 3 are landscape. Omit to read.')] = None,
):
  """Read or set the screen rotation (ESP32 display only; saved on the device)."""
  with connect(ctx) as device:
    if not getattr(device, 'draws_status', False):
      raise BusyTagError("The Busy Tag's screen can't be rotated.")
    typer.echo(device.rotate(value))


@app.command()
def brightness(
  ctx: typer.Context,
  level: Annotated[Optional[int], typer.Argument(min=1, max=100, help='1-100; omit to read.')] = None,
):
  """Read or set display brightness."""
  with connect(ctx) as device:
    if level is None:
      typer.echo(device.brightness())
    else:
      device.set_brightness(level)


@app.command()
def files(ctx: typer.Context):
  """List every file on the device, with storage usage."""
  with connect(ctx) as device:
    entries = device.files()
    total, free = device.storage()
  for name, kind, size in entries:
    typer.echo(f'{human_size(size):>10}  {name}')
  typer.echo(f'\n{human_size(free)} free of {human_size(total)}')


@app.command()
def raw(ctx: typer.Context, command: Annotated[str, typer.Argument(help='e.g. "AT+GFV"')]):
  """Send a raw AT command and print the reply lines (for debugging)."""
  with connect(ctx) as device:
    for line in device.raw(command):
      typer.echo(line)


# --- images ------------------------------------------------------------------

@image_app.command('list')
def image_list(ctx: typer.Context):
  """List images; the one on screen is marked with *."""
  with connect(ctx) as device:
    current = device.current_image()
    entries = device.images()
  for name, size in entries:
    marker = '*' if name == current else ' '
    typer.echo(f'{marker} {human_size(size):>10}  {name}')


@image_app.command('show')
def image_show(ctx: typer.Context, name: Annotated[str, typer.Argument(help='Image file on the device.')]):
  """Show an image that is already on the device."""
  with connect(ctx) as device:
    device.show_image(name)


@image_app.command('upload')
def image_upload(
  ctx: typer.Context,
  path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, help='PNG, JPG, GIF, ...')],
  name: Annotated[Optional[str], typer.Option(help='Filename on the device.')] = None,
  show: Annotated[bool, typer.Option('--show', '-s', help='Show it after uploading.')] = False,
):
  """Upload an image. Static images are fitted to 240x280 PNG."""
  try:
    filename, data, notes = image_tools.prepare(path)
  except OSError as error:
    raise typer.BadParameter(f'cannot read image: {error}')
  filename = name or filename
  for note in notes:
    typer.secho(f'note: {note}', fg='yellow', err=True)
  with connect(ctx) as device:
    device.upload(filename, data)
    typer.echo(f'uploaded {filename} ({human_size(len(data))})')
    if show:
      device.show_image(filename)


@image_app.command('delete')
def image_delete(
  ctx: typer.Context,
  name: Annotated[str, typer.Argument(help='File on the device.')],
  yes: Annotated[bool, typer.Option('--yes', '-y', help='Skip confirmation.')] = False,
):
  """Delete a file from the device."""
  if not yes:
    typer.confirm(f'Delete {name} from the device?', abort=True)
  with connect(ctx) as device:
    replacement = device.delete(name)
  if replacement:
    typer.echo(f'{name} was on screen; now showing {replacement}')


@image_app.command('fill')
def image_fill(ctx: typer.Context, color: Annotated[str, typer.Argument(parser=color_arg, help='Name or RRGGBB.')]):
  """Fill the screen with a solid color."""
  with connect(ctx) as device:
    device.fill_display(color)


# --- LEDs --------------------------------------------------------------------

LedsOption = Annotated[
  int,
  typer.Option('--leds', '-l', parser=leds_arg, help="'all', LED numbers like '1,4,7', or a mask."),
]


@led_app.command('color')
def led_color(
  ctx: typer.Context,
  color: Annotated[str, typer.Argument(parser=color_arg, help='Name or RRGGBB.')],
  leds: LedsOption = 'all',
):
  """Set LEDs to a solid color (stops any pattern), at the configured LED brightness."""
  from busytag import config, status as board

  with connect(ctx) as device:
    device.solid_color(scale_color(color, config.load()['brightness']), leds)
  if leds == 127:
    board.remember_led_color(color)


@led_app.command('brightness')
def led_brightness(
  ctx: typer.Context,
  level: Annotated[Optional[int], typer.Argument(min=1, max=100, help='1-100 percent; omit to read.')] = None,
):
  """Read or set LED brightness (saved in the config; applies to every LED color busytag sends)."""
  from busytag import config, status as board

  if level is None:
    typer.echo(config.load()['brightness'])
    return
  config.set_brightness(level)
  applied, error = board.apply_brightness()
  if error:
    typer.secho(f'Saved, but the LEDs were not updated: {error}', fg='yellow', err=True)
  elif applied is None:
    typer.echo(f'LED brightness {level}%; applies to the next LED change.')


@led_app.command('off')
def led_off(ctx: typer.Context):
  """Turn all LEDs off."""
  with connect(ctx) as device:
    device.solid_color('000000', 127)


@led_app.command('patterns')
def led_patterns(ctx: typer.Context):
  """List the built-in LED patterns."""
  with connect(ctx) as device:
    for pattern_id, name in device.builtin_patterns():
      typer.echo(f'{pattern_id:>3}  {name}')


@led_app.command('pattern')
def led_pattern(
  ctx: typer.Context,
  pattern: Annotated[str, typer.Argument(help="Built-in pattern name or ID, e.g. 'Red Pulses' or 17.")],
  repeat: Annotated[int, typer.Option('--repeat', '-r', min=1, max=255, help='Times to play; 255 = forever.')] = 255,
):
  """Play a built-in LED pattern, at the configured LED brightness."""
  from busytag import config

  with connect(ctx) as device:
    available = device.builtin_patterns()
    match = [
      pattern_id for pattern_id, name in available
      if pattern == str(pattern_id) or pattern.lower() == name.lower()
    ]
    if not match:
      names = ', '.join(name for _, name in available)
      typer.secho(f"Error: no pattern '{pattern}'. Available: {names}", fg='red', err=True)
      raise typer.Exit(1)
    device.play_builtin_pattern(match[0], repeat, config.load()['brightness'])


@led_app.command('stop')
def led_stop(ctx: typer.Context):
  """Stop the running LED pattern."""
  with connect(ctx) as device:
    device.stop_pattern()


# --- agent status ------------------------------------------------------------

STATE_CHOICES = ['working', 'done', 'attention', 'error', 'idle', 'clear']


@app.command()
def status(
  state: Annotated[str, typer.Argument(help=f'One of: {", ".join(STATE_CHOICES)}.')],
  agent: Annotated[str, typer.Option('--agent', '-a', help='Unique ID of the reporting agent.')] = 'default',
  label: Annotated[Optional[str], typer.Option('--label', '-l', help='Name shown on screen (defaults to the agent ID).')] = None,
  detail: Annotated[str, typer.Option('--detail', '-d', help='Short reason, shown for the most urgent agent.')] = '',
):
  """Report an agent's state; the device shows the most urgent agent."""
  from busytag import status as board

  if state not in STATE_CHOICES:
    raise typer.BadParameter(f'use one of: {", ".join(STATE_CHOICES)}', param_hint='STATE')
  error = board.update(agent, state, label, detail)
  if error:
    typer.secho(f'Saved, but the device was not updated: {error}', fg='yellow', err=True)


@app.command()
def agents(
  reset: Annotated[bool, typer.Option('--reset', help='Forget all agents and restore your own image and LEDs.')] = False,
):
  """List agents reporting status."""
  import time
  from busytag import status as board

  if reset:
    error = board.reset()
    typer.echo('All agents cleared.' if not error else f'Cleared, but device not updated: {error}')
    return
  entries, error = board.agents()
  if not entries:
    typer.echo('No agents reporting.')
  for agent, entry in entries:
    age = int(time.time() - entry['updated'])
    when = f'{age // 60}m ago' if age >= 60 else f'{age}s ago'
    detail = f'  {entry["detail"]}' if entry['detail'] else ''
    typer.echo(f'{entry["state"]:<10} {entry["label"]:<24} {when:>8}{detail}')
  if error:
    typer.secho(f'\nLast device error: {error}', fg='yellow')


@app.command()
def hook(
  source: Annotated[str, typer.Argument(help="Hook source: 'claude' or 'opencode'.")] = 'claude',
):
  """Read an agent event (Claude Code hook or OpenCode plugin) on stdin and update the status. Always exits 0."""
  from busytag import hooks

  hooks.run(source)


@app.command()
def setup(
  only: Annotated[Optional[str], typer.Option('--only', help="Just one integration: 'claude' or 'opencode'.")] = None,
  remove: Annotated[bool, typer.Option('--remove', help='Remove the integrations instead.')] = False,
):
  """Install the agent integrations (Claude Code hooks, OpenCode plugin) for the agents found."""
  from busytag import integrations

  if only and only not in integrations.INTEGRATIONS:
    raise typer.BadParameter(f'use one of: {", ".join(integrations.INTEGRATIONS)}', param_hint='--only')
  failed = False
  for name, ok, message in integrations.run(only, remove):
    typer.secho(f'{name}: {message}', fg=None if ok else 'red', err=not ok)
    failed = failed or not ok
  if not remove:
    try:
      with open_device() as device:
        typer.echo(f'Display: {device.name} found at {device.port}')
    except BusyTagError as error:
      typer.secho(f'Display: {error}', fg='yellow')
  if failed:
    raise typer.Exit(1)


@app.command('config')
def show_config(
  path_only: Annotated[bool, typer.Option('--path', help='Print only the config file path.')] = False,
):
  """Show the config file (LED brightness, agent colors); creates it with defaults if missing."""
  from busytag import config

  config.load_document()
  path = config.config_path()
  if path_only:
    typer.echo(path)
    return
  typer.secho(f'# {path}', fg='cyan')
  typer.echo(path.read_text())
