import { useEffect, useState, useCallback } from 'react';
import CameraFeed from './CameraFeed';
import './Dashboard.css';
import {
  Activity,
  Cpu,
  HardDrive,
  Database,
  Clock,
  Calendar,
  Image as ImageIcon,
  Monitor,
  Wind,
  Heart,
} from 'lucide-react';
import { buildBackendUrl, fetchBackend, fetchBackendJson } from '../utils/backendRequest';
import { shouldUseDashboardGeolocation } from './dashboardAqiPolicy.js';

async function getGeolocationPermissionState() {
  if (!navigator.permissions?.query) {
    return null;
  }

  try {
    const permissionStatus = await navigator.permissions.query({ name: 'geolocation' });
    return permissionStatus.state;
  } catch {
    return null;
  }
}

export default function Dashboard({ isVisible = false }) {
  const [stats, setStats] = useState(null);
  const [latestImages, setLatestImages] = useState({ photo: null, screenshot: null });
  const [time, setTime] = useState(new Date());
  const [storageEstimate, setStorageEstimate] = useState({ daysLeft: 0, groupSizeMB: 0 });
  const [aqi, setAqi] = useState(null);
  const [healthStats, setHealthStats] = useState(null);

  const estimateStorage = useCallback(async (photoUrl, screenUrl) => {
    try {
      const [photoResponse, screenshotResponse] = await Promise.all([
        fetchBackend(photoUrl, { method: 'HEAD', retryPolicy: 'poll' }),
        fetchBackend(screenUrl, { method: 'HEAD', retryPolicy: 'poll' }),
      ]);

      const photoSize = parseInt(photoResponse.headers.get('content-length') || 0, 10);
      const screenshotSize = parseInt(screenshotResponse.headers.get('content-length') || 0, 10);
      const groupSizeBytes = photoSize + screenshotSize;

      setStorageEstimate({
        groupSizeMB: groupSizeBytes / (1024 * 1024),
        groupSizeBytes,
      });
    } catch (err) {
      console.error('Error estimating storage', err);
    }
  }, []);

  const fetchStats = useCallback(async () => {
    try {
      const data = await fetchBackendJson('/api/sys_stats', { retryPolicy: 'poll' });
      setStats(data);
    } catch (err) {
      console.error('Failed to fetch stats', err);
    }
  }, []);

  const fetchLatestImages = useCallback(async () => {
    try {
      const data = await fetchBackendJson('/api/latest_images', { retryPolicy: 'poll' });

      if (data.photo?.startsWith('/')) {
        data.photo = buildBackendUrl(data.photo);
      }

      if (data.screenshot?.startsWith('/')) {
        data.screenshot = buildBackendUrl(data.screenshot);
      }

      setLatestImages(data);

      if (data.photo && data.screenshot) {
        estimateStorage(data.photo, data.screenshot);
      }
    } catch (err) {
      console.error('Failed to fetch latest images', err);
    }
  }, [estimateStorage]);

  const fetchAqiBackend = useCallback(async (lat, lon) => {
    try {
      let url = '/api/aqi';
      if (lat !== null && lon !== null) {
        url += `?lat=${lat}&lon=${lon}`;
      }

      const res = await fetchBackend(url, { retryPolicy: 'poll', allowHttpError: true });
      if (!res.ok) {
        return;
      }

      const data = await res.json();
      setAqi(data);
    } catch (err) {
      console.error('Failed to fetch AQI', err);
    }
  }, []);

  const fetchAqi = useCallback(async ({ allowPrompt = false } = {}) => {
    if (!navigator.geolocation) {
      void fetchAqiBackend(null, null);
      return;
    }

    const permissionState = await getGeolocationPermissionState();
    if (!shouldUseDashboardGeolocation({ isVisible: allowPrompt, permissionState })) {
      void fetchAqiBackend(null, null);
      return;
    }

    navigator.geolocation.getCurrentPosition(
      (position) => {
        const { latitude, longitude } = position.coords;
        void fetchAqiBackend(latitude, longitude);
      },
      (error) => {
        if (error.code !== 1) {
          console.error('Geolocation error:', error);
        }
        void fetchAqiBackend(null, null);
      },
      { timeout: 10000, maximumAge: 600000 },
    );
  }, [fetchAqiBackend]);

  const fetchHealth = useCallback(async () => {
    try {
      const res = await fetchBackend('/api/health/sedentary', {
        retryPolicy: 'poll',
        allowHttpError: true,
      });
      if (!res.ok) {
        return;
      }

      const data = await res.json();
      setHealthStats(data);
    } catch (err) {
      console.error('Failed to fetch health stats', err);
    }
  }, []);

  const openFolder = async (type) => {
    try {
      const res = await fetchBackend('/api/open_folder', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type }),
        retryPolicy: 'mutation',
        allowHttpError: true,
      });
      const data = await res.json();

      if (!res.ok) {
        alert(`Failed to open folder: ${data.error || 'Unknown error'}`);
      }
    } catch (err) {
      console.error('Failed to open folder', err);
      alert('Network error or server unreachable');
    }
  };

  useEffect(() => {
    const timer = setInterval(() => setTime(new Date()), 1000);
    const bootstrapTimer = setTimeout(() => {
      void fetchStats();
      void fetchLatestImages();
      void fetchAqi({ allowPrompt: isVisible });
      void fetchHealth();
    }, 0);

    const statsInterval = setInterval(() => void fetchStats(), 5000);
    const imagesInterval = setInterval(() => void fetchLatestImages(), 10000);
    const aqiInterval = setInterval(() => void fetchAqi({ allowPrompt: isVisible }), 600000);
    const healthInterval = setInterval(() => void fetchHealth(), 10000);

    return () => {
      clearInterval(timer);
      clearTimeout(bootstrapTimer);
      clearInterval(statsInterval);
      clearInterval(imagesInterval);
      clearInterval(aqiInterval);
      clearInterval(healthInterval);
    };
  }, [fetchStats, fetchLatestImages, fetchAqi, fetchHealth, isVisible]);

  const daysLeft = stats && storageEstimate.groupSizeBytes > 0
    ? ((stats.disk_free_gb * 1024 * 1024 * 1024) / storageEstimate.groupSizeBytes) * 10 / 86400
    : 0;

  return (
    <div className="dashboard-page">
      <div className="glass-panel dashboard-top-row">
        <div>
          <h2
            style={{
              margin: 0,
              fontSize: '1.5rem',
              display: 'flex',
              alignItems: 'center',
              gap: '0.8rem',
            }}
          >
            <Activity color="var(--primary-color)" size={24} />
            System Dashboard
          </h2>
          <div className="dashboard-actions">
            <button
              className="dashboard-quick-button"
              onClick={() => openFolder('photo')}
              style={{
                background: 'rgba(255,255,255,0.1)',
                border: '1px solid rgba(255,255,255,0.2)',
                color: 'var(--text-primary)',
                padding: '0.3rem 0.8rem',
                borderRadius: '4px',
                cursor: 'pointer',
                fontSize: '0.8rem',
                display: 'flex',
                alignItems: 'center',
                gap: '0.4rem',
              }}
            >
              <ImageIcon size={14} />
              Open Photos
            </button>
            <button
              className="dashboard-quick-button"
              onClick={() => openFolder('screenshot')}
              style={{
                background: 'rgba(255,255,255,0.1)',
                border: '1px solid rgba(255,255,255,0.2)',
                color: 'var(--text-primary)',
                padding: '0.3rem 0.8rem',
                borderRadius: '4px',
                cursor: 'pointer',
                fontSize: '0.8rem',
                display: 'flex',
                alignItems: 'center',
                gap: '0.4rem',
              }}
            >
              <Monitor size={14} />
              Open Screenshots
            </button>
          </div>
        </div>

        <div className="dashboard-clock-group">
          <div
            style={{
              fontSize: '1.6rem',
              fontWeight: 'bold',
              fontFamily: 'monospace',
              display: 'flex',
              alignItems: 'center',
              gap: '0.8rem',
            }}
          >
            <Clock size={24} color="var(--text-muted)" />
            {time.toLocaleTimeString()}
          </div>
          <div style={{ color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Calendar size={18} />
            {time.toLocaleDateString()}
          </div>
        </div>
      </div>

      <div className="dashboard-media-grid">
        <div
          className="glass-panel"
          style={{
            padding: 0,
            display: 'flex',
            flexDirection: 'column',
            aspectRatio: '16/9',
            overflow: 'hidden',
            width: '100%',
            position: 'relative',
          }}
        >
          <div
            style={{
              padding: '0.8rem',
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
              fontSize: '0.9rem',
              fontWeight: 600,
              color: 'var(--text-secondary)',
              position: 'absolute',
              top: 0,
              left: 0,
              zIndex: 10,
              background: 'linear-gradient(to bottom, rgba(0,0,0,0.8), transparent)',
              width: '100%',
            }}
          >
            <ImageIcon size={16} />
            Latest Photo
          </div>
          <div style={{ flex: 1, background: '#000', position: 'relative' }}>
            {latestImages.photo ? (
              <img src={latestImages.photo} alt="Latest" style={{ width: '100%', height: '100%', objectFit: 'contain' }} />
            ) : (
              <div
                style={{
                  width: '100%',
                  height: '100%',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  color: '#666',
                }}
              >
                No Data
              </div>
            )}
          </div>
          {latestImages.photo_name && (
            <div
              style={{
                fontSize: '0.75rem',
                color: 'rgba(255,255,255,0.7)',
                position: 'absolute',
                bottom: '4px',
                right: '8px',
                zIndex: 10,
                fontFamily: 'monospace',
                background: 'rgba(0,0,0,0.5)',
                padding: '2px 4px',
                borderRadius: '4px',
              }}
            >
              {latestImages.photo_name}
            </div>
          )}
        </div>

        <div
          className="glass-panel"
          style={{
            padding: 0,
            display: 'flex',
            flexDirection: 'column',
            aspectRatio: '16/9',
            overflow: 'hidden',
            width: '100%',
            position: 'relative',
            border: '1px solid var(--primary-color)',
            boxShadow: '0 0 15px rgba(0, 120, 215, 0.2)',
          }}
        >
          <div
            style={{
              padding: '0.8rem',
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
              fontSize: '0.9rem',
              fontWeight: 600,
              color: 'var(--primary-color)',
              position: 'absolute',
              top: 0,
              left: 0,
              zIndex: 10,
              background: 'linear-gradient(to bottom, rgba(0,0,0,0.8), transparent)',
              width: '100%',
            }}
          >
            <Activity size={16} />
            Camera Feed
          </div>
          <div style={{ flex: 1, position: 'relative' }}>
            <CameraFeed />
          </div>
        </div>

        <div
          className="glass-panel"
          style={{
            padding: 0,
            display: 'flex',
            flexDirection: 'column',
            aspectRatio: '16/9',
            overflow: 'hidden',
            width: '100%',
            position: 'relative',
          }}
        >
          <div
            style={{
              padding: '0.8rem',
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
              fontSize: '0.9rem',
              fontWeight: 600,
              color: 'var(--text-secondary)',
              position: 'absolute',
              top: 0,
              left: 0,
              zIndex: 10,
              background: 'linear-gradient(to bottom, rgba(0,0,0,0.8), transparent)',
              width: '100%',
            }}
          >
            <Monitor size={16} />
            Latest Screenshot
          </div>
          <div style={{ flex: 1, background: '#000', position: 'relative' }}>
            {latestImages.screenshot ? (
              <img src={latestImages.screenshot} alt="Screenshot" style={{ width: '100%', height: '100%', objectFit: 'contain' }} />
            ) : (
              <div
                style={{
                  width: '100%',
                  height: '100%',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  color: '#666',
                }}
              >
                No Data
              </div>
            )}
          </div>
          {latestImages.screenshot_name && (
            <div
              style={{
                fontSize: '0.75rem',
                color: 'rgba(255,255,255,0.7)',
                position: 'absolute',
                bottom: '4px',
                right: '8px',
                zIndex: 10,
                fontFamily: 'monospace',
                background: 'rgba(0,0,0,0.5)',
                padding: '2px 4px',
                borderRadius: '4px',
              }}
            >
              {latestImages.screenshot_name}
            </div>
          )}
        </div>
      </div>

      <div className="dashboard-stats-grid">
        <StatCard
          icon={<Cpu size={24} color="#a29bfe" />}
          title="CPU Usage"
          value={`${stats?.cpu_usage || 0}%`}
          color="#a29bfe"
        />
        <StatCard
          icon={<Activity size={24} color="#00d2d3" />}
          title="Memory"
          value={`${stats?.memory_used_gb || 0} GB`}
          subValue={`${stats?.memory_percent || 0}% Used`}
          color="#00d2d3"
        />
        <StatCard
          icon={<HardDrive size={24} color="#ff7675" />}
          title="Disk Free"
          value={`${stats?.disk_free_gb || 0} GB`}
          subValue={`~${daysLeft.toFixed(1)} Days left`}
          color="#ff7675"
        />
        <StatCard
          icon={<Database size={24} color="#55efc4" />}
          title="Storage Used"
          value={(() => {
            const mb = stats?.storage_used_mb || 0;
            return mb > 1024 ? `${(mb / 1024).toFixed(2)} GB` : `${mb} MB`;
          })()}
          subValue={`~${storageEstimate.groupSizeMB.toFixed(2)} MB/group`}
          color="#55efc4"
        />
        <StatCard
          icon={<Wind size={24} color={aqi?.color || '#b2bec3'} />}
          title="Air Quality (US)"
          value={aqi?.aqi ?? '--'}
          subValue={aqi ? `${aqi.city} - ${aqi.level}` : 'Loading...'}
          color={aqi?.color || '#b2bec3'}
          titleColor={aqi?.color}
        />
        <StatCard
          icon={(
            <Heart
              size={24}
              color={
                healthStats?.is_sitting && healthStats.duration_minutes >= (healthStats.threshold_minutes * 0.8)
                  ? '#e74c3c'
                  : '#2ecc71'
              }
            />
          )}
          title="Focus Time"
          value={healthStats && healthStats.is_sitting ? `${healthStats.duration_minutes} min` : 'Away'}
          subValue={healthStats?.is_sitting ? `Limit: ${healthStats.threshold_minutes} min` : 'Timer paused'}
          color={
            healthStats?.is_sitting && healthStats.duration_minutes >= (healthStats.threshold_minutes * 0.8)
              ? '#e74c3c'
              : '#2ecc71'
          }
        />
      </div>
    </div>
  );
}

function StatCard({ icon, title, value, subValue, color, titleColor }) {
  return (
    <div className="glass-panel dashboard-stat-card">
      <div
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          width: '4px',
          height: '100%',
          background: color,
        }}
      />
      <div className="dashboard-stat-header">
        {icon}
        <span style={{ fontSize: '0.9rem', fontWeight: 600, color: titleColor || 'inherit' }}>{title}</span>
      </div>
      <div className="dashboard-stat-value">{value}</div>
      {subValue && (
        <div className="dashboard-stat-subvalue" title={subValue}>
          {subValue}
        </div>
      )}
    </div>
  );
}
