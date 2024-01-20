
history_timerange = '''
internally the data within the time range is interpolated if there are more than 1024 data points to avoid a slowdown
of the app due to the plotting routine. This may give some display artifacts where the displayed data seems to change
constantly. However the original data is left untouched. 
'''
history_wait_delay = '''add delay to reduce framerate and lower cpu usage'''

cam_id = 'on windows the camera id is an integer (0,1,2..), on linux a string like /dev/..'

image_width = 'in pixels, set to 0 to make the video as wide as the window (default)'

tsr = 'The total cumber of the samples of the history buffer is 10000. A lower sample rate translates to a longer history and vice versa'