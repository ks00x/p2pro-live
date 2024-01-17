# P2ProLiveApp

Getting the raw and video streams out of an Infiray P2Pro thermal camera and having a live thermal display on the Windows PC (Linux should work as well if the device id is changed)

work in progress...


Conda environment settings for Windows
```
conda create -n p2pro python
activate p2pro
pip install opencv-python pyusb pyaudio  ffmpeg-python pillow streamlit
```

## features
- runs on windows without special drivers
- auto and manual scaling of the temperature to color mapping
- in image live display of max,min and center temperature
- history chart function for min,max,avg,center temperature 
- save history to csv
- save image to csv
- (still) image viewer with zoom etc

run with:
`streamlit run p2prolive_app.py`

![](/media/screenshot.png)