# P2ProLive

Live view and temperature data stream for the Infiray P2Pro thermal camera on Windows and Linux (no special drivers).

## Thermal server (main app)
`thermal_server.py` reads the camera at its full frame rate (25 fps) and offers:
- a browser UI with the live thermal image (colormaps, auto/manual scale, temperature under the mouse cursor)
- collection points/areas drawn on the image: point (pixel), rectangle (drag) or circle (drag the radius),
  each with a label/id; delete them with the x in the list or select + Delete key
- the hottest (and coldest) pixel of the whole image with position
- a **data stream** for other applications: one JSON message per frame with unix epoch timestamp in ms,
  the global values and every point/area with its geometry and values

```bash
source .venv/bin/activate          # or your conda env, see below
pip install -r requirements.txt
python thermal_server.py           # camera auto detected on Linux, otherwise --cam /dev/videoN (Windows: --cam 0)
# open http://127.0.0.1:8080
```
Options: `--host 0.0.0.0` makes the server reachable from other machines (**there is no authentication**, everybody
in the network can see the stream and create/delete areas), `--port`, `--rois <file>` (default `rois.json`, the areas
survive restarts). Only one program can stream from the camera at a time (close webcam apps like Cheese).

### Data stream
| what | how |
|---|---|
| WebSocket (push) | `ws://<host>:8080/ws/data` |
| Server-Sent Events (push, plain HTTP) | `http://<host>:8080/api/stream` |
| last message (polling) | `GET http://<host>:8080/api/latest` |
| full temperature image | `GET http://<host>:8080/api/frame` (`temps`: 192 rows x 256 columns, C) |
| server/camera status | `GET http://<host>:8080/api/status` |

The push streams send every frame (~25/s). Add `?rate=N` to get at most N messages per second
(e.g. `ws://127.0.0.1:8080/ws/data?rate=1`). A slow client skips frames, it never receives old data.

Message (one per frame):
```json
{
  "ts": 1731420000123,
  "frame": 1234,
  "unit": "C", "width": 256, "height": 192,
  "global": {"min": 27.8, "max": 34.67, "mean": 31.4, "max_pos": {"x": 123, "y": 170}, "min_pos": {"x": 237, "y": 151}},
  "rois": [
    {"id": "P1", "type": "point", "x": 200, "y": 50, "temp": 32.01},
    {"id": "motor A", "type": "rect", "x": 40, "y": 30, "w": 40, "h": 30,
     "pixels": 1200, "min": 30.86, "max": 31.86, "mean": 31.34, "max_pos": {"x": 52, "y": 41}, "min_pos": {"x": 77, "y": 58}},
    {"id": "bearing", "type": "circle", "cx": 150.5, "cy": 100.5, "r": 10,
     "pixels": 317, "min": 32.0, "max": 32.4, "mean": 32.3, "max_pos": {"x": 151, "y": 97}, "min_pos": {"x": 141, "y": 103}}
  ]
}
```
- `ts`: unix epoch in milliseconds, host time when the frame was received.
- coordinates are image pixels: `x` = column 0..255, `y` = row 0..191 (sensor orientation). Pixel (i, j) covers
  [i, i+1) x [j, j+1). A rect/circle contains the pixels whose center (i+0.5, j+0.5) lies inside it.
- temperatures in Celsius, rounded to 0.01. The camera works in the high gain mode (up to ~180 C).

Examples:
```bash
python client_example.py --rate 1 --csv log.csv            # python, see the file
curl -N http://127.0.0.1:8080/api/stream?rate=1            # SSE in the terminal
```
```js
const ws = new WebSocket('ws://127.0.0.1:8080/ws/data');   // browser / node
ws.onmessage = (ev) => { const m = JSON.parse(ev.data); console.log(m.ts, m.global.max, m.rois); };
```

