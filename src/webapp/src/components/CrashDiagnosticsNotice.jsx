import { useEffect, useState } from 'react';
import { getPlatformAdapter } from '../utils/platformAdapter';
import { useDisplayLanguage } from '../context/DisplayLanguageContext.jsx';

export default function CrashDiagnosticsNotice() {
  const { t } = useDisplayLanguage();
  const [visible, setVisible] = useState(false);
  const [openFailed, setOpenFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getPlatformAdapter().diagnostics.getStatus().then((status) => {
      if (!cancelled) setVisible(Boolean(status?.previousInterrupted));
    }).catch(() => {});
    return () => { cancelled = true; };
  }, []);

  if (!visible) return null;

  const openRecords = async () => {
    try {
      const result = await getPlatformAdapter().diagnostics.openDirectory();
      setOpenFailed(!result?.opened);
    } catch {
      setOpenFailed(true);
    }
  };

  return (
    <aside className="crash-diagnostics-notice" role="status">
      <div>
        <p>{t('diagnostics.interrupted')}</p>
        {openFailed ? <p>{t('diagnostics.open_failed')}</p> : null}
      </div>
      <button type="button" className="secondary-button" onClick={openRecords}>{t('diagnostics.open')}</button>
      <button type="button" className="secondary-button" onClick={() => setVisible(false)}>{t('diagnostics.dismiss')}</button>
    </aside>
  );
}
