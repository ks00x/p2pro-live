import numpy as np
from PIL import Image, ImageFilter, ImageDraw, ImageFont, ImageColor

def find_tmax(temp):
    m = np.argmax(temp)
    m = np.unravel_index(m, np.array(temp).shape)
    return (m[1],m[0]) , temp[m]

def find_tmin(temp):
    m = np.argmin(temp)
    m = np.unravel_index(m, np.array(temp).shape)
    return (m[1],m[0]) , temp[m]

def draw_annotation(image,pos,text,color='red',fonttype='arial.ttf',fontsize=15,dotsize=4):
        
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
    
    