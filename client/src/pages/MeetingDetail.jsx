import { useState, useEffect, useRef } from 'react';
import { useParams, Link, useSearchParams } from 'react-router-dom';
import axios from 'axios';

export default function MeetingDetail() {
    const { id } = useParams();
    const [searchParams] = useSearchParams();
    const fromStorage = searchParams.get('from') === 'storage';
    const [meeting, setMeeting] = useState(null);
    const [loading, setLoading] = useState(true);
    const [activeTab, setActiveTab] = useState('summary');
    const [reprocessing, setReprocessing] = useState(false);
    const audioRef = useRef(null);
    const [audioUrl, setAudioUrl] = useState(null);

    useEffect(() => {
        fetchMeeting();

        // WebSocket for real-time updates (replaces polling)
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws`;
        let ws = new WebSocket(wsUrl);
        let reconnectTimer = null;

        const connectWs = () => {
            ws = new WebSocket(wsUrl);

            ws.onmessage = (evt) => {
                try {
                    const msg = JSON.parse(evt.data);
                    if (msg.event === 'meeting_updated' && msg.meeting_id === id) {
                        fetchMeeting();
                        if (msg.status !== 'processing') {
                            setReprocessing(false);
                        }
                    }
                } catch (e) { /* ignore */ }
            };

            ws.onclose = () => {
                reconnectTimer = setTimeout(connectWs, 3000);
            };
            ws.onerror = () => ws.close();
        };

        connectWs();

        // Keep-alive ping every 30s
        const pingInterval = setInterval(() => {
            if (ws && ws.readyState === WebSocket.OPEN) ws.send('ping');
        }, 30000);

        return () => {
            clearInterval(pingInterval);
            clearTimeout(reconnectTimer);
            if (ws) ws.close();
        };
    }, [id]);

    // Fetch audio/media as blob via axios (sends auth token)
    useEffect(() => {
        if (!id) return;
        let blobUrl = null;

        axios.get(`/api/meetings/${id}/audio`, { responseType: 'blob' })
            .then(res => {
                blobUrl = URL.createObjectURL(res.data);
                setAudioUrl(blobUrl);
            })
            .catch(err => console.error('Failed to load media', err));

        return () => {
            if (blobUrl) URL.revokeObjectURL(blobUrl);
            setAudioUrl(null);
        };
    }, [id]);

    const fetchMeeting = async () => {
        try {
            const res = await axios.get(`/api/meetings/${id}`);
            setMeeting(res.data);
            setLoading(false);
        } catch (error) {
            console.error("Failed to fetch meeting", error);
            setLoading(false);
        }
    };

    const isImage = (filename) => /\.(jpg|jpeg|png|gif)$/i.test(filename || '');

    const formatTime = (seconds) => {
        if (!seconds && seconds !== 0) return '00:00';
        const mins = Math.floor(seconds / 60);
        const secs = Math.floor(seconds % 60);
        return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
    };

    const jumpToTime = (time) => {
        if (audioRef.current) {
            audioRef.current.currentTime = time;
            audioRef.current.play();
        }
    };

    const handleExport = () => {
        if (!meeting) return;
        let text = meeting.transcription_text || '';
        const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${meeting.filename || 'transcript'}.txt`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
    };

    const handleReprocess = async (maxSpeakers = 4, locales = 'en-US,hi-IN') => {
        if (!meeting) return;
        setReprocessing(true);
        try {
            await axios.post(`/api/meetings/${id}/reprocess?max_speakers=${maxSpeakers}&locales=${encodeURIComponent(locales)}`);
            // WebSocket will notify when processing is done — no polling needed
        } catch (err) {
            console.error('Reprocess failed:', err);
            setReprocessing(false);
        }
    };

    if (loading) return (
        <div className="min-h-screen flex items-center justify-center" style={{ backgroundColor: '#f0f4f8' }}>
            <div className="flex flex-col items-center gap-4">
                <div className="animate-spin w-8 h-8 border-2 border-indigo-500 border-t-transparent rounded-full"></div>
                <p className="text-slate-500">Loading file...</p>
            </div>
        </div>
    );

    if (!meeting) return (
        <div className="min-h-screen p-10 text-slate-700" style={{ backgroundColor: '#f0f4f8' }}>File not found</div>
    );

    const isImg = isImage(meeting.filename);

    // Parse transcription_json
    let transcriptWords = [];
    try {
        if (meeting.transcription_json) {
            const parsed = typeof meeting.transcription_json === 'string'
                ? JSON.parse(meeting.transcription_json)
                : meeting.transcription_json;
            if (Array.isArray(parsed)) transcriptWords = parsed;
        }
    } catch (e) {
        console.warn("Failed to parse transcription_json", e);
    }

    // Parse summary (may be JSON from GPT or plain text)
    let summaryText = '';
    let summaryHindi = '';
    let actionItems = [];
    let actionItemsHindi = [];
    let keyDecisions = [];
    let keyDecisionsHindi = [];
    let topicsDiscussed = [];
    let topicsDiscussedHindi = [];
    try {
        if (meeting.summary) {
            const parsed = JSON.parse(meeting.summary);
            summaryText = parsed.summary || meeting.summary;
            summaryHindi = parsed.summary_hindi || '';
            actionItems = parsed.action_items || [];
            actionItemsHindi = parsed.action_items_hindi || [];
            keyDecisions = parsed.key_decisions || [];
            keyDecisionsHindi = parsed.key_decisions_hindi || [];
            topicsDiscussed = parsed.topics_discussed || [];
            topicsDiscussedHindi = parsed.topics_discussed_hindi || [];
        }
    } catch {
        summaryText = meeting.summary || '';
    }

    // Parse action_items (enriched JSON with Language AI insights)
    let keyPhrases = [];
    let sentiment = '';
    let sentimentScores = {};
    let entities = [];
    try {
        if (meeting.action_items) {
            const parsed = JSON.parse(meeting.action_items);
            if (parsed.key_phrases) keyPhrases = parsed.key_phrases;
            if (parsed.sentiment) sentiment = parsed.sentiment;
            if (parsed.sentiment_scores) sentimentScores = parsed.sentiment_scores;
            if (parsed.entities) entities = parsed.entities;
            // If action_items were inside the enriched JSON, use them
            if (parsed.action_items && Array.isArray(parsed.action_items) && actionItems.length === 0) {
                actionItems = parsed.action_items;
            }
        }
    } catch {
        // action_items is plain text, not JSON
    }

    const sentimentColors = {
        positive: 'bg-green-100 text-green-700 border-green-200',
        neutral: 'bg-gray-100 text-gray-700 border-gray-200',
        negative: 'bg-red-100 text-red-700 border-red-200',
        mixed: 'bg-yellow-100 text-yellow-700 border-yellow-200',
    };
    const sentimentEmoji = { positive: '😊', neutral: '😐', negative: '😟', mixed: '🤔' };

    const hasInsights = keyPhrases.length > 0 || sentiment || entities.length > 0;

    return (
        <div className="min-h-screen p-6 md:p-12 font-sans" style={{ backgroundColor: '#f0f4f8' }}>
            <div className="max-w-6xl mx-auto">

                {/* Header */}
                <div className="mb-8">
                    <Link to={fromStorage ? '/?view=storage' : '/'} className="inline-flex items-center text-slate-500 hover:text-indigo-600 mb-4 transition-colors">
                        ← Back to {fromStorage ? 'Storage' : 'Dashboard'}
                    </Link>
                    <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
                        <div>
                            <h1 className="text-3xl font-extrabold text-slate-700">{meeting.filename}</h1>
                            <div className="flex items-center gap-4 mt-2 text-sm text-slate-500">
                                <span>🕐 {new Date(meeting.upload_timestamp + (meeting.upload_timestamp?.endsWith('Z') ? '' : 'Z')).toLocaleString()}</span>
                                <span className={`px-3 py-1 rounded-full font-bold text-xs ${meeting.status === 'completed'
                                    ? 'bg-green-100 text-green-700'
                                    : meeting.status === 'processing'
                                        ? 'bg-blue-100 text-blue-700'
                                        : 'bg-red-100 text-red-700'
                                    }`}>
                                    {meeting.status === 'completed' ? '✅' : meeting.status === 'processing' ? '⏳' : '❌'} {meeting.status}
                                </span>
                            </div>
                        </div>

                        {!isImg && (
                            <div className="flex gap-2 flex-wrap">
                                {/* Stuck processing or failed — prominent reprocess button */}
                                {(meeting.status === 'processing' || meeting.status === 'failed') && (
                                    <button onClick={() => handleReprocess(4, 'en-US')} disabled={reprocessing}
                                        className="clay-btn-primary px-5 py-2 rounded-xl font-bold text-sm shadow-lg disabled:opacity-50 flex items-center gap-2"
                                        title="Re-run transcription + AI pipeline (English)">
                                        {reprocessing ? (
                                            <><div className="animate-spin w-4 h-4 border-2 border-white border-t-transparent rounded-full"></div> Reprocessing...</>
                                        ) : (
                                            <><span>🔄</span> Reprocess Now</>
                                        )}
                                    </button>
                                )}
                                {meeting.status === 'completed' && (
                                    <>
                                        <button onClick={() => handleReprocess(2, 'en-US')} disabled={reprocessing}
                                            className="clay-btn px-4 py-2 rounded-xl font-bold text-xs text-slate-600 hover:text-indigo-600 disabled:opacity-50"
                                            title="English only — Best for podcasts / 1-on-1">
                                            {reprocessing ? '⏳ Reprocessing...' : '🔄 2 Speakers'}
                                        </button>
                                        <button onClick={() => handleReprocess(4, 'en-US')} disabled={reprocessing}
                                            className="clay-btn px-4 py-2 rounded-xl font-bold text-xs text-slate-600 hover:text-indigo-600 disabled:opacity-50"
                                            title="English only — Best for group meetings">
                                            {reprocessing ? '⏳ Reprocessing...' : '🔄 4 Speakers'}
                                        </button>
                                        <button onClick={() => handleReprocess(4, 'en-US,hi-IN')} disabled={reprocessing}
                                            className="clay-btn px-4 py-2 rounded-xl font-bold text-xs text-orange-600 hover:text-orange-700 disabled:opacity-50 border border-orange-200"
                                            title="English + Hindi bilingual transcription">
                                            {reprocessing ? '⏳ Reprocessing...' : '🇮🇳 Bilingual'}
                                        </button>
                                        <button onClick={handleExport} className="clay-btn-primary px-6 py-2 rounded-xl font-bold text-sm shadow-lg">
                                            📥 Export Transcript
                                        </button>
                                    </>
                                )}
                            </div>
                        )}
                    </div>
                </div>

                {/* Content Layout */}
                <div className="grid grid-cols-1 md:grid-cols-3 gap-6">

                    {/* Left Column: Tabs */}
                    <div className="md:col-span-1">
                        {/* Audio Player / Image Preview */}
                        {isImg ? (
                            <div className="clay-card p-2 overflow-hidden mb-6">
                                {audioUrl ? (
                                    <img src={audioUrl} alt={meeting.filename} className="w-full h-auto rounded-xl" />
                                ) : (
                                    <div className="flex items-center justify-center py-12">
                                        <div className="animate-spin w-5 h-5 border-2 border-indigo-400 border-t-transparent rounded-full mr-2"></div>
                                        <span className="text-sm text-slate-400">Loading image...</span>
                                    </div>
                                )}
                            </div>
                        ) : (
                            <div className="clay-card p-4 mb-6">
                                <h4 className="text-xs font-bold text-slate-400 uppercase mb-3 tracking-wider">🎵 Audio Player</h4>
                                {audioUrl ? (
                                    <audio ref={audioRef} controls preload="auto" className="w-full" src={audioUrl} />
                                ) : (
                                    <div className="flex items-center justify-center py-4">
                                        <div className="animate-spin w-5 h-5 border-2 border-indigo-400 border-t-transparent rounded-full mr-2"></div>
                                        <span className="text-sm text-slate-400">Loading audio...</span>
                                    </div>
                                )}
                            </div>
                        )}

                        {/* Tab Buttons */}
                        {!isImg && (
                            <div className="flex flex-col gap-3">
                                <button
                                    onClick={() => setActiveTab('summary')}
                                    className={`clay-btn p-4 flex items-center gap-3 w-full text-left ${activeTab === 'summary' ? 'active text-indigo-600' : 'text-slate-500'}`}
                                >
                                    ✨ <span>Summary</span>
                                </button>
                                <button
                                    onClick={() => setActiveTab('transcript')}
                                    className={`clay-btn p-4 flex items-center gap-3 w-full text-left ${activeTab === 'transcript' ? 'active text-indigo-600' : 'text-slate-500'}`}
                                >
                                    📝 <span>Transcript</span>
                                </button>
                                {hasInsights && (
                                    <button
                                        onClick={() => setActiveTab('insights')}
                                        className={`clay-btn p-4 flex items-center gap-3 w-full text-left ${activeTab === 'insights' ? 'active text-indigo-600' : 'text-slate-500'}`}
                                    >
                                        🧠 <span>AI Insights</span>
                                    </button>
                                )}
                                {meeting.images && meeting.images.length > 0 && (
                                    <button
                                        onClick={() => setActiveTab('images')}
                                        className={`clay-btn p-4 flex items-center gap-3 w-full text-left ${activeTab === 'images' ? 'active text-indigo-600' : 'text-slate-500'}`}
                                    >
                                        🖼️ <span>Images ({meeting.images.length})</span>
                                    </button>
                                )}
                            </div>
                        )}
                    </div>

                    {/* Right Column: Content */}
                    <div className="md:col-span-2">
                        {isImg ? (
                            <div className="clay-card p-6">
                                <h3 className="font-bold text-slate-700 mb-4">📷 Image Details</h3>
                                <p className="text-sm text-slate-500">Type: {meeting.device_type || 'camera'}</p>
                                <p className="text-sm text-slate-500 mt-1">Size: {((meeting.file_size || 0) / 1024).toFixed(1)} KB</p>
                            </div>
                        ) : (
                            <div className="clay-card p-6 min-h-[500px] overflow-hidden">

                                {/* Summary Tab */}
                                {activeTab === 'summary' && (
                                    <div>
                                        <h2 className="text-2xl font-bold mb-6 text-slate-700">
                                            ✨ Executive Summary
                                        </h2>

                                        {meeting.status === 'processing' ? (
                                            <div className="text-center py-20">
                                                <div className="animate-spin w-8 h-8 border-2 border-indigo-500 border-t-transparent rounded-full mx-auto mb-4"></div>
                                                <p className="text-slate-500">AI is processing your meeting...</p>
                                            </div>
                                        ) : summaryText ? (
                                            <div className="space-y-6">
                                                {/* Sentiment Badge */}
                                                {sentiment && (
                                                    <div className={`inline-flex items-center gap-2 px-4 py-2 rounded-full border text-sm font-semibold ${sentimentColors[sentiment] || sentimentColors.neutral}`}>
                                                        <span>{sentimentEmoji[sentiment] || '😐'}</span>
                                                        <span className="capitalize">{sentiment}</span>
                                                        {sentimentScores.positive !== undefined && (
                                                            <span className="text-xs opacity-70 ml-1">
                                                                ({Math.round((sentimentScores.positive || 0) * 100)}% pos)
                                                            </span>
                                                        )}
                                                    </div>
                                                )}

                                                {/* Summary - English */}
                                                <div className="clay-card p-4 bg-white">
                                                    <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-2">🇬🇧 English</h3>
                                                    <p className="text-slate-700 leading-relaxed whitespace-pre-wrap">{summaryText}</p>
                                                </div>

                                                {/* Summary - Hindi */}
                                                {summaryHindi && (
                                                    <div className="clay-card p-4 bg-orange-50/50 border border-orange-100">
                                                        <h3 className="text-xs font-bold text-orange-400 uppercase tracking-wider mb-2">🇮🇳 हिन्दी</h3>
                                                        <p className="text-slate-700 leading-relaxed whitespace-pre-wrap">{summaryHindi}</p>
                                                    </div>
                                                )}

                                                {/* Action Items */}
                                                {actionItems.length > 0 && (
                                                    <div className="clay-card p-4 bg-white">
                                                        <h3 className="text-sm font-bold text-slate-500 uppercase tracking-wider mb-3">📋 Action Items</h3>
                                                        <ul className="space-y-2">
                                                            {actionItems.map((item, i) => (
                                                                <li key={i} className="flex items-start gap-2 text-sm text-slate-600">
                                                                    <span className="text-indigo-500 mt-0.5">●</span>
                                                                    <span>{typeof item === 'string' ? item : item.task || item.description || JSON.stringify(item)}</span>
                                                                </li>
                                                            ))}
                                                        </ul>
                                                    </div>
                                                )}

                                                {/* Action Items - Hindi */}
                                                {actionItemsHindi.length > 0 && (
                                                    <div className="clay-card p-4 bg-orange-50/50 border border-orange-100">
                                                        <h3 className="text-sm font-bold text-orange-400 uppercase tracking-wider mb-3">📋 कार्य सूची (हिन्दी)</h3>
                                                        <ul className="space-y-2">
                                                            {actionItemsHindi.map((item, i) => (
                                                                <li key={i} className="flex items-start gap-2 text-sm text-slate-600">
                                                                    <span className="text-orange-500 mt-0.5">●</span>
                                                                    <span>{typeof item === 'string' ? item : item.task || item.description || JSON.stringify(item)}</span>
                                                                </li>
                                                            ))}
                                                        </ul>
                                                    </div>
                                                )}

                                                {/* Key Decisions */}
                                                {keyDecisions.length > 0 && (
                                                    <div className="clay-card p-4 bg-white">
                                                        <h3 className="text-sm font-bold text-slate-500 uppercase tracking-wider mb-3">⚖️ Key Decisions</h3>
                                                        <ul className="space-y-2">
                                                            {keyDecisions.map((item, i) => (
                                                                <li key={i} className="flex items-start gap-2 text-sm text-slate-600">
                                                                    <span className="text-green-500 mt-0.5">✓</span>
                                                                    <span>{typeof item === 'string' ? item : JSON.stringify(item)}</span>
                                                                </li>
                                                            ))}
                                                        </ul>
                                                    </div>
                                                )}

                                                {/* Key Decisions - Hindi */}
                                                {keyDecisionsHindi.length > 0 && (
                                                    <div className="clay-card p-4 bg-orange-50/50 border border-orange-100">
                                                        <h3 className="text-sm font-bold text-orange-400 uppercase tracking-wider mb-3">⚖️ मुख्य निर्णय (हिन्दी)</h3>
                                                        <ul className="space-y-2">
                                                            {keyDecisionsHindi.map((item, i) => (
                                                                <li key={i} className="flex items-start gap-2 text-sm text-slate-600">
                                                                    <span className="text-orange-500 mt-0.5">✓</span>
                                                                    <span>{typeof item === 'string' ? item : JSON.stringify(item)}</span>
                                                                </li>
                                                            ))}
                                                        </ul>
                                                    </div>
                                                )}

                                                {/* Topics Discussed */}
                                                {topicsDiscussed.length > 0 && (
                                                    <div className="clay-card p-4 bg-white">
                                                        <h3 className="text-sm font-bold text-slate-500 uppercase tracking-wider mb-3">💬 Topics Discussed</h3>
                                                        <div className="flex flex-wrap gap-2">
                                                            {topicsDiscussed.map((topic, i) => (
                                                                <span key={i} className="px-3 py-1 bg-indigo-50 text-indigo-600 rounded-full text-xs font-medium border border-indigo-100">
                                                                    {typeof topic === 'string' ? topic : JSON.stringify(topic)}
                                                                </span>
                                                            ))}
                                                        </div>
                                                    </div>
                                                )}

                                                {/* Topics Discussed - Hindi */}
                                                {topicsDiscussedHindi.length > 0 && (
                                                    <div className="clay-card p-4 bg-orange-50/50 border border-orange-100">
                                                        <h3 className="text-sm font-bold text-orange-400 uppercase tracking-wider mb-3">💬 चर्चा विषय (हिन्दी)</h3>
                                                        <div className="flex flex-wrap gap-2">
                                                            {topicsDiscussedHindi.map((topic, i) => (
                                                                <span key={i} className="px-3 py-1 bg-orange-50 text-orange-600 rounded-full text-xs font-medium border border-orange-200">
                                                                    {typeof topic === 'string' ? topic : JSON.stringify(topic)}
                                                                </span>
                                                            ))}
                                                        </div>
                                                    </div>
                                                )}
                                            </div>
                                        ) : (
                                            <div className="text-center py-20 text-slate-400">
                                                <span className="text-4xl">🤖</span>
                                                <p className="mt-4">No summary available yet.</p>
                                            </div>
                                        )}
                                    </div>
                                )}

                                {/* Transcript Tab */}
                                {activeTab === 'transcript' && (
                                    <div>
                                        <h2 className="text-2xl font-bold mb-6 text-slate-700">
                                            📝 Full Transcript
                                        </h2>

                                        <div className="max-h-[600px] overflow-y-auto scroll-hide space-y-4 pr-2">
                                            {transcriptWords.length > 0 ? (
                                                transcriptWords.map((w, i) => {
                                                    const colors = ['bg-purple-100 text-purple-600', 'bg-blue-100 text-blue-600', 'bg-green-100 text-green-600', 'bg-orange-100 text-orange-600'];
                                                    const speakerIndex = w.speaker ? w.speaker.charCodeAt(w.speaker.length - 1) % colors.length : 0;
                                                    const isHost = w.speaker === 'Guest-1';

                                                    return (
                                                        <div key={i} className="flex items-start gap-3">
                                                            <div className={`w-8 h-8 rounded-full ${colors[speakerIndex]} flex items-center justify-center text-xs font-bold flex-shrink-0`}>
                                                                {w.speaker ? w.speaker.substring(0, 2).toUpperCase() : 'S1'}
                                                            </div>
                                                            <div className={`${isHost ? 'bubble-right' : 'bubble-left'} p-3 text-sm text-slate-600`}>
                                                                <span
                                                                    className="text-xs text-indigo-500 font-mono mr-2 cursor-pointer hover:underline"
                                                                    onClick={() => jumpToTime(w.start)}
                                                                >
                                                                    [{formatTime(w.start)}]
                                                                </span>
                                                                <span className="font-semibold text-slate-700 mr-1">{w.speaker || 'Speaker'}:</span>
                                                                {w.word}
                                                            </div>
                                                        </div>
                                                    );
                                                })
                                            ) : meeting.transcription_text ? (
                                                <div className="bubble-left p-4 text-sm text-slate-600 leading-relaxed whitespace-pre-wrap">
                                                    {meeting.transcription_text}
                                                </div>
                                            ) : (
                                                <div className="text-center py-20 text-slate-400">
                                                    <span className="text-4xl">📝</span>
                                                    <p className="mt-4">No transcript available.</p>
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                )}

                                {/* AI Insights Tab */}
                                {activeTab === 'insights' && (
                                    <div>
                                        <h2 className="text-2xl font-bold mb-6 text-slate-700">
                                            🧠 AI Insights
                                        </h2>

                                        <div className="space-y-6">
                                            {/* Sentiment Analysis */}
                                            {sentiment && (
                                                <div className="clay-card p-5 bg-white">
                                                    <h3 className="text-sm font-bold text-slate-500 uppercase tracking-wider mb-4">Sentiment Analysis</h3>
                                                    <div className="flex items-center gap-4 mb-4">
                                                        <span className="text-4xl">{sentimentEmoji[sentiment] || '😐'}</span>
                                                        <div>
                                                            <span className={`inline-block px-4 py-1.5 rounded-full text-sm font-bold capitalize ${sentimentColors[sentiment] || sentimentColors.neutral}`}>
                                                                {sentiment}
                                                            </span>
                                                        </div>
                                                    </div>
                                                    {sentimentScores.positive !== undefined && (
                                                        <div className="space-y-2 mt-3">
                                                            {[
                                                                { label: 'Positive', value: sentimentScores.positive, color: 'bg-green-400' },
                                                                { label: 'Neutral', value: sentimentScores.neutral, color: 'bg-gray-400' },
                                                                { label: 'Negative', value: sentimentScores.negative, color: 'bg-red-400' },
                                                            ].map(({ label, value, color }) => (
                                                                <div key={label} className="flex items-center gap-3 text-sm">
                                                                    <span className="w-16 text-slate-500">{label}</span>
                                                                    <div className="flex-1 bg-slate-100 rounded-full h-3 overflow-hidden">
                                                                        <div className={`${color} h-full rounded-full transition-all`} style={{ width: `${Math.round((value || 0) * 100)}%` }} />
                                                                    </div>
                                                                    <span className="w-12 text-right text-slate-600 font-mono">{Math.round((value || 0) * 100)}%</span>
                                                                </div>
                                                            ))}
                                                        </div>
                                                    )}
                                                </div>
                                            )}

                                            {/* Key Phrases */}
                                            {keyPhrases.length > 0 && (
                                                <div className="clay-card p-5 bg-white">
                                                    <h3 className="text-sm font-bold text-slate-500 uppercase tracking-wider mb-4">🔑 Key Phrases ({keyPhrases.length})</h3>
                                                    <div className="flex flex-wrap gap-2">
                                                        {keyPhrases.map((phrase, i) => (
                                                            <span key={i} className="px-3 py-1.5 bg-gradient-to-r from-indigo-50 to-purple-50 text-indigo-700 rounded-full text-xs font-medium border border-indigo-100 shadow-sm">
                                                                {phrase}
                                                            </span>
                                                        ))}
                                                    </div>
                                                </div>
                                            )}

                                            {/* Named Entities */}
                                            {entities.length > 0 && (
                                                <div className="clay-card p-5 bg-white">
                                                    <h3 className="text-sm font-bold text-slate-500 uppercase tracking-wider mb-4">🏷️ Named Entities ({entities.length})</h3>
                                                    <div className="overflow-x-auto">
                                                        <table className="w-full text-sm">
                                                            <thead>
                                                                <tr className="text-left text-slate-400 border-b border-slate-100">
                                                                    <th className="pb-2 font-medium">Entity</th>
                                                                    <th className="pb-2 font-medium">Category</th>
                                                                    <th className="pb-2 font-medium text-right">Confidence</th>
                                                                </tr>
                                                            </thead>
                                                            <tbody className="divide-y divide-slate-50">
                                                                {entities.map((ent, i) => (
                                                                    <tr key={i} className="hover:bg-slate-50 transition-colors">
                                                                        <td className="py-2 text-slate-700 font-medium">{ent.text}</td>
                                                                        <td className="py-2">
                                                                            <span className="px-2 py-0.5 bg-slate-100 text-slate-600 rounded text-xs">
                                                                                {ent.category}
                                                                            </span>
                                                                        </td>
                                                                        <td className="py-2 text-right font-mono text-slate-500">
                                                                            {Math.round((ent.confidence_score || ent.confidence || 0) * 100)}%
                                                                        </td>
                                                                    </tr>
                                                                ))}
                                                            </tbody>
                                                        </table>
                                                    </div>
                                                </div>
                                            )}

                                            {/* No insights fallback */}
                                            {!sentiment && keyPhrases.length === 0 && entities.length === 0 && (
                                                <div className="text-center py-20 text-slate-400">
                                                    <span className="text-4xl">🔍</span>
                                                    <p className="mt-4">No AI insights available yet.</p>
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                )}

                                {/* Images Tab */}
                                {activeTab === 'images' && (
                                    <div>
                                        <h2 className="text-2xl font-bold mb-6 text-slate-700">
                                            🖼️ Session Images
                                        </h2>

                                        {!meeting.images || meeting.images.length === 0 ? (
                                            <div className="text-center py-20 text-slate-400">
                                                <span className="text-4xl">📷</span>
                                                <p className="mt-4">No images captured during this session.</p>
                                            </div>
                                        ) : (
                                            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                                                {meeting.images.map((img) => (
                                                    <div key={img.id} className="clay-card p-2 overflow-hidden group">
                                                        <div className="aspect-video relative overflow-hidden rounded-xl">
                                                            {img.url ? (
                                                                <img
                                                                    src={img.url}
                                                                    alt={img.device_type}
                                                                    className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500"
                                                                    loading="lazy"
                                                                />
                                                            ) : (
                                                                <div className="w-full h-full flex items-center justify-center bg-slate-100 rounded-xl min-h-[120px]">
                                                                    <span className="text-slate-400 text-sm">Image unavailable</span>
                                                                </div>
                                                            )}
                                                            <div className="absolute top-2 left-2 bg-black/60 backdrop-blur-sm px-2 py-1 rounded-md text-xs font-mono text-white flex items-center gap-1 border border-white/10">
                                                                {img.device_type === 'cam1' ? '📸 Cam 1' : img.device_type === 'cam2' ? '📸 Cam 2' : '📷 Unknown'}
                                                            </div>
                                                        </div>
                                                        <div className="p-3">
                                                            <span className="text-xs text-slate-500">{new Date(img.upload_timestamp + (img.upload_timestamp?.endsWith('Z') ? '' : 'Z')).toLocaleString()}</span>
                                                        </div>
                                                    </div>
                                                ))}
                                            </div>
                                        )}
                                    </div>
                                )}
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
}
