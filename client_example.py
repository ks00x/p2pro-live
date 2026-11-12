'''
Example consumer of the P2Pro thermal server data stream.

  python client_example.py                         # ws://127.0.0.1:8080/ws/data, every frame
  python client_example.py --rate 1                # at most 1 message per second
  python client_example.py --url ws://192.168.0.10:8080/ws/data --csv log.csv

Every message is JSON. One per camera frame:
{
  "type": "frame",
  "ts": 1731420000123,          unix epoch in ms of the frame capture
  "ts_source": "driver",        "driver" (capture time from the camera driver) or "host" (time it was read)
  "frame": 1234,                frame counter since server start
  "unit": "C", "width": 256, "height": 192,
  "global": {"min": .., "max": .., "mean": .., "max_pos": {"x": .., "y": ..}, "min_pos": {"x": .., "y": ..}},
  "rois": [
    {"id": "P1", "type": "point", "x": 10, "y": 20, "locked": false, "temp": 31.25},
    {"id": "motor", "type": "rect", "x": 90, "y": 40, "w": 20, "h": 15, "locked": true,
     "pixels": 300, "min": .., "max": .., "mean": .., "max_pos": {..}, "min_pos": {..}},
    {"id": "C1", "type": "circle", "cx": 30.5, "cy": 30.5, "r": 6.2, "locked": false, "pixels": .., "min": .., ...}
  ]
}
and when the camera is (dis)connected, also sent first after connecting:
{"type": "status", "ts": 1731420000123, "camera_connected": false, "camera": "/dev/video4", "error": "..."}
'''
import argparse
import csv
import json
import sys

from websockets.sync.client import connect


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', default='ws://127.0.0.1:8080/ws/data')
    ap.add_argument('--rate', type=float, default=None, help='max messages per second')
    ap.add_argument('--csv', default=None, help='append one row per ROI and message: ts,id,type,temp/max,mean,min')
    ap.add_argument('--count', type=int, default=0, help='stop after n messages (0 = run forever)')
    args = ap.parse_args()
    url = args.url + (f'?rate={args.rate}' if args.rate else '')

    out = None
    if args.csv:
        f = open(args.csv, 'a', newline='')
        out = csv.writer(f)
        if f.tell() == 0:
            out.writerow(['ts', 'id', 'type', 'max', 'mean', 'min'])

    with connect(url) as ws:
        n = 0
        for text in ws:
            msg = json.loads(text)
            if msg['type'] == 'status':
                state = 'connected' if msg['camera_connected'] else f"DISCONNECTED ({msg['error']})"
                print(f"{msg['ts']} camera {msg['camera']} {state}", flush=True)
                continue
            g = msg['global']
            rois = ', '.join(f"{r['id']}={r['temp'] if r['type'] == 'point' else r['max']:.1f}" for r in msg['rois'])
            print(f"{msg['ts']} max {g['max']:.1f}C @({g['max_pos']['x']},{g['max_pos']['y']})  {rois}", flush=True)
            if out:
                out.writerow([msg['ts'], '_global', 'image', g['max'], g['mean'], g['min']])
                for r in msg['rois']:
                    if r['type'] == 'point':
                        out.writerow([msg['ts'], r['id'], 'point', r['temp'], r['temp'], r['temp']])
                    else:
                        out.writerow([msg['ts'], r['id'], r['type'], r['max'], r['mean'], r['min']])
            n += 1
            if args.count and n >= args.count:
                break


if __name__ == '__main__':
    sys.exit(main())
