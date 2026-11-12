'''
P2Pro thermal server: live view in the browser, collection regions (ROIs) and a data stream for other applications.

run:  python thermal_server.py [--cam /dev/video4] [--host 127.0.0.1] [--port 8080] [--rois rois.json]
open: http://127.0.0.1:8080

Data stream (one JSON message per camera frame, see README / roi.build_message):
  WebSocket  ws://<host>:<port>/ws/data[?rate=<max msgs/s>]
  SSE        http://<host>:<port>/api/stream[?rate=<max msgs/s>]
  polling    http://<host>:<port>/api/latest
ROIs (REST): GET/POST/DELETE /api/rois, DELETE /api/rois/{id}
Full temperature image: GET /api/frame
Live view (browser): ws://<host>:<port>/ws/live, per frame one JSON text message followed by one binary message
  binary = header '<4sHHId' (b'P2PR', width, height, frame, ts_ms) + width*height uint16 little endian raw values,
  T[C] = raw/64 - 273.2
'''
import argparse
import asyncio
import contextlib
import json
import logging
import os
import struct
import threading
import time

import numpy as np
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket, WebSocketDisconnect

from p2pro import p2pro, P2PRO_ROWS, P2PRO_COLS
from roi import RoiSet, RoiError, build_message

log = logging.getLogger('thermal_server')
HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, 'static')
FRAME_HEADER = struct.Struct('<4sHHId')
SHAPE = (P2PRO_ROWS, P2PRO_COLS)


class Client:
    'one stream subscriber. Keeps only the newest messages, a slow client skips frames instead of lagging behind'

    def __init__(self, kind, rate=None):
        self.kind = kind  # 'live' (json + binary frame), 'data' (json) or 'sse' (json)
        self.min_interval = 1.0 / rate if rate else 0.0
        self.last_sent = 0.0
        self.queue = asyncio.Queue(maxsize=2)

    def offer(self, item):
        now = time.monotonic()
        if self.min_interval and now - self.last_sent < self.min_interval:
            return
        self.last_sent = now
        if self.queue.full():
            self.queue.get_nowait()  # drop the oldest
        self.queue.put_nowait(item)


class Hub:
    'distributes the frames of the camera thread to the clients (runs in the asyncio loop)'

    def __init__(self):
        self.clients = set()

    def publish(self, text, frame_bytes):
        for c in self.clients:
            c.offer((text, frame_bytes) if c.kind == 'live' else text)


class CameraWorker:
    'reads the camera in its own thread, computes the statistics and publishes them'

    def __init__(self, cam_id, rois, hub, loop):
        self.cam_id = cam_id
        self.rois = rois
        self.hub = hub
        self.loop = loop
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run, name='camera', daemon=True)
        self.latest = None  # (message dict, temperature image)
        self.status = {'camera': None, 'connected': False, 'error': None, 'fps': 0.0, 'frames': 0}

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.thread.join(timeout=5)

    def _open(self):
        cam = p2pro(self.cam_id)  # None -> auto detect by USB id
        self.status.update(camera=str(cam.cam_id), connected=True, error=None)
        log.info('camera %s opened', cam.cam_id)
        return cam

    def run(self):
        cam = None
        frame_no = 0
        t_fps, n_fps = time.monotonic(), 0
        while not self.stop_event.is_set():
            if cam is None:
                try:
                    cam = self._open()
                except Exception as ex:
                    self.status.update(connected=False, error=str(ex))
                    log.warning('camera not available: %s (retrying)', ex)
                    self.stop_event.wait(2)
                    continue
            try:
                frame = cam.get_frame(skip=0, allow_stale=False)
            except Exception as ex:
                self.status.update(connected=False, error=str(ex))
                log.warning('camera read failed: %s (reconnecting)', ex)
                cam = None
                self.stop_event.wait(1)
                continue
            ts_ms = int(time.time() * 1000)  # host time when the frame was received
            raw = p2pro.frame_raw(frame)
            temp = p2pro.raw_to_celsius(raw).astype(np.float32)
            frame_no += 1
            msg = build_message(temp, self.rois.snapshot(), ts_ms, frame_no)
            text = json.dumps(msg, separators=(',', ':'), ensure_ascii=False)
            h, w = raw.shape
            frame_bytes = FRAME_HEADER.pack(b'P2PR', w, h, frame_no % 2**32, float(ts_ms)) + raw.astype('<u2').tobytes()
            self.latest = (msg, temp)
            self.loop.call_soon_threadsafe(self.hub.publish, text, frame_bytes)
            n_fps += 1
            now = time.monotonic()
            if now - t_fps >= 1:
                self.status.update(fps=round(n_fps / (now - t_fps), 1), frames=frame_no)
                t_fps, n_fps = now, 0
        cam = None


def parse_rate(params):
    'optional ?rate=<max messages per second>'
    rate = params.get('rate')
    if rate is None:
        return None
    rate = float(rate)
    if not rate > 0:
        raise ValueError('rate must be > 0')
    return rate


