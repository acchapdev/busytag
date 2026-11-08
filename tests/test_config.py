"""Config file tests."""

import pytest

from busytag import config
from busytag.colors import scale_color


@pytest.fixture(autouse=True)
def config_file(tmp_path, monkeypatch):
  path = tmp_path / 'busytag' / 'config.toml'
  monkeypatch.setenv('BUSYTAG_CONFIG', str(path))
  return path


def write(path, text):
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(text)


def test_defaults_are_written_on_first_use(config_file):
  settings = config.load()
  assert config_file.exists()
  assert settings == {
    'brightness': 100,
    'agent_colors': {'claude': 'FF6000', 'opencode': '0060FF', 'default': 'FFFFFF'},
  }


def test_user_agents_and_color_names(config_file):
  write(config_file, '[agents.codex]\ncolor = "green"\n[agents.claude]\ncolor = "#f0f"\n')
  colors = config.load()['agent_colors']
  assert colors['codex'] == '00FF00'
  assert colors['claude'] == 'FF00FF'
  assert colors['opencode'] == '0060FF'


def test_agent_color_lookup():
  settings = config.load()
  assert config.agent_color(settings, 'claude:abc123') == 'FF6000'
  assert config.agent_color(settings, 'opencode') == '0060FF'
  assert config.agent_color(settings, 'my-build') == 'FFFFFF'


def test_set_brightness_keeps_comments(config_file):
  config.load()
  config.set_brightness(40)
  text = config_file.read_text()
  assert 'brightness = 40' in text
  assert '# LED color for each agent type' in text
  assert config.load()['brightness'] == 40


def test_broken_config_falls_back_to_defaults(config_file):
  write(config_file, 'this is [not toml')
  assert config.load()['brightness'] == 100


def test_bad_color_falls_back_to_white(config_file):
  write(config_file, '[agents.claude]\ncolor = "chartreuse-ish"\n')
  assert config.load()['agent_colors']['claude'] == 'FFFFFF'


@pytest.mark.parametrize('color, percent, expected', [
  ('FF6000', 100, 'FF6000'), ('FF6000', 50, '803000'), ('FFFFFF', 25, '404040'), ('0060FF', 1, '000103'),
])
def test_scale_color(color, percent, expected):
  assert scale_color(color, percent) == expected
