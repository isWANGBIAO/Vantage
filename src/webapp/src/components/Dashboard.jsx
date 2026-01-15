import { useState, useEffect } from 'react';
import CameraFeed from './CameraFeed';
import { Activity, Cpu, HardDrive, Database, Clock, Calendar, Image as ImageIcon, Monitor } from 'lucide-react';

export default function Dashboard() {
    const [stats, setStats] = useState(null);
    const [latestImages, setLatestImages] = useState({ photo: null, screenshot: null });
    const [time, setTime] = useState(new Date());
    const [storageEstimate, setStorageEstimate] = useState({ daysLeft: 0, groupSizeMB: 0 });

    useEffect(() => {
        const timer = setInterval(() => setTime(new Date()), 1000);

        const fetchStats = async () => {
            try {
                const res = await fetch('/api/sys_stats');
                const data = await res.json();
                setStats(data);
            } catch (err) {
                console.error("Failed to fetch stats", err);
            }
        };

        const fetchLatestImages = async () => {
            try {
                const res = await fetch('/api/latest_images');
                const data = await res.json();
                setLatestImages(data);

                // Estimate Size if we have images
                if (data.photo && data.screenshot) {
                    estimateStorage(data.photo, data.screenshot);
                }
            } catch (err) {
                console.error("Failed to fetch latest images", err);
            }
        };

        const estimateStorage = async (photoUrl, screenUrl) => {
            try {
                const [pRes, sRes] = await Promise.all([
                    fetch(photoUrl, { method: 'HEAD' }),
                    fetch(screenUrl, { method: 'HEAD' })
                ]);
                const pSize = parseInt(pRes.headers.get('content-length') || 0);
                const sSize = parseInt(sRes.headers.get('content-length') || 0);
                const groupSizeBytes = pSize + sSize;
                const groupSizeMB = groupSizeBytes / (1024 * 1024);

                // Get Free Space from existing stats or fetch again? 
                // We rely on stats being passed or fetch logs.
                // We'll update the estimate state.
                setStorageEstimate(prev => ({ ...prev, groupSizeMB, groupSizeBytes }));
            } catch (e) {
                console.error("Error estimating storage", e);
            }
        };

        fetchStats();
        fetchLatestImages();
        const statsInterval = setInterval(fetchStats, 5000);
        const imagesInterval = setInterval(fetchLatestImages, 10000);

        return () => {
            clearInterval(timer);
            clearInterval(statsInterval);
            clearInterval(imagesInterval);
        };
    }, []);

    // Calculate Days Left
    const daysLeft = (stats && storageEstimate.groupSizeBytes > 0)
        ? ((stats.disk_free_gb * 1024 * 1024 * 1024) / storageEstimate.groupSizeBytes) * 10 / 86400
        : 0;

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
            {/* Top Row: Time and Basic Info */}
            <div className="glass-panel" style={{ padding: '1.5rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                    <h2 style={{ margin: 0, fontSize: '1.8rem', display: 'flex', alignItems: 'center', gap: '0.8rem' }}>
                        <Activity color="var(--primary-color)" />
                        System Dashboard
                    </h2>
                    <p style={{ margin: '0.5rem 0 0 0', color: 'var(--text-secondary)' }}>Real-time monitoring and statistics</p>
                </div>
                <div style={{ textAlign: 'right', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                    <div style={{ fontSize: '2rem', fontWeight: 'bold', fontFamily: 'monospace', display: 'flex', alignItems: 'center', gap: '0.8rem' }}>
                        <Clock size={28} color="var(--text-muted)" />
                        {time.toLocaleTimeString()}
                    </div>
                    <div style={{ color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: '0.5rem' }}>
                        <Calendar size={16} />
                        {time.toLocaleDateString()}
                    </div>
                </div>
            </div>

            {/* Middle Row: Camera and Latest Images */}
            <div style={{
                display: 'grid',
                gridTemplateColumns: '1.5fr 1fr',
                gap: '1.5rem',
                minHeight: '400px'
            }}>
                <div className="glass-panel" style={{ overflow: 'hidden', padding: '0' }}>
                    <CameraFeed />
                </div>

                <div style={{ display: 'grid', gridTemplateRows: '1fr 1fr', gap: '1.5rem' }}>
                    {/* Latest Photo */}
                    <div className="glass-panel" style={{ padding: '1rem', display: 'flex', flexDirection: 'column' }}>
                        <div style={{ marginBottom: '0.8rem', display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text-secondary)' }}>
                            <ImageIcon size={18} />
                            <h4 style={{ margin: 0 }}>Latest Photo</h4>
                        </div>
                        <div style={{ flex: 1, background: '#000', borderRadius: '8px', overflow: 'hidden', display: 'flex', alignItems: 'center', justifyContent: 'center', position: 'relative' }}>
                            {latestImages.photo ? (
                                <img src={latestImages.photo} alt="Latest" style={{ width: '100%', height: '100%', objectFit: 'contain' }} />
                            ) : (
                                <span style={{ color: 'var(--text-muted)' }}>No photo available</span>
                            )}
                        </div>
                        {latestImages.photo_name && <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '8px', textAlign: 'center', fontFamily: 'monospace' }}>{latestImages.photo_name}</div>}
                    </div>

                    {/* Latest Screenshot */}
                    <div className="glass-panel" style={{ padding: '1rem', display: 'flex', flexDirection: 'column' }}>
                        <div style={{ marginBottom: '0.8rem', display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text-secondary)' }}>
                            <Monitor size={18} />
                            <h4 style={{ margin: 0 }}>Latest Screenshot</h4>
                        </div>
                        <div style={{ flex: 1, background: '#000', borderRadius: '8px', overflow: 'hidden', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                            {latestImages.screenshot ? (
                                <img src={latestImages.screenshot} alt="Latest Screenshot" style={{ width: '100%', height: '100%', objectFit: 'contain' }} />
                            ) : (
                                <span style={{ color: 'var(--text-muted)' }}>No screenshot available</span>
                            )}
                        </div>
                        {latestImages.screenshot_name && <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '8px', textAlign: 'center', fontFamily: 'monospace' }}>{latestImages.screenshot_name}</div>}
                    </div>
                </div>
            </div>

            {/* Bottom Row: Stats Cards */}
            <div style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(4, 1fr)',
                gap: '1.5rem'
            }}>
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
                    value={`${stats?.storage_used_mb || 0} MB`}
                    subValue={`~${storageEstimate.groupSizeMB.toFixed(2)} MB/group`}
                    color="#55efc4"
                />
            </div>
        </div>
    );
}

function StatCard({ icon, title, value, subValue, color }) {
    return (
        <div className="glass-panel" style={{ padding: '1.5rem', position: 'relative', overflow: 'hidden', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            <div style={{
                position: 'absolute',
                top: 0, left: 0, width: '4px', height: '100%',
                background: color
            }}></div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.8rem', color: 'var(--text-secondary)' }}>
                {icon}
                <span style={{ fontSize: '0.9rem', fontWeight: 600 }}>{title}</span>
            </div>
            <div style={{ fontSize: '1.8rem', fontWeight: 'bold', marginTop: '0.5rem' }}>{value}</div>
            {subValue && <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>{subValue}</div>}
        </div>
    );
}
