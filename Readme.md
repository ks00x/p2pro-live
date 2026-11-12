# P2ProLiveApp

Getting the raw and video streams out of an Infiray P2Pro thermal camera and having a live thermal display on the Windows PC (Linux should work as well if the device id is changed)

work in progress...


Conda environment settings for Windows
```powershell
conda create -n p2pro python
activate p2pro
pip install opencv-python pyusb pyaudio pillow plotly matplotlib streamlit
# works well with streamlit 1.3
```

On Linux use venv instead of conda and pip install the same packages. For example:
```bash
cd ~
mkdir venvs
# create the venv: 
python -m venv venvs/p2pro
# important - this command activates the venv:
source ~/venvs/p2pro/bin/activate
# to deactivate type: deactivate
pip install opencv-python pyusb pyaudio pillow plotly matplotlib streamlit==1.38
```

## features
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
