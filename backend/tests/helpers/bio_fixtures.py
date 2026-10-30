"""Tiny deterministic Visium inputs; never read research originals."""
import gzip
import io
import json
import tarfile

from PIL import Image


def bundle_from_parts(parts):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as archive:
        for name, value in sorted(parts.items()):
            info = tarfile.TarInfo(name)
            info.size = len(value)
            archive.addfile(info, io.BytesIO(value))
    return output.getvalue()


def visium_parts(*, duplicate_coordinate=False, missing_barcode=False):
    records = ["1 1 5", "2 1 2", "1 2 1", "3 2 4"]
    if duplicate_coordinate:
        records.append("1 1 7")
    image = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(image, format="PNG")
    return {
        "matrix.mtx": ("%%MatrixMarket matrix coordinate integer general\n"
                       f"3 2 {len(records)}\n" + "\n".join(records) + "\n").encode(),
        "features.tsv": b"ENSG_TEST_1\tG1\tGene Expression\nENSG_TEST_2\tSAME\tGene Expression\nENSG_TEST_3\tSAME\tGene Expression\n",
        "barcodes.tsv": b"AA-1\n" if missing_barcode else b"AA-1\nBB-1\n",
        "tissue_positions_list.csv": b"AA-1,1,0,0,2,2\nBB-1,1,1,1,4,4\nCC-1,0,2,2,6,6\n",
        "scalefactors_json.json": json.dumps({"tissue_hires_scalef": 1.0, "tissue_lowres_scalef": 1.0,
            "spot_diameter_fullres": 1.0, "fiducial_diameter_fullres": 1.0}, sort_keys=True).encode(),
        "tissue_hires_image.png": image.getvalue(),
        "tissue_lowres_image.png": image.getvalue(),
    }


def visium_bundle_bytes(*, unsafe_name=None, duplicate_coordinate=False, missing_barcode=False, changes=None):
    parts = visium_parts(duplicate_coordinate=duplicate_coordinate, missing_barcode=missing_barcode)
    if changes:
        for name, content in changes.items():
            if content is None:
                parts.pop(name, None)
            else:
                parts[name] = content
    members = {"GSM9999999_" + name + ".gz": gzip.compress(value, mtime=0) for name, value in parts.items()}
    if unsafe_name is not None:
        members[unsafe_name] = b"unsafe"
    return bundle_from_parts(members)
