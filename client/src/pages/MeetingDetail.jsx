import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import axios from 'axios';
import { ArrowLeft, Download, CheckCircle, AlertTriangle, MessageSquare, ListTodo, Copy, Play, Image as ImageIcon, FileText } from 'lucide-react';

export default function MeetingDetail() {
    const { id } = useParams();
    const [meeting, setMeeting] = useState(null);
    const [loading, setLoading] = useState(true);
    const [activeTab, setActiveTab] = useState('summary'); // 'summary' or 'transcript'

    useEffect(() => {
        fetchMeeting();
        // Poll for updates if processing
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

    if (loading) return (
        <div className="min-h-screen bg-[#0f172a] flex items-center justify-center text-white">
            <div className="flex flex-col items-center gap-4">
                <div className="animate-spin w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full"></div>
                <p className="text-slate-400">Loading file...</p>
            </div>
        </div>
    );

    if (!meeting) return <div className="min-h-screen bg-[#0f172a] text-white p-10">File not found</div>;

    const isImg = isImage(meeting.filename);

    return (
        <div className="min-h-screen bg-[#0f172a] text-white p-6 md:p-12 font-sans selection:bg-blue-500/30">
            <div className="max-w-6xl mx-auto">
                {/* Header */}
                <div className="mb-8">
                    <Link to="/" className="inline-flex items-center text-slate-400 hover:text-white mb-4 transition-colors group">
                        <ArrowLeft className="w-4 h-4 mr-2 group-hover:-translate-x-1 transition-transform" /> Back to Drive
                    </Link>
                    <div className="flex justify-between items-start">
                        <div className="flex items-center gap-4">
                            <div className="p-3 bg-slate-800 rounded-xl border border-slate-700">
                                {isImg ? <ImageIcon className="w-8 h-8 text-pink-400" /> : <FileText className="w-8 h-8 text-blue-400" />}
                            </div>
                            <div>
                                <h1 className="text-3xl font-bold text-white">{meeting.filename}</h1>
                                <p className="text-slate-400 mt-1 flex items-center gap-2 text-sm">
                                    {new Date(meeting.upload_timestamp).toLocaleString()}
                                    <span className="text-slate-600">•</span>
                                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium uppercase tracking-wider ${meeting.status === 'completed' ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' :
                                        meeting.status === 'failed' ? 'bg-rose-500/10 text-rose-400 border border-rose-500/20' :
                                            'bg-blue-500/10 text-blue-400 border border-blue-500/20 animate-pulse'
                                        }`}>
                                        {meeting.status}
                                    </span>
                                </p>
                            </div>
                        </div>

                        <a
                            href={`/api/meetings/${id}/audio`}
                            download={meeting.filename}
                            className="bg-slate-800 hover:bg-slate-700 text-white px-4 py-2 rounded-lg border border-slate-700 transition-colors flex items-center gap-2 text-sm font-medium"
                        >
                            <Download className="w-4 h-4" /> Download
                        </a>
                    </div>
                </div>

                {/* Content */}
                <div className="grid md:grid-cols-3 gap-8">

                    {/* Left Sidebar */}
                    <div className="md:col-span-1 space-y-6">
                        {/* File Preview / Player */}
                        <div className="bg-slate-800/50 rounded-2xl p-6 border border-slate-700/50 backdrop-blur-sm">
                            <h3 className="text-xs font-bold text-slate-500 mb-4 uppercase tracking-widest">
                                {isImg ? "Image Preview" : "Audio Playback"}
                            </h3>

                            {isImg ? (
                                <div className="rounded-xl overflow-hidden border border-slate-700 bg-black/50 aspect-video flex items-center justify-center">
                                    <img
                                        src={`/api/meetings/${id}/audio`}
                                        alt={meeting.filename}
                                        className="w-full h-full object-contain"
                                    />
                                </div>
                            ) : (
                                <div className="space-y-4">
                                    <div className="w-full h-24 bg-slate-900 rounded-xl flex items-center justify-center border border-slate-800 relative overflow-hidden group">
                                        <div className="absolute inset-0 bg-blue-500/5 group-hover:bg-blue-500/10 transition-colors"></div>
                                        <div className="flex items-center gap-1">
                                            {[...Array(5)].map((_, i) => (
                                                <div key={i} className="w-1 bg-blue-500/50 rounded-full animate-pulse" style={{ height: `${Math.random() * 100}%`, animationDelay: `${i * 0.1}s` }}></div>
                                            ))}
                                        </div>
                                    </div>
                                    <audio
                                        controls
                                        className="w-full"
                                        src={`/api/meetings/${id}/audio`}
                                    >
                                        Your browser does not support the audio element.
                                    </audio>
                                </div>
                            )}
                        </div>

                        {/* Navigation (Only for Audio) */}
                        {!isImg && (
                            <div className="bg-slate-800/50 rounded-2xl p-2 border border-slate-700/50">
                                <button
                                    onClick={() => setActiveTab('summary')}
                                    className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl transition-all font-medium ${activeTab === 'summary' ? 'bg-blue-600 text-white shadow-lg shadow-blue-900/20' : 'text-slate-400 hover:bg-slate-700/50 hover:text-white'}`}
                                >
                                    <ListTodo className="w-5 h-5" /> AI Summary
                                </button>
                                <button
                                    onClick={() => setActiveTab('transcript')}
                                    className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl transition-all font-medium ${activeTab === 'transcript' ? 'bg-blue-600 text-white shadow-lg shadow-blue-900/20' : 'text-slate-400 hover:bg-slate-700/50 hover:text-white'}`}
                                >
                                    <MessageSquare className="w-5 h-5" /> Full Transcript
                                </button>
                                <button
                                    onClick={() => setActiveTab('images')}
                                    className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl transition-all font-medium ${activeTab === 'images' ? 'bg-blue-600 text-white shadow-lg shadow-blue-900/20' : 'text-slate-400 hover:bg-slate-700/50 hover:text-white'}`}
                                >
                                    <ImageIcon className="w-5 h-5" /> Session Images ({meeting.images?.length || 0})
                                </button>
                            </div>
                        )}
                    </div>

                    {/* Main Content Area */}
                    <div className="md:col-span-2 space-y-6">

                        {/* If Image: Show Full Size */}
                        {isImg ? (
                            <div className="bg-slate-900/50 rounded-2xl border border-slate-800 p-2 overflow-hidden">
                                <img
                                    src={`/api/meetings/${id}/audio`}
                                    alt={meeting.filename}
                                    className="w-full h-auto rounded-xl"
                                />
                            </div>
                        ) : (
                            /* If Audio: Tabs */
                            <div className="bg-slate-800/40 rounded-2xl border border-slate-700/50 min-h-[500px] relative overflow-hidden backdrop-blur-sm">

                                {/* Summary Tab */}
                                {activeTab === 'summary' && (
                                    <div className="p-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
                                        <h2 className="text-2xl font-bold mb-6 flex items-center gap-3">
                                            <span className="bg-gradient-to-r from-purple-400 to-pink-400 bg-clip-text text-transparent">Executive Summary</span>
                                            <div className="h-px flex-1 bg-gradient-to-r from-slate-700 to-transparent"></div>
                                        </h2>

                                        {meeting.status === 'processing' ? (
                                            <div className="text-center py-20 text-slate-500">
                                                <div className="animate-spin w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full mx-auto mb-4"></div>
                                                AI is analyzing the audio...
                                            </div>
                                        ) : meeting.summary ? (
                                            <div className="space-y-8">
                                                <div className="prose prose-invert prose-lg max-w-none">
                                                    <p className="leading-relaxed text-slate-300">{meeting.summary}</p>
                                                </div>

                                                {meeting.action_items && (
                                                    <div className="bg-slate-900/50 rounded-2xl p-6 border border-slate-700/50">
                                                        <h3 className="text-sm font-bold text-slate-400 uppercase tracking-widest mb-4 flex items-center gap-2">
                                                            <ListTodo className="w-4 h-4 text-blue-400" /> Action Items
                                                        </h3>
                                                        <div className="space-y-3">
                                                            {meeting.action_items.split(/\n/).map((item, i) => (
                                                                item.trim() && (
                                                                    <div key={i} className="flex items-start gap-4 p-3 rounded-lg hover:bg-slate-800/50 transition-colors group">
                                                                        <div className="mt-1.5 w-2 h-2 rounded-full bg-blue-500 shadow-[0_0_10px_rgba(59,130,246,0.5)] flex-shrink-0" />
                                                                        <span className="text-slate-300 group-hover:text-white transition-colors">
                                                                            {item.replace(/^- /, '').replace(/^\* /, '')}
                                                                        </span>
                                                                    </div>
                                                                )
                                                            ))}
                                                        </div>
                                                    </div>
                                                )}
                                            </div>
                                        ) : (
                                            <div className="text-slate-500 italic text-center py-20">No summary available.</div>
                                        )}
                                    </div>
                                )}

                                {/* Transcript Tab */}
                                {activeTab === 'transcript' && (
                                    <div className="p-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
                                        <h2 className="text-2xl font-bold mb-6 text-white flex items-center gap-3">
                                            Transcription
                                            <div className="h-px flex-1 bg-slate-700"></div>
                                        </h2>
                                        {meeting.status === 'processing' ? (
                                            <div className="text-center py-20 text-slate-500">Processing audio...</div>
                                        ) : meeting.transcription_text ? (
                                            <div className="font-mono text-sm leading-8 text-slate-300 whitespace-pre-wrap bg-slate-900/50 p-6 rounded-xl border border-slate-800">
                                                {meeting.transcription_text}
                                            </div>
                                        ) : (
                                            <div className="text-slate-500 italic text-center py-20">No transcript available.</div>
                                        )}
                                    </div>
                                )}

                                {/* Images Tab */}
                                {activeTab === 'images' && (
                                    <div className="p-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
                                        <h2 className="text-2xl font-bold mb-6 text-white flex items-center gap-3">
                                            Session Images
                                            <div className="h-px flex-1 bg-slate-700"></div>
                                        </h2>

                                        {!meeting.images || meeting.images.length === 0 ? (
                                            <div className="text-center py-20 text-slate-500">
                                                <ImageIcon className="w-12 h-12 mx-auto mb-4 opacity-50" />
                                                No images captured during this session.
                                            </div>
                                        ) : (
                                            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                                                {meeting.images.map((img) => (
                                                    <div key={img.id} className="group relative bg-slate-900 rounded-xl overflow-hidden border border-slate-800 hover:border-blue-500/50 transition-colors">
                                                        <div className="aspect-video relative overflow-hidden">
                                                            <img
                                                                src={`/api/images/${img.filename}`}
                                                                alt={img.device_type}
                                                                className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500"
                                                            />
                                                            <div className="absolute top-2 left-2 bg-black/60 backdrop-blur-sm px-2 py-1 rounded-md text-xs font-mono text-white flex items-center gap-1 border border-white/10">
                                                                {img.device_type === 'cam1' ? '📸 Cam 1' : img.device_type === 'cam2' ? '📸 Cam 2' : '📷 Unknown'}
                                                            </div>
                                                        </div>
                                                        <div className="p-3 flex justify-between items-center bg-slate-900/50">
                                                            <span className="text-xs text-slate-400 font-mono">
                                                                {new Date(img.timestamp).toLocaleTimeString()}
                                                            </span>
                                                            <a
                                                                href={`/api/images/${img.filename}`}
                                                                target="_blank"
                                                                rel="noopener noreferrer"
                                                                className="text-blue-400 hover:text-blue-300 text-xs flex items-center gap-1"
                                                            >
                                                                View Full <ArrowLeft className="w-3 h-3 rotate-180" />
                                                            </a>
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
