"""Select the local Docker image for the B05 lifecycle fixtures."""
import os


def bio_insights_test_image():
    return os.environ.get('PAPERASSIST_SC_NUMERIC_TEST_IMAGE') or 'paperassist-client-b05-sub4-deps:local'
