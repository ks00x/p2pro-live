# P2ProLive

Live view and temperature data stream for the Infiray P2Pro thermal camera on Windows and Linux (no special drivers).

![](media/screenshot.png)

## Thermal server
`thermal_server.py` reads the camera at its full frame rate (25 fps) and offers:
- a browser UI with the live thermal image (colormaps, auto/manual scale, temperature under the mouse cursor)
- collection points/areas drawn on the image: point (pixel), rectangle (drag) or circle (drag the radius),
  each with a label/id; delete them with the x in the list or select + Delete key
- the hottest (and coldest) pixel of the whole image with position
- a **data stream** for other applications: one JSON message per frame with unix epoch timestamp in ms,
  the global values and every point/area with its geometry and values

```bash
source .venv/bin/activate          # or your conda env, see Installation
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

## Credits
Based on [p2pro-live](https://github.com/ks00x/p2pro-live) by Klaus Schwarzburg (MIT License). The detection of the
camera by its USB id follows [P2Pro-Viewer](https://github.com/LeoDJ/P2Pro-Viewer) by LeoDJ (MIT License).
