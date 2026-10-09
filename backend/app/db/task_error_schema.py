"""Durable task retries and nullable attempt/event error history."""
from sqlalchemy import CheckConstraint, Column, Integer, Text, text


CATEGORIES = "'temporary','authentication','permission','configuration','source','output','submission_unknown','budget','interrupted','internal'"
RETRY_REASONS = "'temporary_provider_error','worker_interrupted','manual_retry'"


def add_task_error_columns(tasks, attempts, events):
    tasks.append_column(Column('retry_count', Integer, nullable=False, server_default=text('0')))
    tasks.append_constraint(CheckConstraint('retry_count >= 0 AND retry_count <= 3', name='tasks_retry_count_check'))
    for table in (attempts, events):
        for column in ('error_code', 'error_category', 'retry_reason'):
            table.append_column(Column(column, Text))
        table.append_constraint(CheckConstraint(f'error_category IN ({CATEGORIES})', name=table.name + '_error_category_check'))
        table.append_constraint(CheckConstraint(f'retry_reason IN ({RETRY_REASONS})', name=table.name + '_retry_reason_check'))
    events.append_column(Column('retry_count', Integer))
    events.append_column(Column('retry_delay_seconds', Integer))
    events.append_constraint(CheckConstraint('retry_count >= 0 AND retry_count <= 3', name='task_events_retry_count_check'))
    events.append_constraint(CheckConstraint('retry_delay_seconds IN (10,30,90)', name='task_events_retry_delay_check'))
