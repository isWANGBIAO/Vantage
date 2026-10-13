import { useEffect, useState } from 'react';
import { useDisplayLanguage } from '../context/DisplayLanguageContext.jsx';
import { fetchBackendJson } from '../utils/backendRequest';
import { normalizeFaceLocalSettings } from '../utils/faceLocalSettings';

const inputStyle = { width: '100%', padding: '0.65rem', borderRadius: '8px', border: '1px solid var(--border-color)', background: 'var(--bg-surface)', color: 'var(--text-primary)', boxSizing: 'border-box' };

export default function FaceAnalysisSettings({ onSaved, analysisRunning = false }) {
  const { t } = useDisplayLanguage();
  const [settings, setSettings] = useState(normalizeFaceLocalSettings());
  const [localStatus, setLocalStatus] = useState(null);
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    fetchBackendJson('/api/v1/settings', { retryPolicy: 'load', signal: controller.signal })
      .then((state) => { setSettings(normalizeFaceLocalSettings(state.settings)); setLoaded(true); })
      .catch((failure) => { if (failure.name !== 'AbortError') setError(failure.message); });
    fetchBackendJson('/api/v1/face/local-status', { retryPolicy: 'load', signal: controller.signal })
      .then(setLocalStatus)
      .catch((failure) => { if (failure.name !== 'AbortError') setLocalStatus({ ready: false, message: t('face_local.status_unavailable') }); });
    return () => controller.abort();
  }, [t]);

  const update = (field, value) => {
    setSettings((current) => ({ ...current, [field]: value }));
    setSaved(false);
  };
  const save = async (event) => {
    event.preventDefault();
    setSaving(true);
    setError('');
    setSaved(false);
    try {
      const state = await fetchBackendJson('/api/v1/settings', {
        method: 'PUT', retryPolicy: 'mutation', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(normalizeFaceLocalSettings(settings)),
      });
      setSettings(normalizeFaceLocalSettings(state.settings));
      setSaved(true);
      await onSaved?.();
      try {
        setLocalStatus(await fetchBackendJson('/api/v1/face/local-status', { retryPolicy: 'load' }));
      } catch {
        setLocalStatus({ ready: false, message: t('face_local.status_unavailable') });
      }
    } catch (failure) {
      setError(failure.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <form className="glass-panel" onSubmit={save} style={{ padding: '1.5rem', display: 'grid', gap: '1rem' }}>
      <h3 style={{ margin: 0 }}>{t('face_local.title')}</h3>
      <p style={{ margin: 0, color: 'var(--text-secondary)' }}>{t('face_local.external_only')}</p>
      <fieldset disabled={!loaded || saving || analysisRunning} style={{ border: 0, margin: 0, padding: 0, display: 'grid', gap: '1rem' }}>
        <label>
          <span>{t('face_local.method')}</span>
          <select value={settings.face_analysis_method} onChange={(event) => update('face_analysis_method', event.target.value)} style={inputStyle}>
            <option value="onnx">{t('face_local.onnx')}</option>
            <option value="sam3">{t('face_local.sam3')}</option>
          </select>
        </label>
        {settings.face_analysis_method === 'onnx' ? (
          <label>
            <span>{t('face_local.python')}</span>
            <input type="text" value={settings.face_analysis_python} onChange={(event) => update('face_analysis_python', event.target.value)} style={inputStyle} autoComplete="off" spellCheck={false} />
          </label>
        ) : (
          <label>
            <span>{t('face_local.sam3_python')}</span>
            <input type="text" value={settings.face_analysis_sam3_python} onChange={(event) => update('face_analysis_sam3_python', event.target.value)} style={inputStyle} autoComplete="off" spellCheck={false} />
            <small style={{ color: 'var(--text-secondary)' }}>{t('face_local.sam3_python_hint')}</small>
          </label>
        )}
        {settings.face_analysis_method === 'onnx' ? (
          <label>
            <span>{t('face_local.onnx_path')}</span>
            <input type="text" value={settings.face_analysis_onnx_model} onChange={(event) => update('face_analysis_onnx_model', event.target.value)} style={inputStyle} autoComplete="off" spellCheck={false} />
          </label>
        ) : (
          <label>
            <span>{t('face_local.sam3_path')}</span>
            <input type="text" value={settings.face_analysis_sam3_model_dir} onChange={(event) => update('face_analysis_sam3_model_dir', event.target.value)} style={inputStyle} autoComplete="off" spellCheck={false} />
          </label>
        )}
        <button type="submit" style={{ justifySelf: 'start' }}>{saving ? t('face_local.saving') : t('face_local.save')}</button>
      </fieldset>
      {localStatus && <div role="status">{t('face_local.status')}: {localStatus.method?.toUpperCase()} · {localStatus.ready ? t('face_local.ready') : t('face_local.not_ready')}{localStatus.message ? ` — ${localStatus.message}` : ''}</div>}
      {saved && <div role="status">{t('face_local.saved')}</div>}
      {error && <div role="alert" style={{ color: 'var(--error-color, #ff5757)' }}>{t('face_history.error_prefix', { error })}</div>}
    </form>
  );
}
