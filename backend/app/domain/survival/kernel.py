import warnings
import numpy as np
from scipy.stats import CensoredData,ecdf
from app.domain.regression.common import NumericError,require,payload,bounded_rows
from app.domain.survival.contracts import SurvivalStatistics
SurvivalError=NumericError

def compute_survival(rows,selection):
    s=payload(selection);bounded_rows(rows)
    require(all(np.isfinite(r['time']) and r['time']>=0 and type(r['event']) is bool for r in rows),'numeric_invalid_input','随访时间和状态非法。')
    max_time=max(r['time'] for r in rows);ticks=sorted(set(float(x) for x in np.linspace(0,max_time,5)))
    groups=[];identities=s['groups'] or [None]
    for index,identity in enumerate(identities):
        chosen=[r for r in rows if r['group']==index];require(bool(chosen),'numeric_sample_size','所选组没有完整观察。')
        times=np.array([r['time'] for r in chosen]);events=np.array([r['event'] for r in chosen])
        with warnings.catch_warnings():
            warnings.simplefilter('ignore',RuntimeWarning)
            sf=ecdf(CensoredData(uncensored=times[events],right=times[~events])).sf;interval=sf.confidence_interval(confidence_level=.95,method='log-log')
        lookup={float(t):i for i,t in enumerate(sf.quantiles)};surv=1.;greenwood=0.;points=[];median=None
        for t in sorted(set(times.tolist())):
            risk=int(np.sum(times>=t));d=int(np.sum((times==t)&events));c=int(np.sum((times==t)&~events))
            surv*=1-d/risk
            if d and risk==d:greenwood=None
            elif d and greenwood is not None:greenwood+=d/(risk*(risk-d))
            i=lookup[t];lo=float(interval.low.probabilities[i]);hi=float(interval.high.probabilities[i]);reason=None
            if not np.isfinite(lo) or not np.isfinite(hi) or surv in (0,1):lo=hi=None;reason='boundary_survival_interval_unavailable'
            variance=surv*surv*greenwood if greenwood is not None and surv not in (0,1) else None
            points.append(dict(time=t,n_at_risk=risk,n_event=d,n_censored=c,survival=surv,greenwood_variance=variance,ci_low=lo,ci_high=hi,ci_reason=reason))
            if median is None and surv<=.5:median=t
        risk_table=[dict(time=t,n_at_risk=int(np.sum(times>=t)),events_before=int(np.sum((times<t)&events)),censored_before=int(np.sum((times<t)&~events))) for t in ticks]
        groups.append(dict(identity=identity,label=identity['value'] if identity else 'Overall',n=len(chosen),event_n=int(events.sum()),censored_n=int((~events).sum()),max_time=float(times.max()),median=median,median_reason='not_reached' if median is None else None,points=points,risk_table=risk_table))
    return SurvivalStatistics.model_validate(dict(method='kaplan_meier',n=len(rows),groups=groups,time_unit=s['time_unit'],warnings=['pointwise_intervals','no_between_group_test']+(['zero_time'] if any(r['time']==0 for r in rows) else []))).model_dump(mode='json')
