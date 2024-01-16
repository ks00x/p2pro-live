import streamlit as st
import numpy as np
import time
import cv2
from PIL import Image
import plotly.express as px
import matplotlib.pyplot as plt
from history import history
from p2pro import p2pro
from extras import find_tmin,find_tmax,draw_annotation

st.set_page_config('P2Pro LIVE',initial_sidebar_state='expanded',page_icon='🔺')
session = st.session_state
history_len =  10000
if 'history' not in session :
    session.history = history(maxitems=history_len,columns=3)
cmaplist = ['viridis', 'plasma', 'inferno', 'magma', 'cividis','hot','afmhot','gray','tab20c']

def restart():
    init.clear()    

with st.sidebar:
    id = st.number_input('camera id',value=1,on_change=restart)
    brightness = st.slider('brightness',value=0.,min_value=0.,max_value=1.)
    contrast = st.slider('contrast',value=0.95,min_value=0.1,max_value=1.)
    sharp = st.slider('sharpness',value=0,min_value=-6,max_value=1)
    rot = st.selectbox('rotate image',(0,90,180,270),index=0)
    colormap = st.selectbox('colormap',cmaplist)
    annotations = st.checkbox('show min max temp cursors',value=True)
    showvideo = st.checkbox('show normal video stream',value=False)
    autoscale = st.checkbox('autoscale',value=True)    
    tmax = st.number_input('max T',value=60)
    tmin = st.number_input('min T',value=20)
    st.write('---')
    timeline = st.checkbox('show history timeline',value=False)
    if timeline :
        c1,c2,c3 = st.columns(3)
        show_min = c1.checkbox('min',value=True)
        show_max = c2.checkbox('max',value=True)
        show_mean = c3.checkbox('mean',value=True)
        trange = st.number_input('time range in s',value=500)
        toff = st.slider('time offset in s',value=0.,min_value=0.,max_value=3600.)            
        if st.button('clear history') :
            session.history.clear()            
    st.write('---')
    width = st.number_input('image width',value=600,step=50)
    cheight = st.number_input('chart height',value=300,step=50)
    wait_delay = st.number_input('wait delay ms',value=50,min_value=0,step=10,help='add to delay to reduce framerate and lower cpu usage')

@st.cache_resource
def init():
    p2 = p2pro(id)
    try:
        p2.raw()
    except Exception:
        st.error('this seems to be no P2Pro cam ☹')
    return p2

p2 = init()

##### define placeholders for the loop output:
info = st.empty() 
chart = st.empty()
img = st.empty()
img2 = st.empty()

cm_hot = plt.get_cmap(colormap)   
tc0 = time.time()            
th0 = time.time() 
    
while True:    

    def rotate(temp,rot):        
        if rot == 90 : return np.rot90(temp,1)
        if rot == 180 : return np.rot90(temp,2)
        if rot == 270 : return np.rot90(temp,3)
        return temp
    
    temp = p2.temperature()  
    temp = rotate(temp,rot)
    
    if annotations :  
        idxmax,ma = find_tmax(temp)
        idxmin,mi = find_tmin(temp)

    stat = (temp.min(),temp.max(),temp.mean())  
    if time.time() - th0 > 0.2 : # 200ms minimum spacing between data
        session.history.add(stat)
        th0 = time.time()
    if timeline and (time.time() - tc0 > 0.5):# The chart display increases cpu load. ~2 updates/s                
        data = session.history.timerange(trange,toff,max_samples=500)                
        fig = px.line(x=None, y=None,height=cheight)            
        if show_min : fig.add_scatter(x=data[0], y=data[1],mode='lines',name='min',line=dict(color="blue"))
        if show_max : fig.add_scatter(x=data[0], y=data[2],mode='lines',name='max',line=dict(color="red"))
        if show_mean : fig.add_scatter(x=data[0], y=data[3],mode='lines',name='mean',line=dict(color="black"))
        labels = {'xaxis_title':"time in seconds",'yaxis_title':"temperature in C"}
        fig.update_layout(labels)
        chart.plotly_chart(fig)
        tc0 = time.time()


    c1,c2,c3 = info.columns(3)
    c1.metric('min',value=f"{stat[0]:1.4}C")
    c2.metric('max',value=f"{stat[1]:1.4}C")
    c3.metric('avg',value=f"{stat[2]:1.4}C")
    
    # from here on we start to mod the temp data!
    if sharp < 0:
        temp = cv2.blur(temp, (-sharp+1,-sharp+1)) 
    if sharp >= 1 :
        kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
        temp = cv2.filter2D(temp, -1, kernel)        
    
    if autoscale :
        temp = (temp-stat[0])/(stat[1]-stat[0]) * contrast + brightness
    else :        
        temp = (temp-tmin)/(tmax-tmin) * contrast + brightness
    
    # trick to use the matplotlib colormaps with PIL
    temp = cm_hot(temp)
    temp = np.uint8(temp * 255)
    im = Image.fromarray(temp)    
               
    if annotations :    
        draw_annotation(im,idxmax,f'{ma:1.2f}C')
        draw_annotation(im,idxmin,f'{mi:1.2f}C',color='lightblue')
           
    img.image(im,width=width,clamp=True,) # show the image
                      
    if showvideo :
        v = p2.video()
        v = rotate(v,rot)
        img2.image(v,width=width,clamp=True,)

    time.sleep(wait_delay/1000.)
            
