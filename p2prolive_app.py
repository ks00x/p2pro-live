import streamlit as st
import numpy as np
import time
import cv2
import glob
import os
from datetime import datetime
from PIL import Image
import plotly.express as px
import matplotlib.pyplot as plt
from history import history
from p2pro import p2pro, find_p2pro_devices
import p2pro_cmd
from recorder import ThermalRecorder, RecorderError
from extras import find_tmin,find_tmax,draw_annotation,rotate,preserve_sessionstate,colorbarfig,mytimer
import help
import sys
import platform

st.set_page_config('P2Pro LIVE',initial_sidebar_state='expanded',page_icon='🔺',layout='wide')
session = st.session_state

REC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'recordings')
# camera pseudo color palettes for the camera video stream (PSEUDO_RESERVED is not a palette)
PALETTES = [c.name for c in p2pro_cmd.PseudoColorTypes if c != p2pro_cmd.PseudoColorTypes.PSEUDO_RESERVED]


def scan_video_ports(max_indices=10):
    'returns available camera ids for current platform, on Linux P2Pro devices found by USB id come first'
    if platform.system() == 'Windows':
        return [str(i) for i in range(max_indices)]
    found = find_p2pro_devices()
    if len(found) > 0:
        return found
    return sorted(glob.glob('/dev/video*'))

# https://matplotlib.org/stable/gallery/color/colormap_reference.html
cmaplist = ['jet','gray','bone', 'cividis','rainbow','terrain','nipy_spectral','gist_ncar','brg','hot','plasma', 'viridis','inferno', 'magma','afmhot','tab20c']

HISTORY_LEN =  10000 # length of the history buffer in samples
if 'history' not in session : # init and set default values for sidebar controls
    session.history = history(maxitems=HISTORY_LEN,columns=4)
    session.tsr = 2.
    session.available_cams = scan_video_ports()
    if len(session.available_cams) > 0:
        session.id = session.available_cams[0]
    else:
        session.id = '0' if platform.system() == 'Windows' else '/dev/video0'
    session.brightness = 0.
    session.contrast = 1.
    session.sharp = 0
    session.rotate = 0
    session.annotations = True
    session.autoscale = True
    session.tmin = 20
    session.tmax = 120
    session.timeline = True
    session.show_min = True
    session.show_max = True
    session.show_mean = False
    session.show_center = False
    session.trange = 500.
    session.toff = 0.
    session.width = 0
    session.cheight = 300
    session.wait_delay = 50
    session.t_units = 's'
    session.showscale = True
    session.colormap = cmaplist[0]
    session.showvideo = False
    session.chart_render_count = 0

else :
    preserve_sessionstate(session)
    if 'available_cams' not in session:
        session.available_cams = scan_video_ports()
    if 'chart_render_count' not in session:
        session.chart_render_count = 0

for k,v in (('recorder',None),('rec_radiometry',True),('last_recording',None),('rec_error',None),('caminfo',None)):
    if k not in session:
        session[k] = v

def restart():
    init.clear()

def start_recording():
    session.rec_error = None
    session.recorder = ThermalRecorder(os.path.join(REC_DIR, f'{datetime.now():%Y-%m-%d_%H-%M-%S}_p2pro'),
                                       radiometry=session.rec_radiometry)

def stop_recording():
    rec, session.recorder = session.recorder, None
    if rec is None:
        return
    try:
        session.last_recording = rec.stop()
    except RecorderError as ex:
        session.rec_error = str(ex)

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
        st.selectbox('rotate image',(0,90,180,270),key='rotate',disabled=session.recorder is not None,
                     help='can not be changed while recording')
        st.checkbox('show min max temp cursors',key='annotations')
        st.checkbox('show color scale',key='showscale')
        st.checkbox('show camera video stream',key='showvideo',help=help.showvideo)
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
    # note: the script never ends (main loop), so keep the number of elements constant, otherwise stale
    # elements of the previous run stay visible -> placeholders instead of conditional elements
    with st.expander('recording',expanded=session.recorder is not None or session.last_recording is not None or session.rec_error is not None):
        st.checkbox('include radiometric data',key='rec_radiometry',help=help.rec_radiometry,
                    disabled=session.recorder is not None)
        if session.recorder is None:
            st.button('start recording',on_click=start_recording,help=help.recording)
        else:
            st.button('stop recording',on_click=stop_recording,type='primary')
        rec_msg = st.empty()
        if session.rec_error is not None:
            rec_msg.error(session.rec_error)
        elif session.last_recording is not None:
            rec_msg.caption(f'last recording: {session.last_recording}')
    with st.expander('more settings'):
        if st.button('scan video ports'):
            session.available_cams = scan_video_ports()
            if len(session.available_cams) > 0 and session.id not in session.available_cams:
                session.id = session.available_cams[0]
                restart()

        if len(session.available_cams) > 0:
            current_index = session.available_cams.index(session.id) if session.id in session.available_cams else 0
            selected_id = st.selectbox('video device',session.available_cams,index=current_index,help=help.cam_id)
            if selected_id != session.id:
                session.id = selected_id
                restart()
                st.rerun()
        else:
            st.warning('No video device found. Click "scan video ports" after connecting the camera.')
            st.text_input('video device',on_change=restart,key='id',help=help.cam_id)

        st.number_input('image width',step=50,key='width',help=help.image_width)
        st.number_input('chart height',step=50,key='cheight')
        st.number_input('wait delay ms',min_value=0,step=10,help=help.history_wait_delay,key='wait_delay')

