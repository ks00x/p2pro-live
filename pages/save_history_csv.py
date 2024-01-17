import streamlit as st
from history import history
from datetime import datetime
from extras import preserve_sessionstate

session = st.session_state
preserve_sessionstate(session)

st.write('## save the full history as a csv file')
csv = session.history.csv()
st.download_button('download csv file',data=csv,file_name=f'{datetime.now():%Y-%m-%d_%H:%M:%S}_history.csv')  
