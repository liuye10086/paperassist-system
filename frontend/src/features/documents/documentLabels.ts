export function documentSourceLabel(label: string, t: (s: string) => string) {
    if (t('正文来源') !== 'Body' || !/^(正文|分节)\s*[段落表格合并单元第行列节\d\s，]*$/.test(label))
        return label;
    return label.replace(/，第\s*(\d+)\s*行第\s*(\d+)\s*列/g, ', row $1 column $2').replace(/正文/g, 'Body').replace(/表格/g, ' Table ').replace(/合并单元格/g, ' Merged Cell ').replace(/单元格/g, ' Cell ').replace(/段落/g, ' Paragraph ').replace(/分节/g, 'Section ').replace(/\s+/g, ' ').trim();
}
