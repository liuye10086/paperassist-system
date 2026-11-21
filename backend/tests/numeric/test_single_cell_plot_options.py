"""Presentation parameters operate only on the frozen plot values."""
import json

import numpy as np
import pytest
from PIL import Image


@pytest.mark.parametrize("kind", ["marker_dotplot", "marker_heatmap"])
def test_custom_marker_png_uses_requested_pixels_dpi_and_display_mask(tmp_path, kind):
    from app.adapters.bio_engine import plots
    from app.adapters.bio_engine.manifest import Writer
    data = dict(feature_ids=["g"], clusters=["0", "1"], mean_log1p=[[1.], [3.]],
                detection_fraction=[[.1], [.5]])
    config = dict(kind=kind, width=965, height=720, width_inches=965/480, height_inches=1.5,
                  dpi=480, min_detection_fraction=.5)
    plots.marker_figures_from_saved(Writer(tmp_path), data, config)
    with Image.open(tmp_path / (kind + "_png.png")) as image:
        assert image.size == (965, 720)
        assert image.info["dpi"][0] == pytest.approx(480, abs=.02)
    displayed = json.loads((tmp_path / (kind + "_data.json")).read_bytes())
    assert displayed["display_mask"] == [[False, True]]
    assert displayed["detection_fraction"] == data["detection_fraction"]
    assert displayed["mean_log1p"] == data["mean_log1p"]


def test_frozen_qc_and_integration_redraw_reuse_members_without_loading_raw_data(tmp_path, monkeypatch):
    import hashlib
    from app.adapters.bio_engine import figure
    def descriptor(name, data):
        path = tmp_path / (name + ".json")
        path.write_text(json.dumps(data), encoding="utf8")
        return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    size_bytes=path.stat().st_size)
    saved_qc = dict(total_counts=[10, 20, 30], detected_genes=[2, 4, 5],
                    filtered_total_counts=[20], filtered_detected_genes=[4], kept=[False, True, False])
    saved_integration = dict(before=[[1, 2], [3, 5]], after=[[5, 4], [8, 2]],
                             batches=["A","B"], barcodes=["b1","b2"], batch_key="batch",
                             state={"applied": True}, axis_note="Harmony axes are corrected dimensions, not PCA explained variance")
    members = dict(qc_distribution_data=descriptor("qc", saved_qc),
                   integration_harmony_data=descriptor("integration", saved_integration))
    def forbidden(*args):
        pytest.fail("The frozen plot has every numeric value required for a redraw")
    monkeypatch.setattr(figure, "load_raw", forbidden)
    for kind, panel, settings, key in [
        ("qc","distribution",{"histogram_bins": 3},"qc_distribution"),
        ("integration_harmony","default",{"point_size": 15.},"integration_harmony"),
    ]:
        output = tmp_path / kind
        output.mkdir()
        result = figure.render(dict(raw={"manifest":{"assay":"single_cell"}}, processed={"members":members},
                             output_directory=str(output), config=dict(kind=kind, panel=panel, width=800,
                             height=600, dpi=120, title="Revised", palette="magma", **settings)))
        assert result["status"] == "completed"
        data = json.loads((output / (key + "_data.json")).read_bytes())
        if kind == "qc":
            assert data["kept"] == saved_qc["kept"]
            assert data["filtered_total_counts"] == [20]
        else:
            assert data["after"] == saved_integration["after"]
            assert data["batches"] == ["A", "B"]
        with Image.open(output / (key + "_png.png")) as image:
            assert image.size == (800, 600)


def test_scatter_area_and_distribution_bins_reach_matplotlib(monkeypatch):
    from app.adapters.bio_engine import plots
    captured = []
    def record(writer, key, fig, data, config):
        captured.append(fig)
    monkeypatch.setattr(plots, "save", record)
    try:
        plots.embedding_figure(None, np.array([[1., 2.]]), np.array(["0"]), ["b1"], "umap", {"point_size": 37.})
        assert captured[-1].axes[0].collections[0].get_sizes().tolist() == [37.]
        qc = dict(raw_counts=np.array([8., 10.]), raw_detected=np.array([2., 5.]),
                  filtered_total=[10.], filtered_detected=[5.], obs_mask=[False, True], extreme_fences={},
                  mt_fraction=None, mt_reason="mitochondrial_rule_unconfirmed")
        plots.qc_figures(None, qc, dict(kind="qc", panel="distribution", histogram_bins=3))
        assert len(captured[-1].axes[0].patches) == 6
    finally:
        for fig in captured:
            plots.plt.close(fig)
