"""Fixed system Python + UNO; one private pipe/profile per bounded subprocess."""
import argparse
import json
from pathlib import Path
import subprocess
import time
import uuid
from zipfile import ZipFile
import xml.etree.ElementTree as ET

import uno
from com.sun.star.beans import PropertyValue
from com.sun.star.document.MacroExecMode import NEVER_EXECUTE


def property_value(name, value):
    result = PropertyValue()
    result.Name, result.Value = name, value
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True)
    parser.add_argument('--profile', required=True)
    parser.add_argument('--cache')
    parser.add_argument('--pdf')
    args = parser.parse_args()
    pipe = 'pa_' + uuid.uuid4().hex
    connection = 'pipe,name=' + pipe + ';urp;StarOffice.ComponentContext'
    office = subprocess.Popen([
        'soffice', '-env:UserInstallation=' + Path(args.profile).as_uri(),
        '--headless', '--nologo', '--nodefault', '--nofirststartwizard', '--norestore',
        '--accept=' + connection], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    doc = desktop = None
    try:
        context = uno.getComponentContext()
        resolver = context.ServiceManager.createInstanceWithContext('com.sun.star.bridge.UnoUrlResolver', context)
        remote = None
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                remote = resolver.resolve('uno:' + connection)
                break
            except Exception:
                if office.poll() is not None:
                    raise RuntimeError('office exited')
                time.sleep(.1)
        if remote is None:
            raise RuntimeError('office connection timeout')
        desktop = remote.ServiceManager.createInstanceWithContext('com.sun.star.frame.Desktop', remote)
        doc = desktop.loadComponentFromURL(Path(args.source).as_uri(), '_blank', 0, (
            property_value('Hidden', True), property_value('ReadOnly', True),
            property_value('UpdateDocMode', 0), property_value('MacroExecutionMode', NEVER_EXECUTE)))
        if doc is None:
            raise RuntimeError('document unavailable')
        # Writer drops an empty Word TOC field on import. Materialize a real
        # UNO ContentIndex at our exact field bookmark in this disposable model;
        # its calculated text is merged back into the original Word field.
        with ZipFile(args.source) as package:
            metadata = json.loads(ET.fromstring(package.read('customXml/paperassist-layout.xml')).text)
        layout_index = None
        toc_fields = [field for field in metadata['fields'] if field['role'] == 'toc']
        if toc_fields:
            toc_anchor = doc.getBookmarks().getByName(toc_fields[0]['bookmark']).getAnchor()
            indexes = doc.getDocumentIndexes()
            for i in range(indexes.getCount()):
                candidate = indexes.getByIndex(i)
                try:
                    if doc.Text.compareRegionStarts(candidate.Anchor, toc_anchor) == 0:
                        layout_index = candidate
                        break
                except Exception:
                    pass
            if layout_index is None:
                layout_index = doc.createInstance('com.sun.star.text.ContentIndex')
                layout_index.CreateFromOutline = True
                layout_index.Level = metadata['options']['toc']['depth']
                layout_index.Title = ''
                doc.Text.insertTextContent(toc_anchor, layout_index, True)
        # Two passes allow changed TOC length to settle its own page references.
        for _ in range(3):
            doc.refresh()
            doc.getTextFields().refresh()
            indexes = doc.getDocumentIndexes()
            for index in range(indexes.getCount()):
                indexes.getByIndex(index).update()
            doc.calculateAll() if hasattr(doc, 'calculateAll') else None
        if args.cache:
            bookmarks = doc.getBookmarks()
            fields = {}
            for name in bookmarks.getElementNames():
                if name.startswith('PAF'):
                    fields[name] = bookmarks.getByName(name).getAnchor().getString()
            lines = []
            if layout_index is not None:
                lines.extend(layout_index.getAnchor().getString().splitlines())
            Path(args.cache).write_text(json.dumps({'fields': fields, 'toc_lines': lines}, ensure_ascii=False), encoding='utf-8')
        if args.pdf:
            doc.storeToURL(Path(args.pdf).as_uri(), (
                property_value('FilterName', 'writer_pdf_Export'),
                property_value('FilterData', (
                    property_value('UseLosslessCompression', True), property_value('ExportBookmarks', True))),
                property_value('Overwrite', True)))
    finally:
        if doc is not None:
            doc.close(True)
        if desktop is not None:
            desktop.terminate()
        try:
            office.wait(timeout=5)
        except subprocess.TimeoutExpired:
            office.kill()
            office.wait()


if __name__ == '__main__':
    main()
