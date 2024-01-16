# P2ProLiveApp

Getting the raw and video streams out of an Infiray P2Pro thermal camera and having a live thermal display on the Windows PC (Linux should work as well if the device id is changed)

work in progress...


Conda environment settings for Windows
```
conda create -n p2pro python
activate p2pro
pip install opencv-python pyusb pyaudio  ffmpeg-python
```

run with:
`streamlit run p2prolive_app.py`

![](/media/screenshot.jpg)