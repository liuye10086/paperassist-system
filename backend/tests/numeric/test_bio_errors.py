def test_engine_failure_taxonomy_is_stable_and_does_not_leak_paths():
    from app.adapters.bio_engine.errors import error_code
    assert error_code(MemoryError())=='bio_resource_exceeded'
    assert error_code(ValueError('dense_budget_exceeded'))=='bio_resource_exceeded'
    assert error_code(ValueError('raw_member_hash_mismatch'))=='bio_input_integrity_changed'
    assert error_code(ValueError('csr_invalid'))=='bio_input_integrity_changed'
    assert error_code(ValueError('insufficient_observations_or_hvg'))=='bio_insufficient_observations'
    assert error_code(ValueError('invalid_parameter_seed'))=='bio_recipe_invalid'
    assert error_code(ValueError('h5_link_rejected'))=='bio_h5_unsupported'
    assert error_code(RuntimeError('/private/path'))=='bio_output_invalid'
