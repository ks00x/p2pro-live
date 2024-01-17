import streamlit as st
import numpy as np
import time
import cv2
from PIL import Image
import plotly.express as px
import matplotlib.pyplot as plt
from history import history
from p2pro import p2pro
from extras import find_tmin,find_tmax,draw_annotation,rotate,preserve_sessionstate
import help

st.set_page_config('P2Pro LIVE',initial_sidebar_state='expanded',page_icon='🔺')
session = st.session_state

cmaplist = ['viridis', 'plasma', 'inferno', 'magma', 'cividis','hot','afmhot','gray','tab20c']
HISTORY_LEN =  10000 # length of the history buffer in samples
if 'history' not in session : # init and set default values for sidebar controls
    session.history = history(maxitems=HISTORY_LEN,columns=4)
    session.tsr = 2.
    session.id = '1'
    session.brightness = 0.
    session.contrast = 1.
    session.sharp = 0
    session.rot = 0
    session.annotations = True
    session.autoscale = True
    session.tmin = 20.
    session.tmax = 60
    session.timeline = False
    session.show_min = True
    session.show_max = True
    session.show_mean = True
    session.show_center = True
    session.trange = 500.
    session.toff = 0.
    session.width = 600
    session.cheight = 300
    session.wait_delay = 50
    session.t_units = 's'
else :
    preserve_sessionstate(session)

def restart():
    init.clear()    

with st.sidebar:
    with st.expander('image controls',expanded=True):
        st.slider('brightness',min_value=0.,max_value=1.,key='brightness')
        st.slider('contrast',min_value=0.1,max_value=1.,key='contrast')
        st.slider('sharpness',min_value=-6,max_value=1,key='sharp')
        st.selectbox('rotate image',(0,90,180,270),index=0,key='rot')
        st.selectbox('colormap',cmaplist,key='colormap')
        st.checkbox('show min max temp cursors',key='annotations')
        st.checkbox('show normal video stream',key='showvideo')
    st.checkbox('autoscale',key='autoscale')    
    st.number_input('max T',key='tmax')
    st.number_input('min T',key='tmin')    
    with st.expander('history settings',expanded=session.timeline):
        st.checkbox('show history timeline',key='timeline')
        c1,c2,c3 = st.columns(3)
        c1.checkbox('min',key='show_min')
        c2.checkbox('max',key='show_max')
        c3.checkbox('mean',key='show_mean')
        c1,_,_ = st.columns(3)
        c1.checkbox('center',key='show_center')
        st.number_input('time range in s',help=help.history_timerange,key='trange')
        st.slider('time offset in s',min_value=0.,max_value=3600.,key='toff')      
        st.radio('time units',('s','m'),horizontal=True,key='t_units')        
        st.number_input('history sample rate HZ',value=2.,max_value=10.,min_value=0.1,key='tsr')      
        if st.button('clear history') :
            session.history.clear()            
    with st.expander('more settings'):
        st.text_input('camera id',on_change=restart,key='id',help=help.cam_id)
        st.number_input('image width',step=50,key='width')
        st.number_input('chart height',step=50,key='cheight')
        st.number_input('wait delay ms',min_value=0,step=10,help=help.history_wait_delay,key='wait_delay')

@st.cache_resource
def init():
    p2 = p2pro(session.id)
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

cm_hot = plt.get_cmap(session.colormap)   
tc0 = th0 =  time.time()            
    
while True:    # main aquisition loop
       
    temp = p2.temperature()  
    temp = rotate(temp,session.rot)
    session.last_image = temp
    
    if session.annotations :  
        idxmax,ma = find_tmax(temp)
        idxmin,mi = find_tmin(temp)
        idc = (temp.shape[1]//2,temp.shape[0]//2)
        mc = temp[idc]

    stat = (temp.min(),temp.max(),temp.mean(),mc)  
    if time.time() - th0 > 1/session.tsr : 
        session.history.add(stat)
        th0 = time.time()
    if session.timeline and (time.time() - tc0 > 0.5):# The chart display increases cpu load. ~2 updates/s                
        data = session.history.timerange(session.trange,session.toff,max_samples=1024)                
        fig = px.line(x=None, y=None,height=session.cheight)  
        if session.t_units == 'm' : 
            t = data[0]/60         
            labels = {'xaxis_title':"time in minutes",'yaxis_title':"temperature in C"}
        else :
            t = data[0]
            labels = {'xaxis_title':"time in seconds",'yaxis_title':"temperature in C"}    
        fig.update_layout(labels)
        if session.show_min : fig.add_scatter(x=t, y=data[1],mode='lines',name='min',line=dict(color="blue"))
        if session.show_max : fig.add_scatter(x=t, y=data[2],mode='lines',name='max',line=dict(color="red"))
        if session.show_mean : fig.add_scatter(x=t, y=data[3],mode='lines',name='mean',line=dict(color="green"))        
        if session.show_center : fig.add_scatter(x=t, y=data[4],mode='lines',name='center',line=dict(color="orange"))        
        chart.plotly_chart(fig)
        tc0 = time.time()

    c1,c2,c3,c4 = info.columns(4)
    c1.metric('min',value=f"{stat[0]:1.4}C")
    c2.metric('max',value=f"{stat[1]:1.4}C")
    c3.metric('avg',value=f"{stat[2]:1.4}C")
    c4.metric('center',value=f"{stat[3]:1.4}C")
    
    # from here on we start to mod the temp data!
    if session.sharp < 0:
        temp = cv2.blur(temp, (-session.sharp+1,-session.sharp+1)) 
    if session.sharp >= 1 :
        kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
        temp = cv2.filter2D(temp, -1, kernel)        
    
    if session.autoscale :
        temp = (temp-stat[0])/(stat[1]-stat[0]) * session.contrast + session.brightness
    else :        
        temp = (temp-session.tmin)/(session.tmax-session.tmin) * session.contrast + session.brightness
    
    # trick to use the matplotlib colormaps with PIL
    temp = cm_hot(temp)
    temp = np.uint8(temp * 255)
    im = Image.fromarray(temp)    
               
    if session.annotations :    
        draw_annotation(im,idxmax,f'{ma:1.2f}C')
        draw_annotation(im,idxmin,f'{mi:1.2f}C',color='lightblue')
        draw_annotation(im,idc,f'{mc:1.2f}C',color='lightblue')
           
    img.image(im,width=session.width,clamp=True,) # show the image
                      
    if session.showvideo :
        v = p2.video()
        v = rotate(v,session.rot)
        img2.image(v,width=session.width,clamp=True,)

    time.sleep(session.wait_delay/1000.)
            
