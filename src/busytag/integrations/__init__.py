"""Install and remove the agent integrations: Claude Code hooks and the OpenCode plugin.

Used by `busytag setup` (and so by install.sh). Every step is safe to repeat: our own
entries are replaced, never duplicated, and nothing else in the user's config is touched.
"""

import json
import os
import re
import shutil
import time
from importlib import resources
from pathlib import Path

# Claude Code events that change an agent's state (see hooks.claude_update)
CLAUDE_EVENTS = [
  'SessionStart', 'UserPromptSubmit', 'PreToolUse', 'PostToolUse', 'PostToolUseFailure',
  'PermissionRequest', 'Notification', 'Stop', 'StopFailure', 'SessionEnd',
]
# Matches our hook command however busytag's path was written
OUR_CLAUDE_HOOK = re.compile(r'busytag"?\s+hook\s+claude\b')

OPENCODE_RELOAD = "restart OpenCode's background service to load it: opencode service restart"


class SetupError(Exception):
  pass


def busytag_command():
  """How hooks should run busytag: its installed path, with $HOME kept portable."""
  path = shutil.which('busytag')
  if not path:
    return 'busytag'
  home = str(Path.home())
  if path.startswith(home + os.sep):
    path = '$HOME' + path[len(home):]
  return f'"{path}"' if ' ' in path else path


def claude_settings_path():
  return Path(os.environ.get('CLAUDE_CONFIG_DIR') or Path.home() / '.claude') / 'settings.json'


def opencode_dir():
  return Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'opencode'


def claude_present():
  return claude_settings_path().parent.is_dir() or shutil.which('claude') is not None


def opencode_present():
  return opencode_dir().is_dir() or shutil.which('opencode') is not None


def strip_claude_hooks(hooks):
  """Remove our hook entries in place, dropping groups and events they leave empty."""
  for event in list(hooks):
    groups = []
    for group in hooks[event]:
      entries = group.get('hooks', [])
      kept = [entry for entry in entries if not OUR_CLAUDE_HOOK.search(entry.get('command', ''))]
      if kept or not entries:
        groups.append({**group, 'hooks': kept} if entries else group)
    if groups:
      hooks[event] = groups
    else:
      del hooks[event]


def setup_claude(remove=False):
  """Add (or remove) the busytag hook on every Claude Code event. Returns a status line."""
  path = claude_settings_path()
  try:
    text = path.read_text() if path.exists() else ''
    settings = json.loads(text) if text.strip() else {}
  except json.JSONDecodeError as error:
    raise SetupError(f'{path} is not valid JSON ({error}); fix it and run busytag setup again')

  hooks = settings.setdefault('hooks', {})
  strip_claude_hooks(hooks)
  if not remove:
    command = f'{busytag_command()} hook claude'
    for event in CLAUDE_EVENTS:
      # async: Claude never waits for the display
      hooks.setdefault(event, []).append({'hooks': [{'type': 'command', 'command': command, 'async': True}]})
  if not hooks:
    del settings['hooks']

  new_text = json.dumps(settings, indent=2, ensure_ascii=False) + '\n'
  if text and json.loads(text) == settings:
    return f'already {"removed" if remove else "set up"} in {path}'
  backup = ''
  if text:
    backup_path = path.with_name(f'{path.name}.bak-busytag-{time.strftime("%Y%m%d-%H%M%S")}')
    backup_path.write_text(text)
    backup = f' (backup: {backup_path})'
  path.parent.mkdir(parents=True, exist_ok=True)
  temp = path.with_suffix('.busytag-tmp')
  temp.write_text(new_text)
  temp.replace(path)
  action = 'hooks removed from' if remove else 'hooks added to'
  return f'{action} {path}{backup}; applies to new sessions'


def setup_opencode(remove=False):
  """Install (or remove) the OpenCode 2 plugin. Returns a status line."""
  target = opencode_dir() / 'plugins' / 'busytag.ts'
  if remove:
    if not (target.exists() or target.is_symlink()):
      return 'plugin not installed'
    target.unlink()
    return f'removed {target}; {OPENCODE_RELOAD}'
  if target.is_symlink():
    # `just install-opencode` links a development checkout; keep following it
    return f'{target} links to {os.readlink(target)} (development checkout); left as is'
  plugin = resources.files('busytag.integrations').joinpath('opencode.ts').read_text()
  if target.exists() and target.read_text() == plugin:
    return f'already set up in {target}'
  target.parent.mkdir(parents=True, exist_ok=True)
  target.write_text(plugin)
  return f'plugin installed at {target}; {OPENCODE_RELOAD}'


INTEGRATIONS = {
  'claude': ('Claude Code', claude_present, setup_claude),
  'opencode': ('OpenCode', opencode_present, setup_opencode),
}


def run(only=None, remove=False):
  """Yield (name, ok, message) for each integration."""
  for key, (name, present, apply) in INTEGRATIONS.items():
    if only and key != only:
      continue
    if not only and not remove and not present():
      yield name, True, 'not found on this computer; skipped'
      continue
    try:
      yield name, True, apply(remove)
    except (SetupError, OSError) as error:
      yield name, False, str(error)
