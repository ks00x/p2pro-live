'''
Video recorder for the P2Pro stream.

Writes one .mkv file with two video tracks:
  stream 0: the displayed image (RGB, H.264 crf 16)
  stream 1: the raw 16 bit radiometric data (gray16le, FFV1 lossless), T[C] = raw/64 - 273.2

Adapted from P2Pro-Viewer by LeoDJ, https://github.com/LeoDJ/P2Pro-Viewer
(P2Pro/recorder.py), MIT License, Copyright (c) 2023 LeoDJ.
Changes: no audio track, frames are pushed with write() instead of read from a queue,
ffmpeg logs are collected per process, load_radiometry() to read the data back.

Needs the ffmpeg executable in the PATH and the ffmpeg-python package.
'''
import os
import time
import subprocess

import numpy as np
import ffmpeg


class RecorderError(RuntimeError):
    pass


class ThermalRecorder:

    def __init__(self, path: str, radiometry: bool = True):
        ''':param path: output file name without extension, the result is <path>.mkv'''
        self.path = path
        self.with_radiometry = radiometry
        self.frames = 0
        self.t_start = time.time()
        self._proc_rgb = None
        self._proc_therm = None
        self._rgb_shape = None
        self._raw_shape = None
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)

    @staticmethod
    def _open(path, in_pix_fmt, shape, **output_args) -> subprocess.Popen:
        return (
            ffmpeg
            .input('pipe:', format='rawvideo', pix_fmt=in_pix_fmt, s=f'{shape[1]}x{shape[0]}', use_wallclock_as_timestamps='1')
            .output(path, **output_args)
            .global_args('-hide_banner', '-loglevel', 'error', '-nostats')
            .overwrite_output()
            .run_async(pipe_stdin=True, pipe_stderr=True)
        )

    def write(self, rgb, raw=None):
        '''add one frame.
        :param rgb: H x W x 3 uint8 image (what is shown on screen)
        :param raw: H x W 16 bit raw camera data (required if radiometry is True)'''
        rgb = np.ascontiguousarray(rgb, dtype=np.uint8)
        if self._proc_rgb is None: # open the encoders lazily, the frame sizes are known now
            if rgb.ndim != 3 or rgb.shape[2] != 3 or rgb.shape[0] % 2 or rgb.shape[1] % 2:
                raise RecorderError(f'rgb frame must be H x W x 3 with even H and W, got {rgb.shape}')
            self._rgb_shape = rgb.shape
            self._proc_rgb = self._open(self.path + '.rgb.mkv', 'rgb24', rgb.shape, vcodec='libx264', crf='16', pix_fmt='yuv420p')
            if self.with_radiometry:
                if raw is None:
                    raise RecorderError('radiometry recording needs the raw data')
                self._raw_shape = np.shape(raw)
                self._proc_therm = self._open(self.path + '.therm.mkv', 'gray16le', self._raw_shape, vcodec='ffv1')
            self.t_start = time.time()
        if rgb.shape != self._rgb_shape:
            raise RecorderError(f'frame size changed during recording ({self._rgb_shape} -> {rgb.shape})')
        self._proc_rgb.stdin.write(rgb.tobytes())
        if self.with_radiometry:
            if np.shape(raw) != self._raw_shape:
                raise RecorderError(f'raw size changed during recording ({self._raw_shape} -> {np.shape(raw)})')
            self._proc_therm.stdin.write(np.asarray(raw).astype('<u2').tobytes())
        self.frames += 1

    def elapsed(self):
        return time.time() - self.t_start

    @staticmethod
    def _finish(proc):
        _, err = proc.communicate() # closes stdin and waits for ffmpeg
        if proc.returncode != 0:
            raise RecorderError(f'ffmpeg failed ({proc.returncode}): {err.decode(errors="replace").strip()}')

    def stop(self):
        '''finish the recording and merge the tracks.
        :return: path of the .mkv file or None if no frame was written'''
        if self._proc_rgb is None:
            return None
        procs = [self._proc_rgb] + ([self._proc_therm] if self.with_radiometry else [])
        self._proc_rgb = self._proc_therm = None
        for p in procs:
            self._finish(p)

        tmp = [self.path + '.rgb.mkv'] + ([self.path + '.therm.mkv'] if self.with_radiometry else [])
        out = self.path + '.mkv'
        try:
            (
                ffmpeg
                .output(*[ffmpeg.input(f) for f in tmp], out, vcodec='copy', map_metadata=-1)
                .global_args('-hide_banner', '-loglevel', 'error')
                .run(overwrite_output=True, capture_stdout=True, capture_stderr=True)
            )
        except ffmpeg.Error as ex:
            raise RecorderError(f'merging failed: {ex.stderr.decode(errors="replace").strip()}') from ex
        for f in tmp:
            try:
                os.remove(f)
            except FileNotFoundError:
                pass
        return out


def load_radiometry(path, shape=(192, 256)):
    '''reads the radiometric track (stream 1) of a recording made with ThermalRecorder
    :return: (frames, H, W) array of the raw 16 bit values, use p2pro.raw_to_celsius() for temperatures'''
    out, _ = (
        ffmpeg
        .input(path)
        .output('pipe:', map='0:v:1', format='rawvideo', pix_fmt='gray16le', vsync='passthrough') # no duplicated frames
        .global_args('-hide_banner', '-loglevel', 'error')
        .run(capture_stdout=True, capture_stderr=True)
    )
    return np.frombuffer(out, dtype='<u2').reshape((-1,) + tuple(shape))
