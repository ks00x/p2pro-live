import numpy as np
import time
import io

def hreduce(data,pts):    
    xn = np.linspace(data[0].min(),data[0].max(),pts)
    n = data.shape[0]
    out = np.zeros((n,pts))
    out[0] = xn
    for k in range(1,n):        
        out[k] = np.interp(xn,data[0],data[k])
    return out


class history:

    def __init__(self,maxitems=5000,columns=3) -> None:  
        '''A fifo buffer for numpy fp numbers with time axis in seconds
           The number of columns is free to choose. The total number of columns
           will be columns+1
        '''      
        self.maxitems = maxitems
        self.cols = columns
        self.mem = np.zeros((self.cols+1,self.maxitems),dtype=np.float32)
        self.items = 0
        self.tcreated = time.time()

    def length_s(self):
        return self.mem[0,self.items-1]
    
    def clear(self):
        'clear the memory and reset the timer'
        self.mem = np.zeros((self.cols+1,self.maxitems),dtype=np.float32)
        self.items = 0
        self.tcreated = time.time()

    def head(self,num):
        'get the last num elements'
        assert num >= 1, f'num must be >=1 , got {num}'
        if num > self.items :
            num = self.items                
        return self.mem[:,self.items-1:self.items-num:-1]
        
    def timerange(self,range_s,offset_s=0,max_samples=500):
        if self.items == 0 : return None
        t = self.mem[0][:self.items]
        tmax = t[self.items-1]
        koff = np.searchsorted(t,tmax-offset_s) - 1
        if koff < 0 : koff = 0        
        kend = np.searchsorted(t,tmax - offset_s - range_s) - 1
        if kend < 0 : kend = 0
        #print(koff,kend,self.items)        
        if koff-kend < max_samples :
            #return self.mem[:,koff:kend:-1]
            return self.mem[:,kend:koff]
        else : # reduce samples for plotly
            return hreduce(self.mem[:,kend:koff],max_samples)
                
    def add(self,row:tuple):
        'add a full row : row is a tuple with columns elements'
        t = time.time() - self.tcreated
        if self.items < self.maxitems :
            self.mem[:,self.items] = (t,)+row
            self.items += 1
        else:            
            self.mem = np.roll(self.mem,-1,axis=None,)            
            self.mem[:,self.maxitems-1] = (t,)+row

    def csv(self,fmt='%1.2f')->str:        
        bio = io.BytesIO()
        np.savetxt(bio, self.mem[:,:self.items].T,fmt=fmt,delimiter=' ')
        return bio.getvalue().decode('latin1')        
        

def main():
    import matplotlib.pyplot as plt

    fig,ax = plt.subplots()
    h = history(maxitems=7)
    for k in range(9):
        h.add((10+k,20+k,30+k))
        time.sleep(0.0001)    
    ax.plot(h.head(5)[0],h.head(5)[1:].T)
    plt.show()

if __name__ == '__main__':
    main()