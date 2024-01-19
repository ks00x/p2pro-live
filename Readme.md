# P2ProLiveApp

Getting the raw and video streams out of an Infiray P2Pro thermal camera and having a live thermal display on the Windows PC (Linux should work as well if the device id is changed)

work in progress...


Conda environment settings for Windows
```
conda create -n p2pro python
activate p2pro
pip install opencv-python pyusb pyaudio  ffmpeg-python pillow streamlit
# works well with streamlit 1.3
```

## features
- runs on windows without special drivers
- auto and manual scaling of the temperature to color mapping
- in image live display of max,min and center temperature
- history chart function for min,max,avg,center temperature 
- save history to csv
- save image to csv
- (still) image viewer with zoom etc

run with (activate the p2pro env first):
`streamlit run p2prolive_app.py`
You can specifiy the device id on the commandline:
`streamlit run p2prolive_app.py -- 0`

You may create a .bat file to activate the env and click start the web app (change the folders to match your installation, note the <&> operator):
```bat
activate p2pro & streamlit run d:\users\klaus\develop\python\misc\infiray\p2pro-live\p2prolive_app.py 
```


![](/media/screenshot.png)