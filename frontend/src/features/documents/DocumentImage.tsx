import { useEffect, useState } from 'react';
import { apiFetch } from '../../shared/api/client';
import { useI18n } from '../../shared/i18n';
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink';
import type { ImageMetadata } from './documentApi';
export default function DocumentImage({ image, url, onUnavailable }: {
    image: ImageMetadata;
    url: string;
    onUnavailable: () => void;
}) {
    const { t } = useI18n();
    const [loaded, setLoaded] = useState<{
        url: string;
        src: string;
    } | null>(null);
    const [error, setError] = useState('');
    const [attempt, setAttempt] = useState(0);
    const requestKey = `${url}:${attempt}`;
    const safeInline = image.inline_preview && ['image/png', 'image/jpeg'].includes(image.mime);
    useEffect(() => {
        if (!safeInline)
            return;
        const controller = new AbortController();
        let alive = true;
        let objectUrl = '';
        void apiFetch(url, { signal: controller.signal }).then(async (response) => {
            if ([401, 403].includes(response.status)) {
                onUnavailable();
                throw new Error('permission');
            }
            if (!response.ok)
                throw new Error('image');
            const blob = await response.blob();
            if (!alive || controller.signal.aborted)
                return;
            if (!['image/png', 'image/jpeg'].includes(blob.type))
                throw new Error('type');
            objectUrl = URL.createObjectURL(blob);
            setLoaded({ url: requestKey, src: objectUrl });
            setError('');
        }).catch(() => { if (alive && !controller.signal.aborted)
            setError(requestKey); });
        return () => { alive = false; controller.abort(); if (objectUrl)
            URL.revokeObjectURL(objectUrl); };
    }, [url, requestKey, safeInline, onUnavailable]);
    return <figure className="document-image">{loaded?.url === requestKey && <img src={loaded.src} alt={t('文档嵌入图片')}/>}<figcaption>{image.mime} · {image.size_bytes} {t('字节')}</figcaption>{error === requestKey && <><p role="alert">{t('图片读取失败，请重新读取图片。')}</p><button type="button" onClick={() => setAttempt(value => value + 1)}>{t('重新读取图片')}</button></>}{!safeInline && <p>{t('此图片格式仅提供下载。')}</p>}<ProjectDownloadLink href={url} filename={`embedded-image.${image.mime === 'image/png' ? 'png' : image.mime === 'image/jpeg' ? 'jpg' : 'bin'}`}>{t('下载嵌入图片')}</ProjectDownloadLink></figure>;
}
