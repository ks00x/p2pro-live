import numpy as np
import streamlit as st
import io
import plotly.express as px
from datetime import datetime
from extras import preserve_sessionstate,np_to_csv_stream,c_to_f

st.set_page_config('Infiray P2Pro viewer',initial_sidebar_state="expanded",page_icon='🌡',layout='wide')
session = st.session_state
preserve_sessionstate(session)

with st.sidebar:    
    colorscales = px.colors.named_colorscales()
    units = st.selectbox('units',('Celsius','Fahrenheit'),index=0)
    fahrenheit = False
    if units == 'Fahrenheit' : fahrenheit = True
    colorscale = st.selectbox('color map',colorscales,index=21) 
    rotation = st.selectbox('rotate image',(0,90,180,270))        
    height = st.number_input('image height',value=1200,step=100)    
    autoscale = st.checkbox('autoscale',value=True)
    tmin = st.number_input('min temp',value=0)
    tmax = st.number_input('max temp',value=60)


im = session.last_image
if rotation == 90 :
    im = np.rot90(im)  
if rotation == 180 :
    im = np.rot90(im,2)  
if rotation == 270 :
    im = np.rot90(im,3)          

if fahrenheit :
    title = 'Temperature in Fahrenheit from raw data'
    im = c_to_f(im)
else :
    title = 'Temperature in Celsius from raw data'

csv = np_to_csv_stream(im) 
st.download_button('download csv file',data=csv,file_name=f'{datetime.now():%Y-%m-%d_%H:%M:%S}_p2pro.csv')  

if autoscale :
    fig = px.imshow(im,aspect='equal',color_continuous_scale=colorscale,title=title) 
else :
    fig = px.imshow(im,aspect='equal',color_continuous_scale=colorscale,title=title,zmin=session.tmin,zmax=session.tmax)  

fig.update_layout(height=height)
st.plotly_chart(fig,use_container_width=True)
st.write(f"min = {im.min():1.2f}, max = {im.max():1.2f}, mean = {im.mean():1.2f}")
    
    