### Collection points/areas over REST
Other applications can manage the areas too (the UI is updated live):
```bash
curl http://127.0.0.1:8080/api/rois                                                    # list
curl -X POST http://127.0.0.1:8080/api/rois -d '{"id":"motor A","type":"rect","x":40,"y":30,"w":40,"h":30}'
curl -X POST http://127.0.0.1:8080/api/rois -d '{"id":"bearing","type":"circle","cx":150.5,"cy":100.5,"r":10}'
curl -X POST http://127.0.0.1:8080/api/rois -d '{"type":"point","x":200,"y":50}'      # no id -> P1, P2, ...
curl -X DELETE "http://127.0.0.1:8080/api/rois/motor%20A"                               # delete one (URL encoded id)
curl -X DELETE http://127.0.0.1:8080/api/rois                                          # delete all
```
Errors: 400 invalid definition (outside the image, w/h/r <= 0, ...), 409 id already exists, 404 id not found.
An id has 1..64 characters (no control characters).

### Live view protocol
`ws://<host>:8080/ws/live` (used by the browser UI): per frame the JSON message above followed by one binary message:
header `'<4sHHId'` (`b'P2PR'`, width, height, frame, ts_ms as float64) and width*height uint16 little endian raw values,
T[C] = raw/64 - 273.2.

## Installation
Windows (conda):
```powershell
conda create -n p2pro python
activate p2pro
pip install -r requirements.txt
```
Linux (venv):
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```
The recorder of the Streamlit app also needs the `ffmpeg` executable.

## Streamlit app (older UI)
Run with `streamlit run p2prolive_app.py`. Do not run it at the same time as the thermal server (one camera stream only).

### features
- runs on Windows and Linux without special drivers
- auto and manual scaling of the temperature to color mapping
- in image live display of max,min and center temperature
- history chart function for min,max,avg,center temperature 
- save history to csv
- save image to csv
- (still) image viewer with zoom etc
- Always and only works in the high sensitivity mode (up to 180C)
- finds the camera by its USB id on Linux (no probing of other webcams)
- shows the camera's own video stream in color (camera palette selectable)
- reads camera info over USB: firmware, part/serial number, gain mode, emissivity and other parameters
- records the live image to an .mkv file, optionally with a lossless radiometric track (raw 16 bit data of every frame)

run with (activate the p2pro env first):
`streamlit run p2prolive_app.py`
The app scans readable video ports and lets you select the camera port from the UI, so passing a device id is optional.

You can also run the direct viewer script and select a camera index in the terminal prompt:
`python p2pro.py`

## Linux: USB access
Reading the camera info and setting the palette uses USB vendor commands (pyusb). If the user has no access
to the USB device, install the udev rule (the user must be in the `video` group) and reconnect the camera:
```bash
sudo cp 60-p2pro.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```
Only one program can stream from the camera. Close other webcam apps (e.g. Cheese) before starting.

## Windows: USB access
For the USB vendor commands libusb needs to be installed as an upper filter driver with Zadig:
Options > List all devices, select "USB Camera (Interface 0)", choose "libusb-win32" and "Install filter driver".
The video stream must be opened before the USB commands are sent, otherwise the libusb call may hang.

## Recording
In the sidebar under "recording". The files go to `recordings/<date>_p2pro.mkv`, ffmpeg must be installed.
Stream 0 is the displayed image (H.264), stream 1 (optional) the raw 16 bit data (FFV1, lossless).
Read the radiometric data back in python:
```python
from recorder import load_radiometry
from p2pro import p2pro
raw = load_radiometry('recordings/2026-01-01_12-00-00_p2pro.mkv') # frames x 192 x 256
temp = p2pro.raw_to_celsius(raw)
```

You may create a .bat file to activate the env and click start the web app (change the folders to match your installation, note the <&> operator):
```bat
activate p2pro & streamlit run d:\users\klaus\develop\python\misc\infiray\p2pro-live\p2prolive_app.py 
```


![](/media/screenshot.png)

## Credits
The USB id detection, YUY2 video decoding, USB vendor commands (`p2pro_cmd.py`), the recorder (`recorder.py`) and
`60-p2pro.rules` are taken from or based on [P2Pro-Viewer](https://github.com/LeoDJ/P2Pro-Viewer) by LeoDJ (MIT License).
