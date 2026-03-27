import React, { useState, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Target, CheckCircle2, Circle, GitCommit, TrendingUp, RefreshCw, AlertCircle } from 'lucide-react';
import './ProjectProgress.css';
import { fetchBackendJson } from '../utils/backendRequest';

const ProjectProgress = () => {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    const fetchProgress = async () => {
        setLoading(true);
        setError(null);
        try {
            const result = await fetchBackendJson('/api/project_progress', { retryPolicy: 'load' });
            setData(result);
        } catch (error) {
            setError('Failed to load project progress. Make sure the backend is running.');
            console.error(error);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchProgress();
    }, []);

    if (loading) {
        return (
            <div className="progress-loading">
                <RefreshCw className="animate-spin" size={32} />
                <p>Loading project momentum...</p>
            </div>
        );
    }

    if (error) {
        return (
            <div className="progress-error">
                <AlertCircle size={48} />
                <h3>Error Loading Data</h3>
                <p>{error}</p>
                <button className="retry-btn" onClick={fetchProgress}>Retry</button>
            </div>
        );
    }

    if (!data) return null;

    const { tasks, commits, stats } = data;

    // Group pending tasks by project
    const pendingByProject = tasks.pending.reduce((acc, task) => {
        if (!acc[task.project]) acc[task.project] = [];
        acc[task.project].push(task);
        return acc;
    }, {});

    return (
        <div className="project-progress-container">
            <header className="progress-header">
                <div className="header-title">
                    <Target className="icon-target" size={28} />
                    <h2>Project Momentum</h2>
                </div>
                <button className="refresh-btn" onClick={fetchProgress} title="Refresh Data">
                    <RefreshCw size={18} />
                </button>
            </header>

            <div className="progress-dashboard">
                {/* Left Column: Active Focus (Pending Tasks) */}
                <section className="progress-section focus-board">
                    <h3><Circle size={18} className="text-warning" /> Active Focus (TODOs)</h3>
                    <div className="focus-scroll-area">
                        {Object.entries(pendingByProject).map(([project, projectTasks]) => (
                            <div key={project} className="project-group">
                                <h4 className="project-group-title">{project}</h4>
                                <ul className="task-list">
                                    {projectTasks.map((t, idx) => (
                                        <li key={idx} className="task-item pending">
                                            <div className="task-bullet"></div>
                                            <div className="task-content">
                                                <ReactMarkdown remarkPlugins={[remarkGfm]}>{t.task}</ReactMarkdown>
                                            </div>
                                        </li>
                                    ))}
                                </ul>
                            </div>
                        ))}
                        {tasks.pending.length === 0 && (
                            <div className="empty-state">No pending tasks found. You're all caught up!</div>
                        )}
                    </div>
                </section>

                {/* Center Column: Momentum Stats */}
                <section className="progress-section momentum-board">
                    <h3><TrendingUp size={18} className="text-primary" /> Overall Momentum</h3>

                    <div className="stats-card">
                        <div className="stat-circle-container">
                            <div className="stat-circle" style={{
                                background: `conic-gradient(var(--text-primary) ${(stats.completion_rate * 100).toFixed(0)}%, var(--border-color) 0)`
                            }}>
                                <div className="stat-circle-inner">
                                    <span className="rate-value">{(stats.completion_rate * 100).toFixed(0)}%</span>
                                    <span className="rate-label">Completed</span>
                                </div>
                            </div>
                        </div>

                        <div className="stat-details">
                            <div className="stat-row">
                                <span className="stat-label">Total Tracked Tasks:</span>
                                <span className="stat-num">{stats.total_tasks}</span>
                            </div>
                            <div className="stat-row">
                                <span className="stat-label">Completed Tasks:</span>
                                <span className="stat-num text-success">{stats.completed_tasks}</span>
                            </div>
                            <div className="stat-row">
                                <span className="stat-label">Pending Tasks:</span>
                                <span className="stat-num text-warning">{tasks.pending.length}</span>
                            </div>
                        </div>
                    </div>

                    <div className="recent-completed">
                        <h4>Recently Completed Milestone</h4>
                        {tasks.completed.length > 0 ? (
                            <div className="completed-highlight">
                                <CheckCircle2 size={16} className="text-success" />
                                <div className="task-content">
                                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{tasks.completed[tasks.completed.length - 1].task}</ReactMarkdown>
                                </div>
                            </div>
                        ) : (
                            <span className="text-muted">No completed tasks yet.</span>
                        )}
                    </div>

                </section>

                {/* Right Column: Activity Feed (Git) */}
                <section className="progress-section activity-board">
                    <h3><GitCommit size={18} className="text-accent" /> Recent Activity (14 Days)</h3>
                    <div className="activity-scroll-area">
                        {commits.length > 0 ? (
                            <div className="timeline">
                                {commits.map((commit) => (
                                    <div key={commit.hash} className="timeline-item">
                                        <div className="timeline-marker"></div>
                                        <div className="timeline-content">
                                            <div className="timeline-header">
                                                <span className="commit-date">{commit.date}</span>
                                                <span className="commit-hash">{commit.hash}</span>
                                            </div>
                                            <div className="commit-msg">{commit.message}</div>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        ) : (
                            <div className="empty-state">No recent commits found in the last 14 days.</div>
                        )}
                    </div>
                </section>

            </div>
        </div>
    );
};

export default ProjectProgress;