@st.cache_resource
def init():
    def looks_like_p2pro_temperature(temp):
        # High-sensitivity mode expected operating range is up to about 180C.
        return np.isfinite(temp).all() and temp.min() > -100 and temp.max() < 220

    def first_working_device(candidates):
        for cid in candidates:
            try:
                test = p2pro(cid)
                ok_samples = 0
                for _ in range(2):
                    t = test.temperature()
                    if looks_like_p2pro_temperature(t):
                        ok_samples += 1
                if ok_samples >= 1:
                    return cid
            except Exception:
                continue
        return None

    if len(session.available_cams) == 0:
        session.available_cams = scan_video_ports()

    if len(session.available_cams) > 0:
        # If the selected id is stale or missing, switch to a working one.
        if session.id not in session.available_cams:
            working = first_working_device(session.available_cams)
            session.id = working if working is not None else session.available_cams[0]

    try:
        p2 = p2pro(session.id)
        t = p2.temperature()
        if not looks_like_p2pro_temperature(t):
            raise RuntimeError(
                f'Device {session.id} does not look like a valid P2Pro thermal stream '
                f'(temp range {t.min():.2f}..{t.max():.2f}C).'
            )
    except Exception as ex:
        # One more automatic recovery attempt: choose another working device.
        working = first_working_device(session.available_cams)
        if working is not None and working != session.id:
            session.id = working
            p2 = p2pro(session.id)
            p2.raw()
            return p2
        st.error(
            f'Could not open/read camera device {session.id}. '
            f'Choose another device in the sidebar and click "scan video ports" if needed. '
            f'(Is another program, e.g. a webcam app, using the camera?)\n\n{ex}'
        )
        st.stop()
    return p2

p2 = init()

@st.cache_resource
def init_usb():
    'USB vendor command interface. Opened after the video stream, see p2pro_cmd. Exceptions are not cached.'
    return p2pro_cmd.P2Pro()

def read_caminfo(cam):
    D = p2pro_cmd.DeviceInfoType
    T = p2pro_cmd.PropTpdParams
    info = {
        'firmware': cam.get_device_info_str(D.DEV_INFO_FW_BUILD_VERSION_INFO),
        'part number': cam.get_device_info_str(D.DEV_INFO_GET_PN),
        'serial number': cam.get_device_info_str(D.DEV_INFO_GET_SN),
    }
    gain = cam.get_prop_tpd_params(T.TPD_PROP_GAIN_SEL)
    info['gain'] = {0:'low (0)',1:'high (1)'}.get(gain,f'unknown ({gain})')
    for name,p in (('emissivity (raw)',T.TPD_PROP_EMS),('distance (raw)',T.TPD_PROP_DISTANCE),
                   ('reflection temp (raw)',T.TPD_PROP_TU),('atmospheric temp (raw)',T.TPD_PROP_TA),
                   ('atm. transmittance (raw)',T.TPD_PROP_TAU)):
        info[name] = str(cam.get_prop_tpd_params(p))
    return info

def set_palette():
    session.usb_error = None
    try:
        init_usb().pseudo_color_set(0, p2pro_cmd.PseudoColorTypes[session.cam_palette])
    except Exception as ex:
        session.usb_error = f'could not set palette: {ex}'

with st.sidebar:
    with st.expander('camera (USB)'):
        try:
            cam = init_usb()
        except Exception as ex:
            cam = None
            st.warning(f'USB command interface not available: {ex}\n\n{help.usb}')
        if cam is not None:
            try:
                if session.caminfo is None or st.button('read camera info'):
                    session.usb_error = None
                    session.caminfo = read_caminfo(cam)
                if 'cam_palette' not in session:
                    pal = cam.pseudo_color_get()
                    session.cam_palette = pal.name if pal.name in PALETTES else PALETTES[0]
            except Exception as ex:
                session.usb_error = f'USB read failed: {ex}'
            if session.caminfo is not None:
                st.table({'value':session.caminfo})
            if 'cam_palette' in session:
                st.selectbox('camera video palette',PALETTES,key='cam_palette',on_change=set_palette,help=help.cam_palette)
            usb_msg = st.empty()
            if session.get('usb_error'):
                usb_msg.error(session.usb_error)

##### define placeholders for the loop output:
info = st.empty()
rec_info = st.empty()
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
tm.add('recinfo',1)
tm.add('restart',500)

while True:    # main aquisition loop

    frame = p2.get_frame() # one frame for temperature, video and recording
    raw = p2.frame_raw(frame)
    temp = p2.raw_to_celsius(raw)
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
            session.chart_render_count += 1
            chart.plotly_chart(fig, width='stretch', key=f'history_chart_{session.chart_render_count}')

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

    if session.recorder is not None: # records the displayed image + raw data (not rotated)
        try:
            session.recorder.write(np.asarray(im)[:,:,:3], raw)
        except (RecorderError, OSError) as ex:
            stop_recording()
            session.rec_error = f'recording stopped: {ex}'
            st.rerun()
    if tm.check('recinfo'):
        if session.recorder is not None:
            rec_info.markdown(f':red[● REC] {session.recorder.elapsed():.0f} s, {session.recorder.frames} frames')
        else:
            rec_info.empty()

    if session.width  > 0 :
        img.image(im,width=session.width,clamp=True,)
    else :
        img.image(im,clamp=True)

    if session.showvideo :
        v = p2.frame_video_rgb(frame)
        v = rotate(v,session.rotate)
        if session.width  > 0 :
            img2.image(v,width=session.width,clamp=True,)
        else :
            img2.image(v,clamp=True,width='stretch')

    time.sleep(session.wait_delay/1000.)

    if tm.check('restart') : # memory leak in streamlit
        st.rerun()
