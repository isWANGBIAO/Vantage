import { useCallback, useEffect, useState } from 'react';
import FaceHistory from './FaceHistory';
import { useDisplayLanguage } from '../context/DisplayLanguageContext.jsx';
import { buildBackendUrl, fetchBackendJson } from '../utils/backendRequest.js';
import { loadSettingsState, saveSettingsState } from '../utils/settingsState.js';
import { getPlatformAdapter } from '../utils/platformAdapter.js';
import { assetPathForRecord, formatMetric, safeRecordName, visibleTrend } from '../utils/bodyAnalysisViewModel.js';

const DIRECTORY_FIELDS = {
  leg: 'bodyAnalysisLegDir',
  scalp: 'bodyAnalysisScalpDir',
  model: 'bodyAnalysisModelDir',
};

function displayDirectory(value) {
  return value ? safeRecordName(value.replace(/[\\/]+$/, '')) : '—';
}

function ReportImage({ path, report, label }) {
  const assetPath = assetPathForRecord(path, report?.assets);
  if (!assetPath) return null;
  return <figure style={{ margin: 0 }}><img src={buildBackendUrl(assetPath)} alt={label} loading="lazy" style={{ maxWidth: '100%', maxHeight: 250, borderRadius: 8 }} /><figcaption>{label}</figcaption></figure>;
}

