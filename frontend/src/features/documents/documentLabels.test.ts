import { afterEach, expect, test } from 'vitest';
import { apiError, setLocale, translate } from '../../shared/i18n';
import { documentSourceLabel } from './documentLabels';
afterEach(() => setLocale('zh-CN'));
test('English source coordinates translate generated labels but preserve user text', () => {
    setLocale('en');
    expect(documentSourceLabel('正文表格 1，第 2 行第 3 列', translate)).toBe('Body Table 1, row 2 column 3');
    expect(documentSourceLabel('正文表格 1单元格段落 2', translate)).toBe('Body Table 1 Cell Paragraph 2');
    expect(documentSourceLabel('分节 1', translate)).toBe('Section 1');
    expect(documentSourceLabel('正文表格 1合并单元格段落 2', translate)).toBe('Body Table 1 Merged Cell Paragraph 2');
    expect(documentSourceLabel('User heading', translate)).toBe('User heading');
});
test('document parser and version conflicts have bilingual public errors', () => {
    expect(translate(apiError({ code: 'document_parse_active' }, 'fallback'))).toBe('此文件已有解析任务，请等待完成后再建立新版本。');
    setLocale('en');
    expect(translate(apiError({ code: 'invalid_document' }, 'fallback'))).toBe('The document, image or page selection is invalid. Check the unencrypted Word/PDF or PNG/JPEG original and selected pages.');
});

test.each([
 ['document_changed','文档解析版本完整性核验失败，请核对原文件或重新解析。','The document parse version failed its integrity check. Check the original file or parse it again.'],
 ['document_missing','文档解析版本对象已缺失，请重新解析原文件。','The document parse version object is missing. Parse the original file again.'],
 ['image_not_found','此解析版本中的图片不存在，请刷新版本后核对。','The image does not exist in this parse version. Refresh versions and check again.'],
])('public document error %s is translated without displaying server prose', (code,zh,en)=>{
 const error=apiError({detail:{code,message:'RAW SERVER MESSAGE'}},'fallback')
 expect(translate(error)).toBe(zh)
 setLocale('en');expect(translate(error)).toBe(en)
})
