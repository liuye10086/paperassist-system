"""Run native R comparisons in a fresh interpreter, as the numerical worker does."""
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context


def compare_in_fresh_process(comparison, tmp_path):
    with ProcessPoolExecutor(max_workers=1, mp_context=get_context('spawn')) as worker:
        worker.submit(comparison, tmp_path).result()
