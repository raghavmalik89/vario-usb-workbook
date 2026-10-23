import csv, json, sys
import numpy as np
sys.path.insert(0, 'analysis')
from common import compensate_ms5611

def load(fn):
    from common import get_prom
    with open('analysis/data/'+fn.replace('.csv','.json')) as f:
        meta = json.load(f)
    P={0:{'t':[],'d1':[],'d2':[]},1:{'t':[],'d1':[],'d2':[]}}
    V=[]
    with open('analysis/data/'+fn) as f:
        for r in csv.reader(f):
            if len(r)<9 or not r[0].isdigit(): continue
            t=int(r[1])/1e6
            if r[2]=='P' and r[3]!='' and r[4]!='':
                sid=int(r[3]); P[sid]['t'].append(t); P[sid]['d1'].append(int(r[4]))
            elif r[2]=='T' and r[3]!='' and r[5]!='':
                sid=int(r[3]); P[sid]['d2'].append(int(r[5])); P[sid].setdefault('t2',[]).append(t)
            elif r[2]=='V' and len(r)>13 and r[12]!='':
                V.append((t,int(r[12]),int(r[13]),float(r[14]) if len(r)>14 and r[14] else 0))
    out={}
    for sid in (0,1):
        t=np.array(P[sid]['t']); d1=np.array(P[sid]['d1'])
        t2=np.array(P[sid]['t2']); d2=np.array(P[sid]['d2'])
        # zero-order-hold temperature onto pressure timestamps (causal)
        d2z=d2[np.searchsorted(t2,t,side='right')-1]
        pa,_te = compensate_ms5611(d1,d2z,get_prom(meta,sid))
        alt = 44330.0*(1.0-(pa/101325.0)**0.1902945)
        out[sid]=(t,alt)
    return out,V,out[0][0][0] if len(out[0][0]) else 0

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

names={0:'D01',1:'C03',2:'S4',3:'S5',4:'FUS'}
for fn,tag in [('20261023_221124_idf_elevator_2x.csv','run1'),('20261023_221420_idf_elevator_2x.csv','run2')]:
    data,V,t0=load(fn)
    fig,ax=plt.subplots(3,1,figsize=(14,12),sharex=True)
    for sid in (0,1):
        t,alt=data[sid]
        ax[0].plot(t,alt,label=f'sid{sid}',lw=0.7)
    ax[0].set_ylabel('raw altitude (m)'); ax[0].legend(); ax[0].grid(alpha=0.3)
    ax[0].set_title(tag+' '+fn)
    # per-estimator audio activity in 5 s bins
    bins=np.arange(0,(data[0][0][-1]-t0)+5,5)
    for eid in range(5):
        ts=[t-t0 for t,e,ev,v in V if e==eid and ev==1]
        h,_=np.histogram(ts,bins=bins)
        ax[1].plot(bins[:-1]+2.5,h,label=names[eid])
    ax[1].set_ylabel('ON events / 5s'); ax[1].legend(ncol=5,fontsize=8); ax[1].grid(alpha=0.3)
    # FUS (eid 4) episodes
    episodes=[]
    on=None
    for t,e,ev,v in V:
        if e==4 and ev==1: on=(t-t0,v)
        if e==4 and ev==2 and on:
            episodes.append((on[0],t-t0,(on[1]-500)/450,v/1000.0))
            on=None
    for s,e0,vmax,dur in episodes:
        ax[2].plot([s,e0],[vmax,vmax],lw=2,color='r')
    ax[2].set_ylabel('FUS episodes: peak implied v (m/s)'); ax[2].grid(alpha=0.3); ax[2].set_xlabel('t (s)')
    plt.tight_layout()
    plt.savefig(f'analysis/results/elevator_{tag}.png',dpi=110)
    # leg detection from sid0 raw altitude (1 s moving avg, threshold 0.5 m/s sustained 3 s)
    t,alt=data[0]
    # uniform resample at 20 Hz
    tu=np.arange(t[0],t[-1],0.05)
    au=np.interp(tu,t,alt)
    k=20 # 1 s box
    as_=np.convolve(au,np.ones(k)/k,mode='same')
    v=np.gradient(as_,tu)
    vs=np.convolve(v,np.ones(k)/k,mode='same')
    inleg=np.abs(vs)>0.5
    legs=[]; i=0
    while i<len(tu):
        if inleg[i]:
            j=i
            while j<len(tu) and inleg[j]: j+=1
            if tu[j-1]-tu[i]>2.0: legs.append((tu[i]-t0,tu[j-1]-t0,float(vs[i:j].mean()),float(as_[j-1]-as_[i])))
            i=j
        else: i+=1
    print(f'=== {tag} {fn} ===')
    print(f'alt range sid0: {alt.min():.1f} .. {alt.max():.1f} m, final {alt[-1]:.1f}, total span {alt.max()-alt.min():.1f} m')
    print(f'legs (start-end s, mean climb rate m/s, dH m):')
    for s,e0,vr,dh in legs:
        print(f'  {s:7.1f}-{e0:7.1f}s  v={vr:+5.2f} m/s  dH={dh:+6.1f} m')
    print(f'FUS episodes: {len(episodes)} (start-end s, peak implied v, dur):')
    for s,e0,vmax,dur in episodes:
        print(f'  {s:7.1f}-{e0:7.1f}s v={vmax:+5.2f} dur={dur:5.2f}s')
    # audio vs legs: episodes overlapping legs
    hits=sum(1 for s,e0,_,_ in episodes if any(not(e0<ls or s>le) for ls,le,_,_ in legs))
    print(f'episodes overlapping a detected leg: {hits}/{len(episodes)}')
