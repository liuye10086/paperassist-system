"""Minimal PDF fixtures; no PDF generation runtime dependency."""
def pdf_bytes(streams, *, rotation=0, encrypted=False, font=None):
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'']
    objects.append(font or b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>')
    kids=[]
    for stream in streams:
        page=len(objects)+1; kids.append(f'{page} 0 R')
        objects.append(f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 400] /Rotate {rotation} /Resources << /Font << /F1 3 0 R >> >> /Contents {page+1} 0 R >>'.encode())
        objects.append(b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'\nendstream')
    objects[1]=f'<< /Type /Pages /Kids [{" ".join(kids)}] /Count {len(kids)} >>'.encode()
    if encrypted:
        objects.append(b'<< /Filter /Standard /V 1 /R 2 /Length 40 /O <0000000000000000000000000000000000000000000000000000000000000000> /U <0000000000000000000000000000000000000000000000000000000000000000> /P -4 >>')
    output=bytearray(b'%PDF-1.4\n'); offsets=[0]
    for i,obj in enumerate(objects,1):
        offsets.append(len(output));output.extend(f'{i} 0 obj\n'.encode()+obj+b'\nendobj\n')
    start=len(output);output.extend(f'xref\n0 {len(objects)+1}\n0000000000 65535 f \n'.encode())
    for offset in offsets[1:]:output.extend(f'{offset:010d} 00000 n \n'.encode())
    encrypt=f' /Encrypt {len(objects)} 0 R /ID [<00><00>]' if encrypted else ''
    output.extend(f'trailer\n<< /Size {len(objects)+1} /Root 1 0 R{encrypt} >>\nstartxref\n{start}\n%%EOF'.encode());return bytes(output)

TEXT=b'BT /F1 12 Tf 20 350 Td (001.20 kg) Tj ET'
TABLE=b'20 200 m 220 200 l S 20 240 m 220 240 l S 20 280 m 220 280 l S 20 200 m 20 280 l S 120 200 m 120 280 l S 220 200 m 220 280 l S BT /F1 12 Tf 30 260 Td (A) Tj ET'

def chinese_pdf():
    font=b'<< /Type /Font /Subtype /Type0 /BaseFont /STSong-Light /Encoding /UniGB-UCS2-H /DescendantFonts [<< /Type /Font /Subtype /CIDFontType0 /BaseFont /STSong-Light /CIDSystemInfo << /Registry (Adobe) /Ordering (GB1) /Supplement 4 >> /DW 1000 >>] >>'
    return pdf_bytes([b'BT /F1 12 Tf 20 350 Td <4E2D6587> Tj ET'],font=font)
