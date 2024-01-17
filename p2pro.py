import cv2
import numpy as np
import sys
'''
with info from , check out:
https://www.eevblog.com/forum/thermal-imaging/infiray-and-their-p2-pro-discussion/200/
https://github.com/leswright1977/PyThermalCamera/blob/main/src/tc001v4.2.py

I did create a seperate conda env for this project on Windows:
conda create -n p2pro python
activate p2pro
pip install opencv-python pyusb pyaudio  ffmpeg-python

tested with cv2 4.8.0
'''

class p2pro:

    def __init__(self,cam_id) -> None:
        'module to read out the Infiray P2Pro camera'
        if sys.platform == 'win32': cam_id = int(cam_id)
        self.cap = cv2.VideoCapture(cam_id)         
        self.cap.set(cv2.CAP_PROP_CONVERT_RGB, 0) # do not create rgb data!

    def raw(self):
        'returns the raw 16bit int image'
        ret, frame = self.cap.read() 
        frame = np.reshape(frame[0],(2,192,256,2))
        raw = frame[1,:,:,:].astype(np.intc) # select only the lower image part
        raw = (raw[:,:,1] << 8) + raw[:,:,0] # assemble the 16bit word
        return raw
    
    def video(self):
        'returns the normal 8bit video stream from the upper half'
        ret, frame = self.cap.read() 
        frame = np.reshape(frame[0],(2,192,256,2))
        return frame[0,:,:,0] # select only the upper image part, lower byte                
    
    def temperature(self):
        'returns the image as temperature map in Celsius'
        raw = self.raw()        
        return raw/64 - 273.2 # convert to Celsius scale
    
    def __del__(self):
        self.cap.release()
         

def main():
    import time

    id = 0 # the p2pro camera may have a higher id (1,2..)
    p2 = p2pro(id)
    i = 0
        
    while(True):            
        t0 = time.perf_counter()
        temp = p2.temperature()
        t1 = time.perf_counter()
        ct = (t1-t0)*1000
        i += 1
        if i%20 == 0 :
            print(f"min = {temp.min():1.4}, max = {temp.max():1.4}, avg = {temp.mean():0.4}, cpu secs read = {ct:1.2f}ms")
        
        brightness = 0.01
        contrast = 0.95
        temp = temp.T # transpose image if needed
        # values scaled to [0,1] range
        cv2.imshow('p2pro temperature',(temp-temp.min())/(temp.max()-temp.min()) * contrast + brightness)
        v = p2.video()
        cv2.imshow('video',v.T)
            
        #Waits for a user input to quit the application    
        if cv2.waitKey(1) & 0xFF == ord('q'):    
            break                    
    cv2.destroyAllWindows()


if __name__ == '__main__':
    main()    