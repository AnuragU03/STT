import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import axios from 'axios';
import { Play, FileText, Clock, CheckCircle, Loader2, AlertCircle } from 'lucide-react';

export default function Dashboard() {
    const [meetings, setMeetings] = useState([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        fetchMeetings();
    }, []);

    const fetchMeetings = async () => {
        try {
            const res = await axios.get('/api/meetings');
            setMeetings(res.data);
        } catch (error) {
            console.error("Failed to fetch meetings", error);
        } finally {
            setLoading(false);
        }
    };

    const getStatusColor = (status) => {
        switch (status) {
            case 'completed': return 'text-green-400 bg-green-400/10';
            case 'processing': return 'text-blue-400 bg-blue-400/10';
            case 'failed': return 'text-red-400 bg-red-400/10';
            default: return 'text-gray-400 bg-gray-400/10';
        }
    };

    return (
        <div className="min-h-screen bg-slate-900 text-white p-8">
            <div className="max-w-6xl mx-auto">
                <div className="flex justify-between items-center mb-8">
                    <div>
                        <h1 className="text-3xl font-bold bg-gradient-to-r from-blue-400 to-purple-400 bg-clip-text text-transparent">
                            Meeting Intelligence
                        </h1>
                        <p className="text-slate-400 mt-1">Your automated transcription usage</p>
                    </div>
                    <Link
                        to="/upload"
                        className="bg-blue-600 hover:bg-blue-500 text-white px-6 py-2 rounded-lg font-medium transition-all shadow-lg hover:shadow-blue-500/25 flex items-center gap-2"
                    >
                        <Play className="w-4 h-4" /> New Recording
                    </Link>
                </div>

                {loading ? (
                    <div className="flex justify-center py-20">
                        <Loader2 className="w-8 h-8 animate-spin text-blue-500" />
                    </div>
                ) : (
                    <div className="grid gap-4">
                        {meetings.map((meeting) => (
                            <Link
                                key={meeting.id}
                                to={`/meetings/${meeting.id}`}
                                className="bg-slate-800/50 hover:bg-slate-800 border border-slate-700 hover:border-blue-500/50 rounded-xl p-6 transition-all group"
                            >
                                <div className="flex items-center justify-between">
                                    <div className="flex items-center gap-4">
                                        <div className={`p-3 rounded-full ${getStatusColor(meeting.status)}`}>
                                            {meeting.status === 'processing' ? <Loader2 className="w-6 h-6 animate-spin" /> : <FileText className="w-6 h-6" />}
                                        </div>
                                        <div>
                                            <h3 className="font-semibold text-lg group-hover:text-blue-400 transition-colors">
                                                {meeting.filename || "Untitled Meeting"}
                                            </h3>
                                            <div className="flex items-center gap-4 text-sm text-slate-400 mt-1">
                                                <span className="flex items-center gap-1">
                                                    <Clock className="w-3 h-3" />
                                                    {new Date(meeting.upload_timestamp).toLocaleString()}
                                                </span>
                                                <span className={`px-2 py-0.5 rounded-full text-xs font-medium uppercase tracking-wider ${getStatusColor(meeting.status)}`}>
                                                    {meeting.status}
                                                </span>
                                            </div>
                                        </div>
                                    </div>

                                    <div className="flex items-center gap-6">
                                        {meeting.summary && (
                                            <div className="hidden md:block text-slate-400 text-sm max-w-md truncate">
                                                {meeting.summary.substring(0, 80)}...
                                            </div>
                                        )}
                                    </div>
                                </div>
                            </Link>
                        ))}

                        {meetings.length === 0 && (
                            <div className="text-center py-20 bg-slate-800/30 rounded-2xl border border-slate-700 border-dashed">
                                <p className="text-slate-400">No meetings found. Upload one to get started!</p>
                            </div>
                        )}
                    </div>
                )}
            </div>
        </div>
    );
}
