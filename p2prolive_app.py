import streamlit as st
import numpy as np
import time
import cv2
from PIL import Image
import matplotlib.pyplot as plt

from p2pro import p2pro
from extras import find_tmin,find_tmax,draw_annotation

cmaplist = ['viridis', 'plasma', 'inferno', 'magma', 'cividis','hot','afmhot','gray','tab20c']

with st.sidebar:
    id = st.number_input('camera id',value=0)
    width = st.number_input('image width',value=800,step=50)
    transpose = st.checkbox('transpose image',value=False)
    colormap = st.selectbox('colormap',cmaplist)
    annotations = st.checkbox('show min max temp cursors',value=True)
    showvideo = st.checkbox('show normal video stream',value=False)
    wait_delay = st.number_input('wait delay ms',value=0,min_value=0,step=10,help='add to delay to reduce framerate and lower cpu usage')
    autoscale = st.checkbox('autoscale',value=True)
    tmax = st.number_input('max T',value=60)
    tmin = st.number_input('min T',value=20)

@st.cache_resource
def init():
    return p2pro(id)

p2 = init()

col1,col2,col3 = st.columns((1,2,2))
brightness = col1.slider('brightness',value=0.,min_value=0.,max_value=1.)
contrast = col2.slider('contrast',value=0.95,min_value=0.1,max_value=1.)
sharp = col3.slider('sharpness',value=0,min_value=-6,max_value=1)

info = st.empty() 
img = st.empty()
img2 = st.empty()

cm_hot = plt.get_cmap(colormap)
    
while True:    

    temp = p2.temperature()  
    
    if transpose :
        temp = temp.T  
    if annotations :  
        idxmax,ma = find_tmax(temp)
        idxmin,mi = find_tmin(temp)

    c1,c2,c3 = info.columns(3)
    c1.metric('min',value=f"{temp.min():1.4}C")
    c2.metric('max',value=f"{temp.max():1.4}C")
    c3.metric('avg',value=f"{temp.mean():1.4}C")
    
    # from here on we start to mod the temp data!
    if sharp < 0:
        temp = cv2.blur(temp, (-sharp+1,-sharp+1)) 
    if sharp >= 1 :
        kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
        temp = cv2.filter2D(temp, -1, kernel)        
    
    if autoscale :
        temp = (temp-temp.min())/(temp.max()-temp.min()) * contrast + brightness
    else :        
        temp = (temp-tmin)/(tmax-tmin) * contrast + brightness
    
    temp = cm_hot(temp)
    temp = np.uint8(temp * 255)
    im = Image.fromarray(temp)    
               
    if annotations :    
        draw_annotation(im,idxmax,f'{ma:1.2f}C')
        draw_annotation(im,idxmin,f'{mi:1.2f}C',color='lightblue')
           
    img.image(im,width=width,clamp=True,) # show the image
                      
    if showvideo :
        v = p2.video()
        if transpose :
            v = v.T
        img2.image(v,width=width,clamp=True,)

    time.sleep(wait_delay/1000.)
        
