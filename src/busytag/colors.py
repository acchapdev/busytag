"""Color name and hex parsing."""

import re

NAMED_COLORS = {
  'off': '000000',
  'black': '000000',
  'white': 'FFFFFF',
  'red': 'FF0000',
  'green': '00FF00',
  'blue': '0000FF',
  'yellow': 'FFFF00',
  'cyan': '00FFFF',
  'magenta': 'FF00FF',
  'orange': 'FF8000',
  'purple': '8000FF',
  'pink': 'FF4080',
}


def parse_color(value):
  """Turn 'red', '#ff0000' or 'FF0000' into 'FF0000'."""
  text = value.strip().lower()
  if text in NAMED_COLORS:
    return NAMED_COLORS[text]
  text = text.lstrip('#')
  if re.fullmatch(r'[0-9a-f]{3}', text):
    text = ''.join(char * 2 for char in text)
  if re.fullmatch(r'[0-9a-f]{6}', text):
    return text.upper()
  names = ', '.join(NAMED_COLORS)
  raise ValueError(f"'{value}' is not a color. Use RRGGBB hex or one of: {names}")


def scale_color(color, percent):
  """Dim an RRGGBB color to `percent` of its brightness."""
  channels = [int(color[i:i + 2], 16) for i in (0, 2, 4)]
  return ''.join(f'{round(channel * percent / 100):02X}' for channel in channels)


def parse_leds(value):
  """Turn 'all', '1,3,5' or a raw mask like '127' into a 7-bit LED mask."""
  text = value.strip().lower()
  if text == 'all':
    return 127
  if ',' not in text and text.isdigit() and int(text) > 7:
    mask = int(text)
  else:
    mask = 0
    for part in text.split(','):
      if not part.strip().isdigit() or not 1 <= int(part) <= 7:
        raise ValueError(f"'{value}' is not valid. Use 'all', LED numbers 1-7 like '1,4,7', or a mask")
      mask |= 1 << (int(part) - 1)
  if not 1 <= mask <= 127:
    raise ValueError(f'LED mask must be 1-127, got {mask}')
  return mask
