'''
Infiray P2Pro camera driver: opens the UVC stream and decodes the raw temperature data.

with info from:
https://www.eevblog.com/forum/thermal-imaging/infiray-and-their-p2-pro-discussion/200/
https://github.com/leswright1977/PyThermalCamera/blob/main/src/tc001v4.2.py
https://github.com/LeoDJ/P2Pro-Viewer (USB id detection)

Each camera frame is 256 x 384 YUY2: the upper half is the camera video image, the lower half
the raw 16 bit temperature data, T[C] = raw/64 - 273.2.
'''

import cv2
import numpy as np
import platform
import glob
import os
import time
import re

P2PRO_USB_ID = (0x0bda, 0x5830)  # VID, PID
P2PRO_ROWS = 192   # rows of each image half (video on top, raw temperature data below)
P2PRO_COLS = 256

_VIDIOC_QUERYCAP = 0x80685600     # _IOR('V', 0, struct v4l2_capability), sizeof = 104
_V4L2_CAP_VIDEO_CAPTURE = 0x00000001
_V4L2_CAP_DEVICE_CAPS = 0x80000000


def _is_v4l2_capture_node(dev):
    'Linux: True if the /dev/videoN node can capture video (UVC cameras also expose a metadata node)'
    import fcntl
    try:
        fd = os.open(dev, os.O_RDWR | os.O_NONBLOCK)
    except OSError:
        return False
    try:
        buf = bytearray(104)
        fcntl.ioctl(fd, _VIDIOC_QUERYCAP, buf)
    except OSError:
        return False
    finally:
        os.close(fd)
    caps = int.from_bytes(buf[84:88], 'little')
    if caps & _V4L2_CAP_DEVICE_CAPS:
        caps = int.from_bytes(buf[88:92], 'little')  # caps of this node, not of the whole device
    return bool(caps & _V4L2_CAP_VIDEO_CAPTURE)


def find_p2pro_devices():
    '''Linux: returns the /dev/videoN capture nodes that belong to a P2Pro (USB VID:PID 0bda:5830).
    Returns an empty list on other platforms (there the device can only be found by probing frames).'''
    if platform.system() != 'Linux':
        return []
    found = []
    nodes = glob.glob('/sys/class/video4linux/video*')
    for node in sorted(nodes, key=lambda p: int(re.search(r'(\d+)$', p).group(1))):
        usb_dir = os.path.join(os.path.realpath(os.path.join(node, 'device')), '..')
        try:
            with open(os.path.join(usb_dir, 'idVendor')) as f:
                vid = int(f.read().strip(), 16)
            with open(os.path.join(usb_dir, 'idProduct')) as f:
                pid = int(f.read().strip(), 16)
        except (OSError, ValueError):
            continue  # not an usb device (or no access)
        dev = '/dev/' + os.path.basename(node)
        if (vid, pid) == P2PRO_USB_ID and _is_v4l2_capture_node(dev):
            found.append(dev)
    return found


class p2pro:

    def __init__(self,cam_id=None) -> None:
        '''module to read out the Infiray P2Pro camera
        cam_id: int index (Windows), /dev/videoN (Linux) or None to auto detect by USB id (Linux only)'''
        if cam_id is None:
            devices = find_p2pro_devices()
            if len(devices) == 0:
                raise RuntimeError('no P2Pro camera found (USB id 0bda:5830)')
            cam_id = devices[0]
        if platform.system() == 'Windows':
            cam_id = int(cam_id)
            self.cap = cv2.VideoCapture(cam_id)
        else:
            # Prefer V4L2 and numeric device index to avoid ffmpeg path quirks.
            if isinstance(cam_id, str):
                m = re.fullmatch(r'/dev/video(\d+)', cam_id)
                if m is not None:
                    self.cap = cv2.VideoCapture(int(m.group(1)), cv2.CAP_V4L2)
                else:
                    self.cap = cv2.VideoCapture(cam_id, cv2.CAP_V4L2)
            else:
                self.cap = cv2.VideoCapture(cam_id, cv2.CAP_V4L2)
        if not self.cap.isOpened():
            raise RuntimeError(f'Could not open camera port: {cam_id}')
        self.cam_id = cam_id
        self.cap.set(cv2.CAP_PROP_CONVERT_RGB, 0) # do not create rgb data!
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 256)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 384)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self._last_frame = None

    @staticmethod
    def _decode_stacked_frame(frame):
        'decode camera frame to rows x 256 x 2 based on total byte size'
        flat = np.asarray(frame, dtype=np.uint8).reshape(-1)
        row_bytes = 256 * 2
        if flat.size % row_bytes != 0:
            raise RuntimeError(
                f'Unsupported frame shape {np.asarray(frame).shape} with {flat.size} bytes. '
                'Expected byte-size multiple of 512.'
            )
        rows = flat.size // row_bytes
        decoded = flat.reshape(rows, 256, 2)
        if rows not in (192, 300, 384):
            raise RuntimeError(
                f'Unsupported frame rows: {rows}. Expected one of 192, 300, 384 for P2Pro.'
            )
        return decoded

    def get_frame(self, skip=1, allow_stale=True):
        '''reads one decoded frame (rows x 256 x 2 bytes). Use the frame_* methods to extract the data from it
        skip: buffered frames dropped before the returned one (reduces latency of slow readers, use 0 when
              reading continuously at the camera frame rate)
        allow_stale: if reading fails, return the last good frame instead of raising RuntimeError'''
        for _ in range(3):
            for _ in range(skip):
                self.cap.grab()
            ret, frame = self.cap.read()
            if ret and frame is not None:
                try:
                    decoded = self._decode_stacked_frame(frame)
                    self._last_frame = decoded
                    return decoded
                except RuntimeError:
                    pass
            time.sleep(0.01)

        if allow_stale and self._last_frame is not None:
            return self._last_frame

        raise RuntimeError('Could not read frame from camera stream.')

    @staticmethod
    def frame_raw(frame):
        'raw 16bit image (lower image part) of a frame from get_frame()'
        raw = frame[-P2PRO_ROWS:,:,:].astype(np.intc) # select only the lower image part
        raw = (raw[:,:,1] << 8) + raw[:,:,0] # assemble the 16bit word
        return raw

    @staticmethod
    def raw_to_celsius(raw):
        return raw/64 - 273.2 # convert to Celsius scale

    @staticmethod
    def frame_temperature(frame):
        'temperature map in Celsius of a frame from get_frame()'
        return p2pro.raw_to_celsius(p2pro.frame_raw(frame))

    def raw(self):
        'returns the raw 16bit int image'
        return self.frame_raw(self.get_frame())

    def temperature(self):
        'returns the image as temperature map in Celsius'
        return self.frame_temperature(self.get_frame())

    def __del__(self):
        if hasattr(self, 'cap') and self.cap is not None:
            self.cap.release()
