'''
Collection regions (ROIs) on the thermal image and the per frame statistics.

Coordinates are image pixels of the (un-rotated) sensor image, W x H = 256 x 192:
x = column (0..W-1), y = row (0..H-1). Pixel (i, j) covers [i, i+1) x [j, j+1), its center is (i+0.5, j+0.5).

ROI definitions (JSON):
  point : {"id": "p1", "type": "point",  "x": 10, "y": 20}                    -> the single pixel (x, y)
  rect  : {"id": "a1", "type": "rect",   "x": 10, "y": 20, "w": 30, "h": 15}  -> pixels whose center lies inside
  circle: {"id": "c1", "type": "circle", "cx": 50.5, "cy": 60.5, "r": 8}      -> pixels whose center lies inside
'''
import json
import math
import os
import threading
import unicodedata

import numpy as np

ID_MAX_LEN = 64
GEOMETRY_KEYS = {'point': ('x', 'y'), 'rect': ('x', 'y', 'w', 'h'), 'circle': ('cx', 'cy', 'r')}


class RoiError(ValueError):
    pass


def _r2(v):
    'rounds a temperature/coordinate for the JSON output'
    return round(float(v), 2)


def _pos(x, y):
    return {'x': int(x), 'y': int(y)}


def validate_id(roi_id):
    if not isinstance(roi_id, str):
        raise RoiError('id must be a string')
    roi_id = roi_id.strip()
    if not 1 <= len(roi_id) <= ID_MAX_LEN:
        raise RoiError(f'id must have 1..{ID_MAX_LEN} characters')
    if any(unicodedata.category(c).startswith('C') for c in roi_id):
        raise RoiError('id must not contain control characters')
    return roi_id


class Roi:
    'one collection region. Immutable after creation, the pixel indices are precomputed'

    def __init__(self, roi_id, kind, geom, shape):
        self.id = roi_id
        self.type = kind
        self.geom = geom  # dict with the GEOMETRY_KEYS of the type
        h, w = shape
        if kind == 'point':
            x, y = geom['x'], geom['y']
            if not (0 <= x < w and 0 <= y < h):
                raise RoiError(f'point ({x}, {y}) is outside the image ({w} x {h})')
            self.ys = np.array([y])
            self.xs = np.array([x])
        else:
            cy, cx = np.mgrid[0:h, 0:w]
            cx = cx + 0.5  # pixel centers
            cy = cy + 0.5
            if kind == 'rect':
                g = geom
                mask = (cx >= g['x']) & (cx <= g['x'] + g['w']) & (cy >= g['y']) & (cy <= g['y'] + g['h'])
            else:
                g = geom
                mask = (cx - g['cx']) ** 2 + (cy - g['cy']) ** 2 <= g['r'] ** 2
            self.ys, self.xs = np.nonzero(mask)
            if self.ys.size == 0:
                raise RoiError(f'{kind} contains no pixel of the image')

    @classmethod
    def from_dict(cls, d, shape):
        'validates a ROI definition (see module doc) and builds the ROI'
        if not isinstance(d, dict):
            raise RoiError('ROI definition must be a JSON object')
        roi_id = validate_id(d.get('id'))
        kind = d.get('type')
        if kind not in GEOMETRY_KEYS:
            raise RoiError(f'type must be one of {list(GEOMETRY_KEYS)}')
        geom = {}
        for k in GEOMETRY_KEYS[kind]:
            v = d.get(k)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                raise RoiError(f'{kind}: "{k}" must be a finite number')
            geom[k] = v
        if kind == 'point':
            geom = {'x': int(math.floor(geom['x'])), 'y': int(math.floor(geom['y']))}
        else:
            geom = {k: _r2(v) for k, v in geom.items()}
        if kind == 'rect' and (geom['w'] <= 0 or geom['h'] <= 0):
            raise RoiError('rect: w and h must be > 0')
        if kind == 'circle' and geom['r'] <= 0:
            raise RoiError('circle: r must be > 0')
        return cls(roi_id, kind, geom, shape)

    def to_dict(self):
        return {'id': self.id, 'type': self.type, **self.geom}

    def stats(self, temp):
        'definition + values of this ROI for the temperature image temp (H x W, Celsius)'
        out = self.to_dict()
        vals = temp[self.ys, self.xs]
        if self.type == 'point':
            out['temp'] = _r2(vals[0])
            return out
        kmax = int(np.argmax(vals))
        kmin = int(np.argmin(vals))
        out.update({
            'pixels': int(vals.size),
            'min': _r2(vals[kmin]),
            'max': _r2(vals[kmax]),
            'mean': _r2(vals.mean()),
            'max_pos': _pos(self.xs[kmax], self.ys[kmax]),
            'min_pos': _pos(self.xs[kmin], self.ys[kmin]),
        })
        return out


def global_stats(temp):
    'min, max, mean and the positions of the hottest and coldest pixel of the whole image'
    kmax = int(np.argmax(temp))
    kmin = int(np.argmin(temp))
    ymax, xmax = np.unravel_index(kmax, temp.shape)
    ymin, xmin = np.unravel_index(kmin, temp.shape)
    return {
        'min': _r2(temp.flat[kmin]),
        'max': _r2(temp.flat[kmax]),
        'mean': _r2(temp.mean()),
        'max_pos': _pos(xmax, ymax),
        'min_pos': _pos(xmin, ymin),
    }


class RoiSet:
    'thread safe, ordered set of ROIs, optionally persisted to a JSON file'

    def __init__(self, shape, path=None):
        self.shape = shape
        self.path = path
        self._lock = threading.Lock()
        self._rois = {}
        if path and os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                for d in json.load(f):
                    roi = Roi.from_dict(d, shape)
                    self._rois[roi.id] = roi

    def _save(self):
        if not self.path:
            return
        tmp = self.path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump([r.to_dict() for r in self._rois.values()], f, indent=1, ensure_ascii=False)
        os.replace(tmp, self.path)

    def snapshot(self):
        'list of the current ROIs (the ROI objects are immutable)'
        with self._lock:
            return list(self._rois.values())

    def definitions(self):
        return [r.to_dict() for r in self.snapshot()]

    def _next_id(self, kind):
        prefix = {'point': 'P', 'rect': 'R', 'circle': 'C'}.get(kind, 'A')
        n = 1
        while f'{prefix}{n}' in self._rois:
            n += 1
        return f'{prefix}{n}'

    def add(self, d):
        'adds a ROI from its definition. A missing/empty id is generated (P1, R1, C1, ...). Returns the definition'
        if isinstance(d, dict) and not str(d.get('id') or '').strip():
            with self._lock:
                d = {**d, 'id': self._next_id(d.get('type'))}
        roi = Roi.from_dict(d, self.shape)
        with self._lock:
            if roi.id in self._rois:
                raise RoiError(f'id "{roi.id}" already exists')
            self._rois[roi.id] = roi
            self._save()
        return roi.to_dict()

    def remove(self, roi_id):
        'removes the ROI (and with it its id). Returns False if it does not exist'
        with self._lock:
            if roi_id not in self._rois:
                return False
            del self._rois[roi_id]
            self._save()
            return True

    def clear(self):
        with self._lock:
            n = len(self._rois)
            self._rois.clear()
            self._save()
            return n


def build_message(temp, rois, ts_ms, frame_no):
    'the data stream message of one frame'
    h, w = temp.shape
    return {
        'ts': int(ts_ms),
        'frame': int(frame_no),
        'unit': 'C',
        'width': int(w),
        'height': int(h),
        'global': global_stats(temp),
        'rois': [r.stats(temp) for r in rois],
    }
