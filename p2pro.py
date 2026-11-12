import cv2
import numpy as np
import platform
import glob
import os
import time
import re

'''
with info from , check out:
https://www.eevblog.com/forum/thermal-imaging/infiray-and-their-p2-pro-discussion/200/
https://github.com/leswright1977/PyThermalCamera/blob/main/src/tc001v4.2.py
https://github.com/LeoDJ/P2Pro-Viewer (USB id detection, YUY2 video decoding, USB commands, recorder)

I did create a seperate conda env for this project on Windows:
conda create -n p2pro python
activate p2pro
pip install opencv-python pyusb pyaudio  ffmpeg-python

tested with cv2 4.8.0
'''

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
                raise RuntimeError('No P2Pro camera found (USB id 0bda:5830). Pass the camera id explicitly.')
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

    @staticmethod
    def is_compatible_frame(frame):
        'quick compatibility check used during camera scan'
        try:
            p2pro._decode_stacked_frame(frame)
            return True
        except Exception:
            return False

    def get_frame(self):
        'reads one decoded frame (rows x 256 x 2 bytes). Use the frame_* methods to extract the data from it'
        for _ in range(3):
            # Drop buffered frames to reduce display latency.
            for _ in range(2):
                self.cap.grab()
            ret, frame = self.cap.retrieve()
            if not ret or frame is None:
                ret, frame = self.cap.read()
            if ret and frame is not None:
                try:
                    decoded = self._decode_stacked_frame(frame)
                    self._last_frame = decoded
                    return decoded
                except RuntimeError:
                    pass
            time.sleep(0.01)

        if self._last_frame is not None:
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

    @staticmethod
    def frame_video(frame):
        'normal 8bit video (luma) of the upper half of a frame from get_frame()'
        return frame[:P2PRO_ROWS,:,0] # upper image part, lower byte

    @staticmethod
    def frame_video_rgb(frame):
        '''RGB video (192 x 256 x 3, uint8) of the upper half of a frame from get_frame().
        The upper half is YUY2 encoded and uses the camera pseudo color palette (see p2pro_cmd).
        Falls back to the gray luma image if the frame has no separate video half.'''
        if frame.shape[0] < 2 * P2PRO_ROWS:
            return cv2.cvtColor(np.ascontiguousarray(frame[:P2PRO_ROWS,:,0]), cv2.COLOR_GRAY2RGB)
        return cv2.cvtColor(np.ascontiguousarray(frame[:P2PRO_ROWS]), cv2.COLOR_YUV2RGB_YUY2)

    def raw(self):
        'returns the raw 16bit int image'
        return self.frame_raw(self.get_frame())

    def video(self):
        'returns the normal 8bit video stream from the upper half'
        return self.frame_video(self.get_frame())

    def video_rgb(self):
        'returns the RGB video stream (camera pseudo color) from the upper half'
        return self.frame_video_rgb(self.get_frame())

    def temperature(self):
        'returns the image as temperature map in Celsius'
        return self.frame_temperature(self.get_frame())

    def __del__(self):
        if hasattr(self, 'cap') and self.cap is not None:
            self.cap.release()


def main():
    import time

    def configure_opencv_qt_fonts():
        if platform.system() != 'Linux':
            return
        font_dir = '/usr/share/fonts/truetype/dejavu'
        if os.path.isdir(font_dir):
            os.environ.setdefault('QT_QPA_FONTDIR', font_dir)

    configure_opencv_qt_fonts()

    def open_capture(cam_id):
        if platform.system() == 'Windows':
            return cv2.VideoCapture(int(cam_id))
        return cv2.VideoCapture(cam_id)

    def scan_video_ports(max_indices=10):
        'returns list of readable camera ids for current platform'
        ids = find_p2pro_devices() # Linux: found by USB id, no probing needed
        if len(ids) > 0:
            return ids
        if platform.system() == 'Windows':
            candidates = [str(i) for i in range(max_indices)]
        else:
            candidates = sorted(glob.glob('/dev/video*'))

        for cid in candidates:
            cap = open_capture(cid)
            ok, frame = cap.read()
            cap.release()
            if ok and frame is not None and p2pro.is_compatible_frame(frame):
                ids.append(cid)
        return ids

    def select_camera_port():
        ids = scan_video_ports()
        if len(ids) == 0:
            fallback = '0' if platform.system() == 'Windows' else '/dev/video0'
            typed = input(f'No readable video ports found. Enter camera id manually [{fallback}]: ').strip()
            return typed or fallback

        print('Detected video ports:')
        for i, cid in enumerate(ids):
            print(f'  [{i}] {cid}')
        if len(ids) == 1:
            return ids[0]

        while True:
            typed = input('Select camera index [0]: ').strip()
            if typed == '':
                return ids[0]
            if typed.isdigit() and int(typed) < len(ids):
                return ids[int(typed)]
            print(f'Invalid selection: {typed}. Enter a number between 0 and {len(ids)-1}.')

    cam_id = select_camera_port()
    print(f'Using camera port: {cam_id}')
    p2 = p2pro(cam_id)
    i = 0

    while(True):
        t0 = time.perf_counter()
        frame = p2.get_frame()
        temp = p2.frame_temperature(frame)
        t1 = time.perf_counter()
        ct = (t1-t0)*1000
        i += 1
        if i%20 == 0 :
            print(f"min = {temp.min():1.4}, max = {temp.max():1.4}, avg = {temp.mean():0.4}, cpu secs read = {ct:1.2f}ms")

        brightness = 0.01
        contrast = 0.95
        temp = temp.T # transpose image if needed
        # values scaled to [0,1] range
        cv2.imshow('p2pro temperature',(temp-temp.min())/(temp.max()-temp.min()) * contrast + brightness)
        v = p2.frame_video_rgb(frame)
        cv2.imshow('video',cv2.cvtColor(v.transpose(1,0,2), cv2.COLOR_RGB2BGR))

        #Waits for a user input to quit the application
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
    cv2.destroyAllWindows()


if __name__ == '__main__':
    main()
