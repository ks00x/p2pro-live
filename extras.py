import numpy as np
from PIL import Image, ImageDraw, ImageFont
import io

def preserve_sessionstate(session):
      'trick to preserve session state of the main page , see: https://discuss.streamlit.io/t/preserving-state-across-sidebar-pages/107/23      '
      for k in session.keys():
            session[k] = session[k]

def np_to_csv_stream(im,fmt='%1.2f')->str:        
        bio = io.BytesIO()
        np.savetxt(bio,im,fmt=fmt,delimiter=' ')
        return bio.getvalue().decode('latin1')     

def c_to_f(x):
    return x * 1.8 + 32  


def find_tmax(temp):
    'finds the max of the 2D <temp> array and returns a tuple ((x,y),value) of coordinates and value at position'
    m = np.argmax(temp) 
    m = np.unravel_index(m, np.array(temp).shape)
    return (m[1],m[0]) , temp[m]

def find_tmin(temp):
    'finds the min of the 2D <temp> array and returns a tuple ((x,y),value) of coordinates and value at position'
    m = np.argmin(temp)
    m = np.unravel_index(m, np.array(temp).shape)
    return (m[1],m[0]) , temp[m]

def rotate(temp,rot):        
        if rot == 90 : return np.rot90(temp,1)
        if rot == 180 : return np.rot90(temp,2)
        if rot == 270 : return np.rot90(temp,3)
        return temp

def draw_annotation(image,pos,text,color='red',fonttype='arial.ttf',fontsize=15,dotsize=4):
        '''draws a circle at the <pos> location and the annotation <text> next to it.
        Checks for image borders and adjusts the the text position so the text remains visible
        '''
        draw = ImageDraw.Draw(image)
        s = dotsize/2
        x1 = abs(pos[0]-s)
        y1 = abs(pos[1]-s)
        x2 = abs(pos[0]+s)
        y2 = abs(pos[1]+s)
        draw.ellipse((x1,y1,x2,y2), fill=color, 
                outline=color, width=1)
    
        font = ImageFont.truetype(fonttype, fontsize,)
        tl = int(draw.textlength(text,font))
        # give some offset if text is near the border:
        w,h = image.size
        if x1 + tl > w : x = pos[0] - tl               
        else : x = pos[0]
        if y1 + fontsize > h : y = pos[1] - fontsize
        else : y = pos[1]

        draw.text((x,y),text,fill=color,font=font )



def convert_colormap(temp,colormapper):
    temp = colormapper(temp)
    temp = np.uint8(temp * 255)
    im = Image.fromarray(temp)
    return im
    

def colorbarfig(min,max,cmapname):
    'draw a colorbar with scale only image'
    # https://matplotlib.org/stable/users/explain/colors/colorbar_only.html
    from matplotlib import cm,colors,figure    
    # solves memory problems calling it this way!
    # see https://discourse.matplotlib.org/t/pyplot-interface-and-memory-management/22299
    fig = figure.Figure(figsize=(1, 8), layout='constrained') 
    ax = fig.subplots(1, 1)        
    norm = colors.Normalize(vmin=min, vmax=max)
    fig.colorbar(cm.ScalarMappable(norm=norm, cmap=cmapname),
             cax=ax, orientation='vertical') # , label='temperature'
    ax.tick_params(labelsize=16)
    return fig
