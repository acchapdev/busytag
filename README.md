# busytag

Command-line control for a Busy Tag USB display (firmware 2.x).

```bash
just install                              # puts `busytag` on PATH
busytag info
busytag image list                        # * marks the image on screen
busytag image upload photo.jpg --show     # static images are fitted to 240x280 PNG
busytag image show Busy_uwkmkuod.png
busytag image delete old.gif              # switches away first if it's on screen
busytag image fill purple                 # solid screen color
busytag led color red --leds 1,4,7        # names or RRGGBB; LEDs 1-7, 'all', or a mask
busytag led pattern "Red Pulses" -r 3     # built-in pattern by name or ID; 255 = forever
busytag led patterns | stop | off
busytag brightness 60
busytag raw 'AT+GFV'                      # debug: send any AT command
```

The port is auto-detected; override with `--port` or `BUSYTAG_PORT`.
Quit the Busy Tag desktop app first: only one program can use the port.
