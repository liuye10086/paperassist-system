"""Mounted only in a UUID test stack: die after real publisher confirmation."""
import os
from pathlib import Path
import sys

sys.path.insert(0, '/app')
from delivery_crash_support import durable_marker, require_isolated_test

from app.workers.config import load_secrets

load_secrets()
config, assets = require_isolated_test(queue=True)
from app.workers.celery_app import publish_confirmed
from app.workers import celery_app
from app.workers.__main__ import main


def publish_then_exit(message, **kwargs):
    publish_confirmed(message, **kwargs)
    durable_marker(assets / '.test-dispatcher-crashed.json',
                   {'checkpoint': 'after_broker_confirm_before_outbox_mark', **message})
    # No exception/finally simulation: RabbitMQ keeps the durable real message.
    os._exit(75)


celery_app.publish_confirmed = publish_then_exit
raise SystemExit(main())
