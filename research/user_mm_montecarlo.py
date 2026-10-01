# Monte-Carlo of money-management plans on the trades of the user's LiteFinance tester run (test A).
import pandas as pd, numpy as np
from numba import njit
T=pd.read_csv('/tmp/claude-0/-home-user-hayati/dd988b5a-9b5f-5304-9c45-c4ad2460d765/scratchpad/user_trades.csv',parse_dates=['t','out'])
T['stop']=(T.px-T.sl).abs(); T['hour']=T.t.dt.hour; T=T.sort_values('t').reset_index(drop=True)
bad=[3,4,19,20,21,22]
@njit(cache=True)
def run(R,stop,dayid,start,mode,base,mult,cap,daily,ruin_lvl):
    bal=start; peak=start; mdd=0.0; streak=0; cur=-1; ds=bal
    for i in range(len(R)):
        if dayid[i]!=cur:
            cur=dayid[i]; ds=bal
        if daily>0 and bal<=ds*(1-daily/100): continue
        if mode==0:   # fixed lots, x mult after each win
            lots=base*mult**streak
            if cap>0: lots=min(lots,cap)
        else:         # % of balance, continuous lots (cent account)
            rp=base*mult**streak
            if cap>0: rp=min(rp,cap)
            lots=bal*rp/100/(stop[i]*100)
        pnl=R[i]*stop[i]*100*lots
        bal+=pnl
        streak=streak+1 if pnl>0 else 0
        if bal>peak: peak=bal
        dd=1-bal/peak
        if dd>mdd: mdd=dd
        if bal<=ruin_lvl: return bal,1.0,1
    return bal,mdd,0
def mc(df,mode,base,mult,cap,daily,n=2000,seed=1):
    rng=np.random.default_rng(seed)
    R=df.R.values; S=df.stop.values; day=pd.factorize(df.t.dt.date)[0].astype(np.int64)
    fin=[];dd=[];ru=[]
    for k in range(n):
        p=rng.permutation(len(R))
        b,m,r=run(R[p],S[p],day,100.0,mode,base,mult,cap,daily,10.0)
        fin.append(b);dd.append(m);ru.append(r)
    fin=np.array(fin);dd=np.array(dd)*100
    return dict(ruin_pct=round(100*np.mean(ru),1),median_final=round(np.median(fin)),p10_final=round(np.percentile(fin,10)),p90_final=round(np.percentile(fin,90)),median_maxDD=round(np.median(dd)))
rows=[]
good=T[~T.hour.isin(bad)].reset_index(drop=True)
for name,df in (('all hours',T),('skip bad hours',good)):
    for (lab,mode,base,mult,cap) in (('YOUR PLAN: 0.01 lot, x1.5/win, no cap',0,0.01,1.5,0),
                                      ('YOUR PLAN: 0.01 lot, x2/win, no cap',0,0.01,2.0,0),
                                      ('0.01 lot fixed',0,0.01,1.0,0),
                                      ('cent acct: 1% risk, x1.5/win, cap 3%',1,1.0,1.5,3.0),
                                      ('cent acct: 2% risk, x1.5/win, cap 5%',1,2.0,1.5,5.0),
                                      ('cent acct: 3% risk, x1.5/win, cap 8%',1,3.0,1.5,8.0)):
        for daily in (0,5,3):
            rows.append(dict(trades=name,sizing=lab,daily_stop=daily or '-',**mc(df,mode,base,mult,cap,daily)))
r=pd.DataFrame(rows); pd.set_option('display.width',250); print(r.to_string(index=False))
r.to_csv('/home/user/hayati/research/results/user_mm_montecarlo.csv',index=False)
print('--- % risk without anti-martingale vs with (all hours, no daily stop)')
for lab,b,m,c in (('1% fixed',1,1,0),('2% fixed',2,1,0),('3% fixed',3,1,0),('2% x1.5 cap5',2,1.5,5),('2% x2 cap 8',2,2,8),('2% x1.5 no cap',2,1.5,0)):
    print(lab, mc(T,1,b,m,c,0))
