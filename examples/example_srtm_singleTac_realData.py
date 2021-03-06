
# coding: utf-8

# In[1]:

get_ipython().magic('load_ext autoreload')
get_ipython().magic('autoreload 2')
from kineticmodel import SRTM_Zhou2003, SRTM_Lammertsma1996


# In[2]:

import numpy as np
#np.random.seed(0)

import scipy as sp
import matplotlib.pyplot as plt
get_ipython().magic('matplotlib inline')
import pandas as pd


# In[4]:

table=pd.read_table('data/ROI_TAC_nonPVE.txt')
table.columns

t= pd.Series.as_matrix(np.mean(table.iloc[:,[0, 1]], axis=1))
diff=np.diff(table.iloc[:,[0, 1]], axis=1)
dt=np.reshape(diff, np.product(diff.shape))
TAC=table.loc[:,'Neocortex']
refTAC=table.loc[:,'Total_cb']

fig, ax = plt.subplots();
ax.plot(t, TAC, label='Neocortex');
ax.plot(t, refTAC, label='Cerebellum');
ax.set_xlabel('t');
ax.set_ylabel('Activity');
ax.set_title('Real PET data');
ax.legend();


# In[5]:

# Initialize SRTM Lammerstma 1996 model
mdl_lammertsma = SRTM_Lammertsma1996(t, dt, TAC, refTAC, time_unit='s')

# fit model
mdl_lammertsma.fit();

# get model results
mdl_lammertsma.results


# In[6]:

# Initialize SRTM Zhou 2003 model
mdl_zhou = SRTM_Zhou2003(t, dt, TAC, refTAC, time_unit='s')

mdl_zhou.fit();

mdl_zhou.results


# In[ ]:



