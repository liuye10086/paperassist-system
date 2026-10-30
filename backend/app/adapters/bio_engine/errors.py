"""Stable public failure categories; exception text stays out of transport."""


def error_code(exc):
    if isinstance(exc,(MemoryError,TimeoutError)):return 'bio_resource_exceeded'
    if isinstance(exc,PermissionError) or type(exc).__name__=='SandboxUnavailable':return 'bio_isolation_unavailable'
    if type(exc).__name__=='BioParseError':
        code=getattr(exc,'code','bio_output_invalid')
        return {'bio_source_changed':'bio_input_integrity_changed','bio_input_limit':'bio_resource_exceeded'}.get(code,code)
    if not isinstance(exc,ValueError):return 'bio_output_invalid'
    reason=str(exc)
    if any(token in reason for token in ['budget','limit','h5_logical_size']):return 'bio_resource_exceeded'
    if reason.startswith('insufficient_'):return 'bio_insufficient_observations'
    if any(token in reason for token in ['hash_mismatch','raw_axis','csr_invalid','raw_counts','mapping_axis']):return 'bio_input_integrity_changed'
    if reason=='h5_matrix_mismatch':return 'bio_h5_matrix_mismatch'
    if reason.startswith('h5_'):return 'bio_h5_unsupported'
    if any(token in reason for token in ['parameter','max_counts','max_mt','mitochondrial','unsupported_engine_mode','unsupported_figure','unknown_exclusion','stable_feature','gene_panel','title_limit']):return 'bio_recipe_invalid'
    return 'bio_output_invalid'
