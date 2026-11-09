"""`busytag setup` tests: Claude Code settings merge and OpenCode plugin install."""

import json
import plistlib
from pathlib import Path

import pytest

from busytag import integrations

OTHER_HOOK = {'hooks': [{'type': 'command', 'command': 'atuin hook claude-code'}]}


@pytest.fixture(autouse=True)
def homes(tmp_path, monkeypatch):
  monkeypatch.setenv('CLAUDE_CONFIG_DIR', str(tmp_path / 'claude'))
  monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'config'))
  monkeypatch.setattr(integrations.shutil, 'which', lambda name: str(Path.home() / '.local/bin' / name))
  # Never touch the real LaunchAgents or launchd
  monkeypatch.setenv('HOME', str(tmp_path / 'home'))
  monkeypatch.setenv('BUSYTAG_STATE_DIR', str(tmp_path / 'state'))
  monkeypatch.setattr(integrations, 'launchctl', FakeLaunchctl())
  return tmp_path


class FakeLaunchctl:
  def __init__(self):
    self.calls = []
    self.loaded = False

  def __call__(self, *args):
    self.calls.append(args[0])
    if args[0] == 'bootstrap':
      self.loaded = True
    elif args[0] == 'bootout':
      self.loaded = False
    code = 0 if args[0] != 'print' or self.loaded else 113
    return type('Result', (), {'returncode': code, 'stdout': '', 'stderr': ''})()


def settings_file():
  return integrations.claude_settings_path()


def write_settings(data):
  path = settings_file()
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(json.dumps(data, indent=2))


def our_commands(settings):
  return [
    entry['command'] for groups in settings.get('hooks', {}).values()
    for group in groups for entry in group['hooks'] if 'busytag' in entry['command']
  ]


# --- Claude Code -------------------------------------------------------------

def test_claude_hooks_added_and_other_settings_kept():
  write_settings({'model': 'opus', 'hooks': {'Stop': [OTHER_HOOK]}})
  message = integrations.setup_claude()
  settings = json.loads(settings_file().read_text())
  assert settings['model'] == 'opus'
  assert settings['hooks']['Stop'][0] == OTHER_HOOK
  assert set(settings['hooks']) == set(integrations.CLAUDE_EVENTS)
  assert our_commands(settings) == ['$HOME/.local/bin/busytag hook claude'] * len(integrations.CLAUDE_EVENTS)
  assert settings['hooks']['Stop'][1]['hooks'][0]['async'] is True
  assert 'backup' in message
  assert list(settings_file().parent.glob('settings.json.bak-busytag-*'))


def test_claude_setup_is_idempotent():
  write_settings({'hooks': {'Stop': [OTHER_HOOK]}})
  integrations.setup_claude()
  assert integrations.setup_claude().startswith('already set up')
  settings = json.loads(settings_file().read_text())
  assert len(our_commands(settings)) == len(integrations.CLAUDE_EVENTS)


def test_claude_setup_replaces_old_path():
  write_settings({'hooks': {'Stop': [{'hooks': [
    {'type': 'command', 'command': '/opt/old/busytag hook claude', 'async': True},
    {'type': 'command', 'command': 'say done'},
  ]}]}})
  integrations.setup_claude()
  settings = json.loads(settings_file().read_text())
  # Our entry leaves the shared group; the other hook stays
  assert settings['hooks']['Stop'][0] == {'hooks': [{'type': 'command', 'command': 'say done'}]}
  assert '/opt/old/busytag hook claude' not in our_commands(settings)


def test_claude_remove_leaves_other_hooks():
  write_settings({'model': 'opus', 'hooks': {'Stop': [OTHER_HOOK]}})
  integrations.setup_claude()
  integrations.setup_claude(remove=True)
  assert json.loads(settings_file().read_text()) == {'model': 'opus', 'hooks': {'Stop': [OTHER_HOOK]}}


def test_claude_settings_created_when_missing():
  integrations.setup_claude()
  assert len(our_commands(json.loads(settings_file().read_text()))) == len(integrations.CLAUDE_EVENTS)


def test_claude_invalid_json_is_left_alone():
  settings_file().parent.mkdir(parents=True)
  settings_file().write_text('{ not json')
  with pytest.raises(integrations.SetupError):
    integrations.setup_claude()
  assert settings_file().read_text() == '{ not json'


# --- OpenCode ----------------------------------------------------------------

def plugin_file():
  return integrations.opencode_dir() / 'plugins' / 'busytag.ts'


def test_opencode_plugin_installed_and_removed():
  assert 'plugin installed' in integrations.setup_opencode()
  assert 'export default { id: "busytag", setup }' in plugin_file().read_text()
  assert integrations.setup_opencode().startswith('already set up')
  integrations.setup_opencode(remove=True)
  assert not plugin_file().exists()


def test_opencode_development_link_is_kept(tmp_path):
  checkout = tmp_path / 'checkout.ts'
  checkout.write_text('// dev')
  plugin_file().parent.mkdir(parents=True)
  plugin_file().symlink_to(checkout)
  assert 'left as is' in integrations.setup_opencode()
  assert plugin_file().is_symlink()


# --- Plug-in refresh LaunchAgent ---------------------------------------------

def test_watch_agent_installed_and_loaded():
  message = integrations.setup_watch()
  plist = plistlib.loads(integrations.launch_agent_path().read_bytes())
  assert plist['ProgramArguments'] == [str(Path.home() / '.local/bin/busytag'), 'watch']
  assert plist['KeepAlive'] is True
  assert plist['EnvironmentVariables']['BUSYTAG_STATE_DIR'].endswith('state')
  assert integrations.launchctl.calls == ['print', 'bootstrap']
  assert 'installed' in message


def test_watch_setup_is_idempotent():
  integrations.setup_watch()
  assert integrations.setup_watch().startswith('already set up')
  assert integrations.launchctl.calls.count('bootstrap') == 1


def test_watch_agent_reloaded_when_changed():
  integrations.setup_watch()
  integrations.launch_agent_path().write_bytes(b'old')
  integrations.setup_watch()
  assert integrations.launchctl.calls == ['print', 'bootstrap', 'print', 'bootout', 'bootstrap']


def test_watch_agent_removed():
  integrations.setup_watch()
  assert integrations.setup_watch(remove=True).startswith('stopped and removed')
  assert not integrations.launch_agent_path().exists()
  assert not integrations.launchctl.loaded
  assert integrations.setup_watch(remove=True) == 'LaunchAgent not installed'


def test_watch_needs_busytag_on_path(monkeypatch):
  monkeypatch.setattr(integrations.shutil, 'which', lambda name: None)
  results = list(integrations.run(only='watch'))
  assert results[0][1] is False
  assert 'not on PATH' in results[0][2]


# --- run ---------------------------------------------------------------------

def test_missing_agents_are_skipped(monkeypatch):
  monkeypatch.setattr(integrations.shutil, 'which', lambda name: None)
  results = list(integrations.run())
  assert [message for _, _, message in results][:2] == ['not found on this computer; skipped'] * 2
  assert not settings_file().exists()


def test_only_installs_one(homes):
  (homes / 'claude').mkdir()
  results = list(integrations.run(only='opencode'))
  assert [name for name, _, _ in results] == ['OpenCode']
  assert not settings_file().exists()
