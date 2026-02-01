import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import axios from 'axios';
import { ArrowLeft, Download, CheckCircle, AlertTriangle, MessageSquare, ListTodo, Copy, Play } from 'lucide-react';

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

    if (loading) return <div className="min-h-screen bg-slate-900 flex items-center justify-center text-white">Loading...</div>;
    if (!meeting) return <div className="min-h-screen bg-slate-900 text-white p-10">Meeting not found</div>;

    return (
        <div className="min-h-screen bg-slate-900 text-white p-6 md:p-12">
            <div className="max-w-5xl mx-auto">
                {/* Header */}
                <div className="mb-8">
                    <Link to="/" className="inline-flex items-center text-slate-400 hover:text-white mb-4 transition-colors">
                        <ArrowLeft className="w-4 h-4 mr-2" /> Back to Dashboard
                    </Link>
                    <div className="flex justify-between items-start">
                        <div>
                            <h1 className="text-3xl font-bold">{meeting.filename}</h1>
                            <p className="text-slate-400 mt-2 flex items-center gap-2">
                                {new Date(meeting.upload_timestamp).toLocaleString()}
                                <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${meeting.status === 'completed' ? 'bg-green-500/20 text-green-400' :
                                    meeting.status === 'failed' ? 'bg-red-500/20 text-red-400' : 'bg-blue-500/20 text-blue-400 animate-pulse'
                                    }`}>
                                    {meeting.status.toUpperCase()}
                                </span>
                            </p>
                        </div>
                    </div>
                </div>

                {/* Content */}
                <div className="grid md:grid-cols-3 gap-8">

                    {/* Sidebar / Tabs (Mobile) */}
                    <div className="md:col-span-1 space-y-4">
                        <div className="bg-slate-800 rounded-xl p-2 border border-slate-700">
                            <button
                                onClick={() => setActiveTab('summary')}
                                className={`w-full flex items-center gap-3 px-4 py-3 rounded-lg transition-all ${activeTab === 'summary' ? 'bg-blue-600 text-white shadow-lg' : 'text-slate-400 hover:bg-slate-700'}`}
                            >
                                <ListTodo className="w-5 h-5" /> AI Summary
                            </button>
                            <button
                                onClick={() => setActiveTab('transcript')}
                                className={`w-full flex items-center gap-3 px-4 py-3 rounded-lg transition-all ${activeTab === 'transcript' ? 'bg-blue-600 text-white shadow-lg' : 'text-slate-400 hover:bg-slate-700'}`}
                            >
                                <MessageSquare className="w-5 h-5" /> Full Transcript
                            </button>
                        </div>

                        {/* Audio Player */}
                        <div className="bg-slate-800 rounded-xl p-6 border border-slate-700">
                            <h3 className="text-sm font-semibold text-slate-400 mb-3 uppercase tracking-wider">Audio Source</h3>
                            <audio
                                controls
                                className="w-full"
                                src={`/api/meetings/${id}/audio`}
                            >
                                Your browser does not support the audio element.
                            </audio>
                            <p className="text-xs text-slate-500 mt-2 truncate">{meeting.filename}</p>
                        </div>
                    </div>

                    {/* Main Content Area */}
                    <div className="md:col-span-2">
                        <div className="bg-slate-800 rounded-xl border border-slate-700 min-h-[500px] shadow-xl overflow-hidden">

                            {/* Summary Tab */}
                            {activeTab === 'summary' && (
                                <div className="p-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
                                    <h2 className="text-xl font-bold mb-6 flex items-center gap-2">
                                        <span className="bg-gradient-to-r from-purple-400 to-pink-400 bg-clip-text text-transparent">AI Executive Summary</span>
                                    </h2>

                                    {meeting.status === 'processing' ? (
                                        <div className="text-center py-20 text-slate-500">
                                            <div className="animate-spin w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full mx-auto mb-4"></div>
                                            AI is analyzing the meeting...
                                        </div>
                                    ) : meeting.summary ? (
                                        <div className="space-y-8">
                                            <div className="prose prose-invert max-w-none">
                                                <p className="text-lg leading-relaxed text-slate-300">{meeting.summary}</p>
                                            </div>

                                            {meeting.action_items && (
                                                <div className="bg-slate-900/50 rounded-xl p-6 border border-slate-700/50">
                                                    <h3 className="text-sm font-bold text-slate-400 uppercase tracking-widest mb-4 flex items-center gap-2">
                                                        <ListTodo className="w-4 h-4" /> Action Items
                                                    </h3>
                                                    <div className="space-y-3">
                                                        {/* Simple split by newlines/bullets if it's a string */}
                                                        {meeting.action_items.split(/\n/).map((item, i) => (
                                                            item.trim() && (
                                                                <div key={i} className="flex items-start gap-3 text-slate-300">
                                                                    <div className="mt-1.5 w-1.5 h-1.5 rounded-full bg-blue-400 flex-shrink-0" />
                                                                    <span>{item.replace(/^- /, '').replace(/^\* /, '')}</span>
                                                                </div>
                                                            )
                                                        ))}
                                                    </div>
                                                </div>
                                            )}
                                        </div>
                                    ) : (
                                        <div className="text-slate-500 italic">No summary available.</div>
                                    )}
                                </div>
                            )}

                            {/* Transcript Tab */}
                            {activeTab === 'transcript' && (
                                <div className="p-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
                                    <h2 className="text-xl font-bold mb-6 text-slate-200">Transcription</h2>
                                    {meeting.status === 'processing' ? (
                                        <div className="text-center py-20 text-slate-500">Processing audio...</div>
                                    ) : meeting.transcription_text ? (
                                        <div className="space-y-6">
                                            {/* Ideally we use the JSON words for timestamps here, but for now simple text */}
                                            <p className="text-slate-300 leading-relaxed whitespace-pre-wrap">{meeting.transcription_text}</p>
                                        </div>
                                    ) : (
                                        <div className="text-slate-500 italic">No transcript available.</div>
                                    )}
                                </div>
                            )}

                        </div>
                    </div>

                </div>
            </div>
        </div>
    );
}
