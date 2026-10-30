"""Secret-free Linux child; untrusted data is opened only after sandbox entry."""
import os

for _name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS",
              "VECLIB_MAXIMUM_THREADS", "BLIS_NUM_THREADS"):
    os.environ[_name] = "1"

import json
import codecs
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from PIL import Image
from app.adapters.bio_parser.sandbox import enter_bio_sandbox
from app.adapters.bio_parser.visium import canonical_json, parse_registered_files, strict_json
from app.domain.bioinformatics.parser_contracts import BioParseError, PARSER_VERSION
from app.domain.bioinformatics.settings import BioLimits


def emit(value):
    sys.stdout.buffer.write(canonical_json(value))
    sys.stdout.buffer.flush()


def preload_runtime():
    # Codec registry lookup otherwise lazily imports a module after Landlock
    # denies reads outside the frozen input and output paths.
    codecs.lookup("utf-8-sig")
    Image.init()


def main():
    # The bounded, trusted path metadata arrives first, but no source bytes are
    # opened until Landlock and resource limits have succeeded.
    sys.stdout.buffer.write(b"READY\n")
    sys.stdout.buffer.flush()
    try:
        header = sys.stdin.buffer.read(4)
        if len(header) != 4:
            raise ValueError()
        length = struct.unpack("!I", header)[0]
        if not 0 < length <= 65536:
            raise ValueError()
        payload = sys.stdin.buffer.read(length)
        if len(payload) != length or sys.stdin.buffer.read(1):
            raise ValueError()
        metadata = strict_json(payload)
        limits = BioLimits.model_validate(metadata["settings"])
        manifest, output = metadata["input_manifest"], Path(metadata["output_directory"])
        if manifest["parser_version"] != PARSER_VERSION:
            raise ValueError()
        preload_runtime()
        pinned_fds = enter_bio_sandbox(manifest["files"], output, limits, int(sys.argv[1]))
    except MemoryError:
        emit({"error": {"code": "bio_parse_resource_limit"}})
        return
    except PermissionError:
        emit({"error": {"code": "bio_environment_unavailable"}})
        return
    except Exception:
        emit({"error": {"code": "bio_environment_unavailable"}})
        return
    try:
        result = parse_registered_files(manifest["files"], output, limits).summary()
        if len(canonical_json(result)) > limits.max_output_json_bytes:
            raise BioParseError("bio_input_limit", "result_json")
        emit({"result": result})
    except BioParseError as exc:
        emit({"error": {"code": exc.code}})
    except MemoryError:
        emit({"error": {"code": "bio_parse_resource_limit"}})
    except PermissionError:
        emit({"error": {"code": "bio_environment_unavailable"}})
    except Exception:
        emit({"error": {"code": "bio_matrix_invalid"}})
    finally:
        for fd in pinned_fds:
            os.close(fd)


if __name__ == "__main__":
    main()
