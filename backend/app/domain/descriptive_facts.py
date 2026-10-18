"""English fixed text for modern descriptive artifacts."""
METHOD = ('Complete records for selected fields were used, without imputation, deduplication or outlier removal. '
    'Sample standard deviation uses n-1; quantiles use linear interpolation at (n-1)p. '
    'Boxes show Q1-Q3 and the median. Whiskers reach the most extreme observed values inside '
    'Q1-1.5*IQR to Q3+1.5*IQR; hollow points mark observations outside these fences.')
METRICS = dict(n='Sample size',mean='Mean',std='Sample standard deviation',min='Minimum',q1='Lower quartile',
    median='Median',q3='Upper quartile',max='Maximum',iqr='Interquartile range')


def english_facts(payload, result):
    facts=payload['facts']
    labels=dict(variable='Numeric variable',unit='Measurement unit',grouping='Grouping variable',sheet='Worksheet',
                **{'figure.number':'Figure number','figure.title':'Figure title','method.summary':'Calculation and plotting method',
                   'data.total':'Source row count','data.valid':'Complete record count','data.excluded':'Excluded row count'})
    for key,fact in facts.items():
        if key in labels: fact['label']=labels[key]
        elif key.startswith('overall.'): fact['label']='Overall: '+METRICS[key.split('.')[-1]]
        elif key.startswith('groups.'):
            part=key.split('.')[-1]
            fact['label']='Group label' if part=='label' else METRICS[part]
        elif key.startswith('series.'):
            fact['label']={'outlier_count':'Outlying observation count','whislo':'Lower whisker','whishi':'Upper whisker'}[key.split('.')[-1]]
        if fact['raw'] is None: fact['value']='Unavailable'
    from app.domain.dataset_processing import analysis_stage_text
    method = analysis_stage_text(METHOD, result)
    facts['method.summary'].update(value=method,raw=method)
    if not result['selection']['unit']: facts['unit'].update(value='unit not specified',raw='unit not specified')
    if not result['group_name']: facts['grouping'].update(value='No grouping',raw='No grouping')
