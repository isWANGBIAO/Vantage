import { useState, useEffect } from 'react';
import { RefreshCw, Wallet, Clock, Coins, BarChart3, ClipboardList } from 'lucide-react';

const formatNumber = (value, digits = 2) => {
    if (value === null || value === undefined || Number.isNaN(value)) return '--';
    if (typeof value === 'number') {
        return value.toLocaleString(undefined, { maximumFractionDigits: digits });
    }
    return value;
};

const formatCurrency = (value) => formatNumber(value, 2);

function MetricRow({ label, value, hint }) {
    return (
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', alignItems: 'baseline' }}>
            <span style={{ color: 'var(--text-secondary)' }}>{label}</span>
            <span style={{ fontWeight: 600 }}>{value}</span>
            {hint && <span style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>{hint}</span>}
        </div>
    );
}

function SheetTable({ sheet }) {
    return (
        <div className="glass-panel" style={{ padding: '1rem 1.2rem', display: 'flex', flexDirection: 'column', gap: '0.8rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                    <h3 style={{ margin: 0, fontSize: '1.05rem' }}>{sheet.name}</h3>
                    <p style={{ margin: 0, color: 'var(--text-muted)', fontSize: '0.8rem' }}>
                        共 {sheet.row_count} 行{sheet.truncated ? '（已截断）' : ''}
                    </p>
                </div>
            </div>
            <div style={{ overflowX: 'auto', maxHeight: '420px', overflowY: 'auto', border: '1px solid var(--border-color)', borderRadius: '10px' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem' }}>
                    <thead style={{ position: 'sticky', top: 0, background: 'var(--bg-surface)' }}>
                        <tr>
                            {sheet.columns.map((col, idx) => (
                                <th key={idx} style={{ textAlign: 'left', padding: '0.6rem', borderBottom: '1px solid var(--border-color)', color: 'var(--text-secondary)' }}>
                                    {col}
                                </th>
                            ))}
                        </tr>
                    </thead>
                    <tbody>
                        {sheet.rows.map((row, rowIndex) => (
                            <tr key={rowIndex} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                                {row.map((cell, cellIndex) => (
                                    <td key={cellIndex} style={{ padding: '0.6rem', color: 'var(--text-primary)' }}>
                                        {cell === null || cell === undefined || cell === '' ? '--' : String(cell)}
                                    </td>
                                ))}
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
}

export default function ExpenseSheet() {
    const [data, setData] = useState(null);
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState('');
    const [isRefreshing, setIsRefreshing] = useState(false);

    const fetchData = async () => {
        setIsLoading(true);
        setError('');
        try {
            const res = await fetch('http://localhost:8000/api/balance_sheet');
            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.error || 'Failed to load balance sheet');
            }
            const payload = await res.json();
            setData(payload);
        } catch (err) {
            setError(err.message || '加载失败');
        }
        setIsLoading(false);
        setIsRefreshing(false);
    };

    useEffect(() => {
        fetchData();
    }, []);

    const handleRefresh = () => {
        setIsRefreshing(true);
        fetchData();
    };

    const summary = data?.summary || {};
    const timeCost = summary.time_cost || {};
    const assets = summary.assets || {};
    const budget = summary.budget || {};

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
            <div className="glass-panel" style={{ padding: '1.2rem 1.5rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                    <h2 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
                        <Wallet size={20} color="var(--primary-color)" />
                        开销表
                    </h2>
                    <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                        来源：{data?.source?.path || 'Balance Sheet.xlsx'}  ｜ 更新：{data?.source?.updated_at || '--'}
                    </p>
                </div>
                <button
                    onClick={handleRefresh}
                    disabled={isRefreshing}
                    style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', padding: '0.6rem 1.2rem' }}
                >
                    <RefreshCw size={16} className={isRefreshing ? 'spin-animation' : ''} />
                    {isRefreshing ? '刷新中...' : '刷新'}
                </button>
            </div>

            {isLoading && (
                <div className="glass-panel" style={{ padding: '1.2rem', textAlign: 'center', color: 'var(--text-muted)' }}>
                    正在加载开销数据...
                </div>
            )}

            {error && (
                <div className="glass-panel" style={{ padding: '1.2rem', color: '#ff7675' }}>
                    {error}
                </div>
            )}

            {!isLoading && !error && (
                <>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '1.2rem' }}>
                        <div className="glass-panel" style={{ padding: '1.2rem', display: 'flex', flexDirection: 'column', gap: '0.8rem' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
                                <Clock size={18} color="var(--accent-color)" />
                                <span style={{ fontWeight: 600 }}>时间成本</span>
                            </div>
                            <MetricRow label="全天均摊每分钟" value={formatCurrency(timeCost.per_minute)} />
                            <MetricRow label="全月均摊每天" value={formatCurrency(timeCost.per_day_month)} />
                            <MetricRow label="日均支出" value={formatCurrency(timeCost.daily_average)} />
                            <MetricRow label="月度总支出" value={formatCurrency(timeCost.monthly_total)} />
                        </div>

                        <div className="glass-panel" style={{ padding: '1.2rem', display: 'flex', flexDirection: 'column', gap: '0.8rem' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
                                <Coins size={18} color="#f39c12" />
                                <span style={{ fontWeight: 600 }}>资产结构</span>
                            </div>
                            <MetricRow label="固定资产" value={formatCurrency(assets.fixed_assets?.value)} />
                            <MetricRow label="流动资产" value={formatCurrency(assets.current_assets?.value)} />
                            <MetricRow label="总资产" value={formatCurrency(assets.total_assets?.value)} />
                            <MetricRow label="负债合计" value={formatCurrency(assets.liabilities?.value)} />
                            <MetricRow label="净资产" value={formatCurrency(assets.equity?.value)} />
                            <MetricRow label="现金+股票" value={formatCurrency(assets.cash_and_stock?.value)} />
                        </div>

                        <div className="glass-panel" style={{ padding: '1.2rem', display: 'flex', flexDirection: 'column', gap: '0.8rem' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
                                <ClipboardList size={18} color="#74b9ff" />
                                <span style={{ fontWeight: 600 }}>预算</span>
                            </div>
                            <MetricRow label="每月必须开支" value={formatCurrency(budget.monthly_required)} />
                            <MetricRow label="每月非必须开支" value={formatCurrency(budget.monthly_optional)} />
                        </div>

                        <div className="glass-panel" style={{ padding: '1.2rem', display: 'flex', flexDirection: 'column', gap: '0.8rem' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
                                <BarChart3 size={18} color="#55efc4" />
                                <span style={{ fontWeight: 600 }}>优化建议</span>
                            </div>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem', color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
                                {(data?.suggestions || []).map((item, idx) => (
                                    <div key={idx} style={{ display: 'flex', gap: '0.6rem' }}>
                                        <span style={{ color: 'var(--accent-color)' }}>•</span>
                                        <span>{item}</span>
                                    </div>
                                ))}
                            </div>
                        </div>
                    </div>

                    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                        {data?.sheets?.map((sheet) => (
                            <SheetTable key={sheet.name} sheet={sheet} />
                        ))}
                    </div>
                </>
            )}
        </div>
    );
}