function ReportSection({ kind, report, t }) {
  const records = Array.isArray(report?.[kind]?.records) ? report[kind].records : [];
  const trend = visibleTrend(report, kind);
  return (
    <section aria-label={t(kind === 'leg' ? 'body_analysis.tab.leg' : 'body_analysis.tab.scalp')}>
      <p>{t('body_analysis.record_count', { count: records.length })}</p>
      {trend.length === 0 && <p>{t('body_analysis.no_verified_trend')}</p>}
      {trend.length > 0 && <div style={{ overflowX: 'auto', marginBottom: 16 }}><table>
        <thead><tr><th>{t('body_analysis.captured_at')}</th><th>{t(kind === 'leg' ? 'body_analysis.hair_count' : 'body_analysis.hair_region')}</th><th>{t(kind === 'leg' ? 'body_analysis.density' : 'body_analysis.texture')}</th></tr></thead>
        <tbody>{trend.map((point) => <tr key={point.date}><td>{point.date}</td><td>{formatMetric(kind === 'leg' ? point.hair_count : point.hair_region_fraction_percent)}</td><td>{formatMetric(kind === 'leg' ? point.hair_density_per_mpx : point.texture_fraction_percent)}</td></tr>)}</tbody>
      </table></div>}
      {records.length === 0 && <p>{t('body_analysis.no_records')}</p>}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 16 }}>
        {records.map((record, index) => (
          <article className="glass-panel" key={`${kind}-${index}`} style={{ padding: 16 }}>
            <h3>{safeRecordName(record.file_name) || t('body_analysis.photo_number', { number: index + 1 })}</h3>
            <p>{t('body_analysis.captured_at')}: {record.timestamp_verified ? String(record.captured_at || '—') : t('body_analysis.date_unverified')}</p>
            <p>{t('body_analysis.review_status')}: {record.review_status === 'accepted' ? t('body_analysis.accepted') : t('body_analysis.unreviewed')}</p>
            <p>{t('body_analysis.texture')}: {formatMetric(record.texture_fraction_percent)}%</p>
            {kind === 'leg' && <p>{t('body_analysis.hair_count')}: {formatMetric(record.hair_count)}</p>}
            {kind === 'scalp' && <p>{t('body_analysis.hair_region')}: {formatMetric(record.hair_region_fraction_percent)}%</p>}
            {kind === 'scalp' && <p>{t('body_analysis.scalp_candidate_rejected')}</p>}
            {Array.isArray(record.quality_flags) && record.quality_flags.length > 0 && (
              <details><summary>{t('body_analysis.quality')}</summary><ul>{record.quality_flags.map((flag, flagIndex) => <li key={flagIndex}>{String(flag)}</li>)}</ul></details>
            )}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: 8, marginTop: 12 }}>
              <ReportImage path={record.overlay_path} report={report} label={t('body_analysis.overlay')} />
              <ReportImage path={record.mask_path} report={report} label={t('body_analysis.mask')} />
              <ReportImage path={record.texture_mask_path} report={report} label={t('body_analysis.texture_mask')} />
              <ReportImage path={record.line_mask_path} report={report} label={t('body_analysis.line_mask')} />
              {kind === 'scalp' && <ReportImage path={record.scalp_candidate_overlay_path} report={report} label={t('body_analysis.rejected_candidate')} />}
              {kind === 'scalp' && <ReportImage path={record.scalp_candidate_mask_path} report={report} label={t('body_analysis.rejected_candidate_mask')} />}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

export default function BodyAnalysis() {
  const { t } = useDisplayLanguage();
  const [subtab, setSubtab] = useState('dark-circles');
  const [settings, setSettings] = useState(null);
  const [status, setStatus] = useState(null);
  const [report, setReport] = useState(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');

  const refresh = useCallback(async () => {
    try {
      const nextStatus = await fetchBackendJson('/api/v1/body-analysis/status', { retryPolicy: 'poll' });
      setStatus(nextStatus);
      if (nextStatus.last_report_available) {
        try {
          const nextReport = await fetchBackendJson('/api/v1/body-analysis/report', { retryPolicy: 'poll' });
          if (nextReport?.complete === true && nextReport.schema_version === 1) setReport(nextReport);
        } catch {
          // Keep the last complete report while a refresh fails.
        }
      }
    } catch {
      setMessage(t('body_analysis.status_unavailable'));
    }
  }, [t]);

  useEffect(() => {
    let mounted = true;
    void loadSettingsState().then((state) => { if (mounted) setSettings(state.settings); }).catch(() => {
      if (mounted) setMessage(t('body_analysis.settings_unavailable'));
    });
    void refresh();
    const timer = window.setInterval(() => { void refresh(); }, 5000);
    return () => { mounted = false; window.clearInterval(timer); };
  }, [refresh, t]);

  const saveField = async (field, value) => {
    setBusy(true);
    setMessage('');
    try {
      const next = await saveSettingsState({ [field]: value });
      setSettings(next.settings);
      await refresh();
    } catch {
      setMessage(t('body_analysis.save_failed'));
    } finally {
      setBusy(false);
    }
  };

  const chooseDirectory = async (kind) => {
    try {
      const result = await getPlatformAdapter().paths.pickBodyAnalysisDirectory(kind);
      if (result?.path) await saveField(DIRECTORY_FIELDS[kind], result.path);
    } catch {
      setMessage(t('body_analysis.pick_failed'));
    }
  };

  const runAction = async (action) => {
    setBusy(true);
    setMessage('');
    try {
      await fetchBackendJson(`/api/v1/body-analysis/${action}`, { method: 'POST', retryPolicy: 'mutation' });
      await refresh();
    } catch {
      setMessage(t('body_analysis.action_failed'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section style={{ padding: '1rem', minHeight: '100%' }}>
      <h2>{t('body_analysis.title')}</h2>
      <nav aria-label={t('body_analysis.subpages')} style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        {[
          ['dark-circles', 'body_analysis.tab.dark_circles'],
          ['leg', 'body_analysis.tab.leg'],
          ['scalp', 'body_analysis.tab.scalp'],
        ].map(([key, label]) => <button type="button" key={key} aria-current={subtab === key ? 'page' : undefined} onClick={() => setSubtab(key)}>{t(label)}</button>)}
      </nav>
      {subtab === 'dark-circles' ? <FaceHistory isVisible /> : (
        <>
          <div className="glass-panel" style={{ padding: 16, marginBottom: 16 }}>
            <h3>{t('body_analysis.local_setup')}</h3>
            <p>{t('body_analysis.local_only')}</p>
            <label><input type="checkbox" checked={settings?.bodyAnalysisEnabled === true} disabled={busy || !settings} onChange={(event) => { void saveField('bodyAnalysisEnabled', event.target.checked); }} /> {t('body_analysis.auto_scan')}</label>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, marginTop: 12 }}>
              {Object.keys(DIRECTORY_FIELDS).map((kind) => <div key={kind}>
                <button type="button" disabled={busy || !getPlatformAdapter().capabilities.pickBodyAnalysisDirectory} onClick={() => { void chooseDirectory(kind); }}>{t(`body_analysis.choose_${kind}`)}</button>
                <span style={{ marginLeft: 8 }}>{displayDirectory(settings?.[DIRECTORY_FIELDS[kind]])}</span>
              </div>)}
            </div>
            <p>{t('body_analysis.status')}: {t(`body_analysis.status_${status?.status || 'unknown'}`)}</p>
            {status?.progress && <p>{t('body_analysis.progress', { done: status.progress.completed ?? 0, total: status.progress.total ?? 0 })}</p>}
            {status?.status === 'missing_environment' && <p>{t('body_analysis.environment_missing')}</p>}
            {status?.status === 'missing_environment' && <button type="button" disabled={busy} onClick={() => { void runAction('install'); }}>{t('body_analysis.install')}</button>}
            <button type="button" disabled={busy || settings?.bodyAnalysisEnabled !== true} onClick={() => { void runAction('retry'); }}>{t('body_analysis.retry')}</button>
            {message && <p role="alert">{message}</p>}
            {status?.error && <p role="alert">{t('body_analysis.action_failed')}</p>}
          </div>
          {report && <ReportSection kind={subtab} report={report} t={t} />}
          {!report && <p>{t('body_analysis.no_report')}</p>}
          {report && status?.status === 'running' && <p>{t('body_analysis.showing_previous_report')}</p>}
          {report && status?.status === 'failed' && <p>{t('body_analysis.showing_previous_report')}</p>}
        </>
      )}
    </section>
  );
}
