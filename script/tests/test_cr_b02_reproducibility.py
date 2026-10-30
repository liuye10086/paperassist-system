"""Targeted contracts for independent scientific reproduction/export."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import sys

import numpy as np

MODULE = Path(__file__).resolve().parents[1] / 'cr_b02_repro_compare.py'
spec = importlib.util.spec_from_file_location('repro_compare', MODULE)
compare = importlib.util.module_from_spec(spec) if spec else None
if MODULE.exists():
    spec.loader.exec_module(compare)


class ReproductionContractTests(unittest.TestCase):
    def test_tool_exists(self):
        self.assertTrue(MODULE.exists(), 'scientific comparison helper missing')

    def test_integer_change_fails_without_tolerance(self):
        if not MODULE.exists(): self.skipTest('helper missing')
        with self.assertRaises(AssertionError):
            compare.compare_array(np.array([1000000]), np.array([1000001]), exact=True)

    def test_float_tolerance_and_nan_mask_are_enforced(self):
        if not MODULE.exists(): self.skipTest('helper missing')
        compare.compare_array(np.array([1., np.nan]), np.array([1.000001, np.nan]))
        with self.assertRaises(AssertionError):
            compare.compare_array(np.array([1., np.nan]), np.array([1., 0.]))
        with self.assertRaises(AssertionError):
            compare.compare_array(np.array([1.]), np.array([1.001]))

    def test_marker_float64_tolerance_is_stricter(self):
        if not MODULE.exists(): self.skipTest('helper missing')
        with tempfile.TemporaryDirectory() as directory:
            a, b = Path(directory)/'a.tsv', Path(directory)/'b.tsv'
            a.write_text('cluster\tfeature_id\tp_value\n0\tENSG1\t0.1\n')
            b.write_text('cluster\tfeature_id\tp_value\n0\tENSG1\t0.100001\n')
            with self.assertRaises(AssertionError): compare.compare_table(a, b, 'markers')

    def test_marker_order_must_match(self):
        if not MODULE.exists(): self.skipTest('helper missing')
        with tempfile.TemporaryDirectory() as directory:
            a, b = Path(directory)/'a.tsv', Path(directory)/'b.tsv'
            a.write_text('cluster\tfeature_id\tscore\n0\tA\t1\n0\tB\t2\n')
            b.write_text('cluster\tfeature_id\tscore\n0\tB\t2\n0\tA\t1\n')
            with self.assertRaises(AssertionError): compare.compare_table(a, b, 'markers')

    def test_pca_sign_uses_stable_feature_id_tie_break(self):
        if not MODULE.exists(): self.skipTest('helper missing')
        scores, loadings = compare.canonical_pca(np.array([[2., 3.]]), np.array([[-1., 2.], [1., 1.]]), ['B', 'A'])
        np.testing.assert_array_equal(scores, [[2., 3.]])
        reverse, _ = compare.canonical_pca(-np.array([[2., 3.]]), -np.array([[-1., 2.], [1., 1.]]), ['B', 'A'])
        np.testing.assert_array_equal(scores, reverse)

    def test_relative_path_resolver_rejects_escape(self):
        target = Path(__file__).resolve().parents[1] / 'cr_b02_reproduce.py'
        self.assertTrue(target.exists(), 'standalone reproduction script missing')
        source = importlib.util.spec_from_file_location('reproduce', target)
        module = importlib.util.module_from_spec(source); source.loader.exec_module(module)
        for path in ('../private', '/private', 'C:\\private', 'https://secret.invalid/a'):
            with self.assertRaises(ValueError): module.relative_file(Path.cwd(), path)

    def test_completed_independent_run_resumes_without_wait_or_confirm(self):
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
        import verify_cr_b02_reproducibility as verifier
        class Session:
            base='/api/v1/projects/project';progress={}
            def post(self,*args,**kwargs):
                assert args[0]=='independent-run', 'completed run must not confirm again'
                return {'id':'run','task':{'id':'task'}}
            def get(self,path):
                if path.endswith('/bio-analysis-runs/run'):
                    return {'task':{'status':'succeeded','result_bio_processed_dataset_version_id':'processed'}}
                return {'id':'processed'}
            def wait(self,*args): raise AssertionError('already completed run cannot wait for an earlier checkpoint')
            def save(self): pass
        value=verifier.independent_run(Session(),{'raw_source':{},'id':'recipe','revision':1})
        self.assertEqual(value['id'],'processed')

    def test_public_geo_urls_are_not_misidentified_as_windows_paths(self):
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
        import verify_cr_b02_reproducibility as verifier
        text='!Sample_supplementary_file = ftp://ftp.ncbi.nlm.nih.gov/geo/samples/example'
        self.assertEqual(verifier.public_record({'declaration':text}),{'declaration':text})
        for text in ('C:/Users/private','host_path=C:\\Users\\private'):
            with self.assertRaises(ValueError):verifier.public_record(text)


if __name__ == '__main__': unittest.main()
