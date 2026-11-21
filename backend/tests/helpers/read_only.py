"""Compare full business rows and stored file contents across HTTP requests."""


def assert_read_only_snapshot(before, after):
    old_tables, old_files = before
    new_tables, new_files = after
    assert new_files == old_files
    assert new_tables.keys() == old_tables.keys()
    for table, rows in old_tables.items():
        if table == 'operational_request_events':
            # Each observed HTTP request can append a trace. Earlier events must stay intact.
            assert len(new_tables[table]) >= len(rows)
            assert all(event in new_tables[table] for event in rows), table
        else:
            assert new_tables[table] == rows, table