def create_app(cam_id=None, rois_path=None):
    hub = Hub()
    rois = RoiSet(SHAPE, rois_path)
    state = {}

    @contextlib.asynccontextmanager
    async def lifespan(app):
        worker = CameraWorker(cam_id, rois, hub, asyncio.get_running_loop())
        state['worker'] = worker
        worker.start()
        yield
        worker.stop()

    def error(msg, status=400):
        return JSONResponse({'error': msg}, status_code=status)

    async def index(request):
        return FileResponse(os.path.join(STATIC, 'index.html'))

    async def api_status(request):
        w = state['worker']
        return JSONResponse({**w.status, 'clients': len(hub.clients), 'rois': len(rois.snapshot()),
                             'width': SHAPE[1], 'height': SHAPE[0]})

    async def api_latest(request):
        latest = state['worker'].latest
        if latest is None:
            return error('no frame yet', 503)
        return JSONResponse(latest[0])

    async def api_frame(request):
        latest = state['worker'].latest
        if latest is None:
            return error('no frame yet', 503)
        msg, temp = latest
        return JSONResponse({k: msg[k] for k in ('ts', 'frame', 'unit', 'width', 'height')} |
                            {'temps': np.round(temp, 2).tolist()})

    async def api_rois(request: Request):
        if request.method == 'GET':
            return JSONResponse(rois.definitions())
        if request.method == 'DELETE':
            return JSONResponse({'deleted': rois.clear()})
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return error('body must be JSON')
        try:
            if isinstance(body, list):  # several at once, all or nothing is not guaranteed
                return JSONResponse([rois.add(d) for d in body], status_code=201)
            return JSONResponse(rois.add(body), status_code=201)
        except RoiError as ex:
            return error(str(ex), 409 if 'already exists' in str(ex) else 400)

    async def api_roi_delete(request: Request):
        roi_id = request.path_params['roi_id']
        if not rois.remove(roi_id):
            return error(f'id "{roi_id}" not found', 404)
        return Response(status_code=204)

    async def api_stream(request: Request):
        try:
            client = Client('sse', parse_rate(request.query_params))
        except ValueError as ex:
            return error(str(ex))

        async def events():
            hub.clients.add(client)
            try:
                yield 'retry: 2000\n\n'
                while True:
                    try:
                        text = await asyncio.wait_for(client.queue.get(), 10)
                        yield f'data: {text}\n\n'
                    except asyncio.TimeoutError:
                        yield ': keepalive\n\n'  # camera stalled, keep the connection open
            finally:
                hub.clients.discard(client)

        return StreamingResponse(events(), media_type='text/event-stream',
                                 headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

    async def ws_stream(websocket: WebSocket, kind):
        try:
            client = Client(kind, parse_rate(websocket.query_params))
        except ValueError as ex:
            await websocket.close(code=1008, reason=str(ex))
            return
        await websocket.accept()
        hub.clients.add(client)

        async def drain():  # detects the disconnect, incoming messages are ignored
            while True:
                if (await websocket.receive())['type'] == 'websocket.disconnect':
                    return

        receiver = asyncio.create_task(drain())
        try:
            while not receiver.done():
                getter = asyncio.create_task(client.queue.get())
                done, _ = await asyncio.wait({getter, receiver}, return_when=asyncio.FIRST_COMPLETED)
                if getter not in done:
                    getter.cancel()
                    break
                item = getter.result()
                if kind == 'live':
                    await websocket.send_text(item[0])
                    await websocket.send_bytes(item[1])
                else:
                    await websocket.send_text(item)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            hub.clients.discard(client)
            receiver.cancel()

    async def ws_live(websocket):
        await ws_stream(websocket, 'live')

    async def ws_data(websocket):
        await ws_stream(websocket, 'data')

    routes = [
        Route('/', index),
        Route('/api/status', api_status),
        Route('/api/latest', api_latest),
        Route('/api/frame', api_frame),
        Route('/api/stream', api_stream),
        Route('/api/rois', api_rois, methods=['GET', 'POST', 'DELETE']),
        Route('/api/rois/{roi_id:path}', api_roi_delete, methods=['DELETE']),
        WebSocketRoute('/ws/live', ws_live),
        WebSocketRoute('/ws/data', ws_data),
        Mount('/static', StaticFiles(directory=STATIC), name='static'),
    ]
    return Starlette(routes=routes, lifespan=lifespan)


def main():
    ap = argparse.ArgumentParser(description='P2Pro thermal server (live view, ROIs, data stream)')
    ap.add_argument('--cam', default=None, help='camera id (/dev/videoN on Linux, index on Windows). Default: auto detect (Linux)')
    ap.add_argument('--host', default='127.0.0.1', help='use 0.0.0.0 to allow access from other machines (no authentication!)')
    ap.add_argument('--port', type=int, default=8080)
    ap.add_argument('--rois', default=os.path.join(HERE, 'rois.json'), help='file where the ROIs are stored')
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    print(f'P2Pro thermal server: http://{args.host}:{args.port}  (data stream: ws://{args.host}:{args.port}/ws/data)')
    uvicorn.run(create_app(args.cam, args.rois), host=args.host, port=args.port, log_level='warning')


if __name__ == '__main__':
    main()
