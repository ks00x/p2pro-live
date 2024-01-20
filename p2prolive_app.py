import streamlit as st
import numpy as np
import time
import cv2
from PIL import Image
import plotly.express as px
import matplotlib.pyplot as plt
from history import history
from p2pro import p2pro
from extras import find_tmin,find_tmax,draw_annotation,rotate,preserve_sessionstate,colorbarfig,mytimer
import help
import sys

st.set_page_config('P2Pro LIVE',initial_sidebar_state='expanded',page_icon='🔺',layout='wide')
session = st.session_state

# https://matplotlib.org/stable/gallery/color/colormap_reference.html
cmaplist = ['jet','gray','bone', 'cividis','rainbow','terrain','nipy_spectral','gist_ncar','brg','hot','plasma', 'viridis','inferno', 'magma','afmhot','tab20c']

HISTORY_LEN =  10000 # length of the history buffer in samples
if 'history' not in session : # init and set default values for sidebar controls
    session.history = history(maxitems=HISTORY_LEN,columns=4)
    session.tsr = 2.
    session.id = '1'
    session.brightness = 0.
    session.contrast = 1.
    session.sharp = 0
    session.rotate = 0
    session.annotations = True
    session.autoscale = True
    session.tmin = 20.
    session.tmax = 60
    session.timeline = True
    session.show_min = True
    session.show_max = True
    session.show_mean = True
    session.show_center = True
    session.trange = 500.
    session.toff = 0.
    session.width = 0
    session.cheight = 300
    session.wait_delay = 50
    session.t_units = 's'
    session.showscale = True

    if len(sys.argv) > 1 : # cmdline overwrite for the device id, use '--' in front of the argument!
        session.id = sys.argv[1]

else :    
    preserve_sessionstate(session)    

def restart():
    init.clear()    

with st.sidebar:
    with st.expander('color scaling',expanded=True):
        st.checkbox('autoscale',key='autoscale')    
        st.number_input('max T',key='tmax')
        st.number_input('min T',key='tmin')    
        st.selectbox('colormap',cmaplist,key='colormap')
    with st.expander('image controls',expanded=True):
        # st.slider('brightness',min_value=0.,max_value=1.,key='brightness')
        # st.slider('contrast',min_value=0.1,max_value=1.,key='contrast')
        st.slider('sharpness',min_value=-6,max_value=1,key='sharp')
        st.selectbox('rotate image',(0,90,180,270),key='rotate')
        st.checkbox('show min max temp cursors',key='annotations')
        st.checkbox('show color scale',key='showscale')
        st.checkbox('show normal video stream',key='showvideo')
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
        st.number_input('history sample rate Hz',max_value=10.,min_value=0.1,key='tsr',help=help.tsr)      
        if st.button('clear history') :
            session.history.clear()            
    with st.expander('more settings'):
        st.text_input('camera id',on_change=restart,key='id',help=help.cam_id)
        st.number_input('image width',step=50,key='width',help=help.image_width)
        st.number_input('chart height',step=50,key='cheight')
        st.number_input('wait delay ms',min_value=0,step=10,help=help.history_wait_delay,key='wait_delay')

@st.cache_resource
def init():
    p2 = p2pro(session.id)
    try:
        p2.raw()
    except Exception:
        st.error(f'this seems to be no P2Pro cam ☹. Check the camera id string, currently: {session.id}')
    return p2

p2 = init()

##### define placeholders for the loop output:
info = st.empty() 
chart = st.empty()
if session.showscale :
    c1,c2 = st.columns((0.9,0.1))
    img = c1.empty()
    img_cbar = c2.empty()
else: 
    img = st.empty()
img2 = st.empty()

cm_hot = plt.get_cmap(session.colormap)     
tm = mytimer()       
tm.add('chart',1/session.tsr)
tm.add('history',1/session.tsr)
tm.add('colorbar',0.5)
tm.add('restart',500)

    
while True:    # main aquisition loop
        
    temp = p2.temperature()  
    temp = rotate(temp,session.rotate)
    session.last_image = temp
       
    if session.annotations :  
        idxmax,ma = find_tmax(temp)
        idxmin,mi = find_tmin(temp)
    idc = (temp.shape[1]//2,temp.shape[0]//2)
    mc = temp[idc[::-1]] # why is that reverse needed???

    stat = (temp.min(),temp.max(),temp.mean(),mc)  
    if tm.check('history') : # add history data
        session.history.add(stat)        

    if session.timeline and tm.check('chart'):# The chart display increases cpu load. ~2 updates/s                
        data = session.history.timerange(session.trange,session.toff,max_samples=1024)            
        if data is not None:    
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
            chart.plotly_chart(fig,use_container_width=True)
            
    
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
        if session.showscale and tm.check('colorbar') :
            f = colorbarfig(stat[0],stat[1],session.colormap)
            img_cbar.pyplot(f)            
            del f            
    else :        
        temp = (temp-session.tmin)/(session.tmax-session.tmin) * session.contrast + session.brightness
        if session.showscale and tm.check('colorbar'):
            f = colorbarfig(session.tmin,session.tmax,session.colormap)
            img_cbar.pyplot(f)            
            del f
    # trick to use the matplotlib colormaps with PIL
    temp = cm_hot(temp)    
    temp = np.uint8(temp * 255)
    im = Image.fromarray(temp)    
               
    if session.annotations :    
        draw_annotation(im,idxmax,f'{ma:1.2f}C')
        draw_annotation(im,idxmin,f'{mi:1.2f}C',color='lightblue')
        draw_annotation(im,idc,f'{mc:1.2f}C',color='lightblue')    

    if session.width  > 0 : 
        img.image(im,width=session.width,clamp=True,) 
    else :
        img.image(im,clamp=True,use_column_width=True)    
                      
    if session.showvideo :
        v = p2.video()
        v = rotate(v,session.rotate)        
        if session.width  > 0 : 
            img2.image(v,width=session.width,clamp=True,) 
        else :
            img2.image(v,clamp=True,use_column_width=True)

    time.sleep(session.wait_delay/1000.)

    if tm.check('restart') : # memory leak in streamlit
        st.rerun()
            
