import math,warnings
import numpy as np
from scipy.optimize import linprog
from app.domain.regression.common import NumericError,require,payload,bounded_rows
from app.domain.regression.contracts import RegressionStatistics
RegressionError=NumericError

def terms(s):
    result=[dict(term='intercept',column=None,level=None,reference=None,unit='')]
    for c in s['covariates']:
        if c['type']=='continuous':result.append(dict(term=c['column'],column=c['column'],level=None,reference=None,unit=c['unit']))
        else:
            for level in c['levels']:
                if level!=c['reference']:result.append(dict(term=c['column']+':'+level['value'],column=c['column'],level=level,reference=c['reference'],unit=c['unit']))
    return result

def compute_regression(rows,selection):
    import statsmodels.api as sm
    s=payload(selection);bounded_rows(rows)
    raw=np.array([r['x'] for r in rows],dtype=float);y=np.array([r['y'] for r in rows],dtype=float)
    require(raw.ndim==2 and 1<=raw.shape[1]<=20 and np.isfinite(raw).all() and np.isfinite(y).all(),'numeric_invalid_input','非法设计矩阵。')
    n=len(y);p=raw.shape[1]+1;method=s['method']
    require(n>=max(10 if method=='ols' else 20,p+2),'numeric_sample_size','完整样本量不足。')
    means=raw.mean(axis=0);scales=raw.std(axis=0);require((scales>0).all(),'numeric_rank','协变量没有变化。')
    X=np.column_stack([np.ones(n),(raw-means)/scales]);sv=np.linalg.svd(X,compute_uv=False);rank=int(np.linalg.matrix_rank(X));condition=float(sv[0]/sv[-1])
    require(rank==p and condition<=1e8,'numeric_rank','设计矩阵秩亏或严重病态。')
    transform=np.eye(p);transform[0,1:]=-means/scales;transform[1:,1:]=np.diag(1/scales)
    warning_list=['complete_case_selection_bias','association_not_causation','unadjusted_coefficient_inference']
    if n-p<10:warning_list.append('small_residual_df')
    gradient=None
    if method=='ols':
        require(np.ptp(y)>1e-12*max(1,float(np.max(np.abs(y)))),'numeric_constant','结局没有足够变化。')
        fit=sm.OLS(y,X).fit(method='qr',use_t=True)
        # A change of measurement origin must not change the perfect-fit guard.
        centered_y=y-y.mean()
        require(float(fit.ssr)>1e-20*max(1,float(np.dot(centered_y,centered_y))),'numeric_perfect_fit','完美或近完美拟合不能发布经典推断。')
        influence=fit.get_influence();leverage=influence.hat_matrix_diag.tolist();cooks=influence.cooks_distance[0].tolist()
        statistic_distribution=__import__('scipy').stats.t(df=n-p);rs=float(fit.rsquared);ars=float(fit.rsquared_adj);sd=float(math.sqrt(fit.ssr/(n-p)));ll=dev=aic=None
        if any(h>2*p/n for h in leverage) or any(d>4/n for d in cooks) or np.max(np.abs(influence.resid_studentized_internal))>3:warning_list.append('influence_screening')
    else:
        require(np.isin(y,[0,1]).all() and min(int(y.sum()),int(n-y.sum()))>=5,'numeric_sample_size','Logistic阳性和阴性均须至少5例。')
        Z=(2*y-1)[:,None]*X
        # b=u-v, u/v>=0; L1 norm bounded, maximize total nonnegative margins.
        A=np.column_stack([-Z,Z]);objective=np.r_[-Z.sum(axis=0),Z.sum(axis=0)]
        lp=linprog(objective,A_ub=np.vstack([A,np.ones((1,2*p))]),b_ub=np.r_[np.zeros(n),1.],bounds=(0,None),method='highs',options={'time_limit':5.})
        require(lp.success and lp.x is not None and np.max(A@lp.x)<=1e-7,'numeric_separation_check','分离检查无法可靠完成。')
        require(-float(lp.fun)<=1e-7,'numeric_separation','存在完全或准完全分离，无有限无惩罚MLE。')
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always');fit=sm.Logit(y,X).fit(method='newton',start_params=np.zeros(p),maxiter=100,tol=1e-10,disp=False)
        require(not caught and fit.mle_retvals.get('converged',False),'numeric_convergence','Logistic未可靠收敛。')
        gradient=float(np.max(np.abs(fit.model.score(fit.params))));require(gradient<1e-6,'numeric_convergence','梯度未收敛。')
        eigen=np.linalg.eigvalsh(-fit.model.hessian(fit.params));require(eigen.min()>1e-10,'numeric_unstable','信息矩阵非正定或病态。')
        leverage=[];cooks=[];statistic_distribution=__import__('scipy').stats.norm();rs=ars=sd=None;ll=float(fit.llf);dev=-2*ll;aic=float(fit.aic)
        if min(y.sum(),n-y.sum())/(p-1)<10:warning_list.append('sparse_data')
    beta=transform@fit.params;cov=transform@fit.cov_params()@transform.T;se=np.sqrt(np.diag(cov));stat=beta/se;pv=2*statistic_distribution.sf(np.abs(stat));critical=float(statistic_distribution.ppf(.975));low=beta-critical*se;high=beta+critical*se
    require(np.isfinite(np.r_[beta,se,stat,pv,low,high,cov.ravel()]).all(),'numeric_unstable','非有限推断结果。')
    metadata=terms(s);require(len(metadata)==p,'numeric_invalid_input','编码项与模型不同。')
    coefficients=[]
    for i,t in enumerate(metadata):
        odds=[None]*3
        if method=='logistic':
            require(max(beta[i],low[i],high[i])<709 and min(beta[i],low[i],high[i])>-745,'numeric_overflow','原单位OR或区间无法有限表达。')
            odds=[float(math.exp(v)) for v in (beta[i],low[i],high[i])]
        coefficients.append(dict(**t,beta=float(beta[i]),se=float(se[i]),statistic=float(stat[i]),p_value=float(pv[i]),ci_low=float(low[i]),ci_high=float(high[i]),or_value=odds[0],or_ci_low=odds[1],or_ci_high=odds[2]))
    fitted=fit.predict();residual=y-fitted
    return RegressionStatistics.model_validate(dict(method=method,n=n,p=p,df_residual=n-p,coefficients=coefficients,covariance=cov.tolist(),r_squared=rs,adjusted_r_squared=ars,residual_sd=sd,log_likelihood=ll,deviance=dev,aic=aic,diagnostics=dict(rank=rank,centers=means.tolist(),scales=scales.tolist(),condition_number=condition,converged=True,gradient_max=gradient,residuals=residual.tolist(),fitted=fitted.tolist(),leverage=leverage,cooks_distance=cooks),warnings=warning_list)).model_dump(mode='json')
