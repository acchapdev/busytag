"""Prepare images for the 240x280 display."""

import io
from pathlib import Path

from PIL import Image, ImageOps

WIDTH = 240
HEIGHT = 280
MAX_GIF_BYTES = 1_000_000


def prepare(path):
  """Return (filename, bytes, notes) ready to upload.

  Static images are fitted to 240x280 and saved as PNG. GIFs are uploaded
  unchanged so animation survives; notes warn when they won't display well.
  """
  path = Path(path)
  notes = []
  with Image.open(path) as image:
    size = image.size
    if image.format == 'GIF':
      data = path.read_bytes()
      if size != (WIDTH, HEIGHT):
        notes.append(f'GIF is {size[0]}x{size[1]}, display is {WIDTH}x{HEIGHT}')
      if len(data) > MAX_GIF_BYTES:
        notes.append(f'GIF is {len(data):,} bytes; the device supports about 1 MB')
      return path.name, data, notes

    if image.format == 'PNG' and size == (WIDTH, HEIGHT):
      return path.name, path.read_bytes(), notes

    # Crop to fill the screen, keeping the centre of the image
    fitted = ImageOps.fit(image.convert('RGBA'), (WIDTH, HEIGHT))
    output = io.BytesIO()
    fitted.save(output, format='PNG', optimize=True)
    notes.append(f'converted {image.format} {size[0]}x{size[1]} to {WIDTH}x{HEIGHT} PNG')
    return f'{path.stem}.png', output.getvalue(), notes
