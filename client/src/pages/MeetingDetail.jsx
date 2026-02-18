import { useState, useEffect, useRef } from 'react';
import { useParams, Link } from 'react-router-dom';
import axios from 'axios';

export default function MeetingDetail() {
    const { id } = useParams();
    const [meeting, setMeeting] = useState(null);
    const [loading, setLoading] = useState(true);
    const [activeTab, setActiveTab] = useState('summary');
    const audioRef = useRef(null);

    useEffect(() => {
        fetchMeeting();
        const interval = setInterval(() => {
            if (meeting && meeting.status === 'processing') {
                fetchMeeting();
            }
        }, 5000);
        return () => clearInterval(interval);
    }, [id, meeting?.status]);

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

    return (
        <div className="min-h-screen p-6 md:p-12 font-sans" style={{ backgroundColor: '#f0f4f8' }}>
            <div className="max-w-6xl mx-auto">

                {/* Header */}
                <div className="mb-8">
                    <Link to="/" className="inline-flex items-center text-slate-500 hover:text-indigo-600 mb-4 transition-colors">
                        ← Back to Dashboard
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

                        {!isImg && meeting.status === 'completed' && (
                            <button onClick={handleExport} className="clay-btn-primary px-6 py-2 rounded-xl font-bold text-sm shadow-lg">
                                📥 Export Transcript
                            </button>
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
                                <img src={`/api/meetings/${id}/audio`} alt={meeting.filename} className="w-full h-auto rounded-xl" />
                            </div>
                        ) : (
                            <div className="clay-card p-4 mb-6">
                                <h4 className="text-xs font-bold text-slate-400 uppercase mb-3 tracking-wider">🎵 Audio Player</h4>
                                <audio ref={audioRef} controls preload="metadata" src={`/api/meetings/${id}/audio`} className="w-full" />
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
                                        ) : meeting.summary ? (
                                            <div className="space-y-6">
                                                <div className="clay-card p-4 bg-white">
                                                    <p className="text-slate-700 leading-relaxed whitespace-pre-wrap">{meeting.summary}</p>
                                                </div>
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
                                                            <img
                                                                src={`/api/images/${img.filename}`}
                                                                alt={img.device_type}
                                                                className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500"
                                                            />
                                                            <div className="absolute top-2 left-2 bg-black/60 backdrop-blur-sm px-2 py-1 rounded-md text-xs font-mono text-white flex items-center gap-1 border border-white/10">
                                                                {img.device_type === 'cam1' ? '📸 Cam 1' : img.device_type === 'cam2' ? '📸 Cam 2' : '📷 Unknown'}
                                                            </div>
                                                        </div>
                                                        <div className="p-3">
                                                            <span className="text-xs text-slate-500">{new Date(img.upload_timestamp).toLocaleString()}</span>
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
