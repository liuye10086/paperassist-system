"""Read accession/declaration metadata without evaluating or fetching it."""
import re

from defusedxml import ElementTree

from app.domain.bioinformatics.parser_contracts import BioParseError


def parse_geo(content, filename):
    try:
        text = content.decode("utf-8-sig")
    except UnicodeError:
        raise BioParseError("bio_format_unsupported", "metadata_encoding") from None
    if filename.lower().endswith(".xml"):
        try:
            ElementTree.fromstring(content)
        except Exception:
            raise BioParseError("bio_archive_invalid", "xml_integrity") from None
    accessions = {"gse": sorted(set(re.findall(r"\bGSE[0-9]+\b", text))),
                  "gsm": sorted(set(re.findall(r"\bGSM[0-9]+\b", text)))}
    empty = False
    if "!series_matrix_table_begin" in text:
        body = text.split("!series_matrix_table_begin", 1)[1].split("!series_matrix_table_end", 1)[0]
        records = [line for line in body.splitlines() if line.strip()]
        empty = len(records) <= 1
    # Only explicit declarations are copied; bounded text remains untrusted data.
    declarations = [line[:4096] for line in text.splitlines()
                    if line.startswith(("!Series_", "!Sample_", "^SERIES", "^SAMPLE"))][:256]
    return {"accessions": accessions, "empty_series_matrix": empty, "declarations": declarations}
