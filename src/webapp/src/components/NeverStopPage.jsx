import { useCallback, useState } from 'react';
import { createPortal } from 'react-dom';
import NeverStopApp from '../../never-stop/ui/App.jsx';
import neverStopStyles from '../../never-stop/ui/style.css?inline';

export default function NeverStopPage({ isVisible, openRequest }) {
  const [shadowRoot, setShadowRoot] = useState(null);
  const attachHost = useCallback((host) => {
    if (host) setShadowRoot(host.shadowRoot || host.attachShadow({ mode: 'open' }));
  }, []);
  const bridgeAvailable = typeof window !== 'undefined' &&
    typeof window.vantagePlatform?.neverStop?.invoke === 'function';

  return (
    <div className="never-stop-page-host" ref={attachHost} style={{ minHeight: '70vh' }}>
      {shadowRoot && createPortal(
        <>
          <style>{neverStopStyles}</style>
          {bridgeAvailable ? (
            <NeverStopApp isVisible={isVisible} openRequest={openRequest} />
          ) : (
            <div role="alert">Never Stop 本地连接不可用。请重新启动 Vantage 后重试。</div>
          )}
        </>,
        shadowRoot,
      )}
    </div>
  );
}
