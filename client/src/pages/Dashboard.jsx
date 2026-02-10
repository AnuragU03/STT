import { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import axios from 'axios';
import {
    Play, FileText, Clock, CheckCircle, Loader2, AlertCircle,
    LayoutGrid, List as ListIcon, Music, Image as ImageIcon,
    MoreVertical, Search, HardDrive, Trash2, Edit2, X
} from 'lucide-react';

export default function Dashboard() {
    const [meetings, setMeetings] = useState([]);
    const [loading, setLoading] = useState(true);
    const [viewMode, setViewMode] = useState('grid'); // 'grid' | 'list'
    const [filter, setFilter] = useState('all'); // 'all' | 'audio' | 'image'
    const [searchQuery, setSearchQuery] = useState('');

    // Menu States
    const [activeMenu, setActiveMenu] = useState(null); // ID of active menu
    const menuRef = useRef(null);

    // Edit State
    const [renameId, setRenameId] = useState(null);
    const [newName, setNewName] = useState('');

    useEffect(() => {
        fetchMeetings();
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, []);

    const handleClickOutside = (event) => {
        if (menuRef.current && !menuRef.current.contains(event.target)) {
            setActiveMenu(null);
        }
    };

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

    const handleDelete = async (id, e) => {
        e.preventDefault(); // Prevent Link navigation
        if (!window.confirm("Are you sure you want to delete this file?")) return;

        try {
            await axios.delete(`/api/meetings/${id}`);
            setMeetings(meetings.filter(m => m.id !== id));
            setActiveMenu(null);
        } catch (error) {
            alert("Failed to delete file");
        }
    };

    const startRename = (meeting, e) => {
        e.preventDefault();
        setRenameId(meeting.id);
        setNewName(meeting.filename);
        setActiveMenu(null);
    };

    const submitRename = async (e) => {
        e.preventDefault();
        try {
            await axios.patch(`/api/meetings/${renameId}`, { new_filename: newName });
            setMeetings(meetings.map(m => m.id === renameId ? { ...m, filename: newName } : m));
            setRenameId(null);
        } catch (error) {
            alert("Failed to rename");
        }
    };

    const isImage = (filename) => /\.(jpg|jpeg|png|gif)$/i.test(filename || '');

    const filteredMeetings = meetings.filter(m => {
        if (filter === 'audio' && isImage(m.filename)) return false;
        if (filter === 'image' && !isImage(m.filename)) return false;
        if (searchQuery && !m.filename.toLowerCase().includes(searchQuery.toLowerCase())) return false;
        return true;
    });

    const getStatusColor = (status) => {
        switch (status) {
            case 'completed': return 'text-emerald-400 bg-emerald-400/10 border-emerald-400/20';
            case 'processing': return 'text-blue-400 bg-blue-400/10 border-blue-400/20';
            case 'failed': return 'text-rose-400 bg-rose-400/10 border-rose-400/20';
            default: return 'text-slate-400 bg-slate-400/10 border-slate-400/20';
        }
    };

    const StatCard = ({ title, value, icon: Icon, color }) => (
        <div className="bg-slate-800/40 border border-slate-700/50 p-4 rounded-2xl flex items-center gap-4">
            <div className={`p-3 rounded-xl ${color}`}>
                <Icon className="w-6 h-6" />
            </div>
            <div>
                <p className="text-slate-400 text-sm font-medium">{title}</p>
                <h3 className="text-2xl font-bold text-white">{value}</h3>
            </div>
        </div>
    );

    return (
        <div className="min-h-screen bg-[#0f172a] text-white p-4 md:p-8 font-sans selection:bg-blue-500/30">
            <div className="max-w-7xl mx-auto space-y-8">

                {/* Header */}
                <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
                    <div>
                        <h1 className="text-4xl font-bold bg-gradient-to-r from-blue-400 via-indigo-400 to-purple-400 bg-clip-text text-transparent">
                            My Drive
                        </h1>
                        <p className="text-slate-400 mt-1 flex items-center gap-2">
                            <HardDrive className="w-4 h-4" />
                            Storage used: {(meetings.reduce((acc, m) => acc + (m.file_size || 0), 0) / (1024 * 1024)).toFixed(2)} MB
                        </p>
                    </div>
                    <Link
                        to="/upload"
                        className="bg-blue-600 hover:bg-blue-500 text-white px-6 py-2.5 rounded-xl font-medium transition-all shadow-lg hover:shadow-blue-500/25 flex items-center gap-2 group"
                    >
                        <Play className="w-4 h-4 fill-white group-hover:scale-110 transition-transform" />
                        New Upload
                    </Link>
                </div>

                {/* Stats */}
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <StatCard title="Total Files" value={meetings.length} icon={FileText} color="bg-purple-500/20 text-purple-400" />
                    <StatCard title="Images" value={meetings.filter(m => isImage(m.filename)).length} icon={ImageIcon} color="bg-pink-500/20 text-pink-400" />
                    <StatCard title="Audio Recordings" value={meetings.filter(m => !isImage(m.filename)).length} icon={Music} color="bg-blue-500/20 text-blue-400" />
                </div>

                {/* Toolbar */}
                <div className="flex flex-col md:flex-row justify-between items-center gap-4 bg-slate-800/30 p-2 rounded-2xl border border-slate-700/50 backdrop-blur-xl">
                    <div className="flex items-center gap-1 bg-slate-900/50 p-1 rounded-xl">
                        {['all', 'audio', 'image'].map((t) => (
                            <button key={t} onClick={() => setFilter(t)} className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-all capitalize ${filter === t ? 'bg-slate-700 text-white shadow-sm' : 'text-slate-400 hover:text-white hover:bg-slate-800'}`}>
                                {t}
                            </button>
                        ))}
                    </div>
                    <div className="flex items-center gap-3 w-full md:w-auto">
                        <div className="relative flex-1 md:w-64">
                            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
                            <input type="text" placeholder="Search files..." value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} className="w-full bg-slate-900/50 border border-slate-700 rounded-xl py-2 pl-9 pr-4 text-sm focus:outline-none focus:border-blue-500/50 transition-colors placeholder:text-slate-600" />
                        </div>
                        <div className="flex items-center gap-1 bg-slate-900/50 p-1 rounded-xl">
                            <button onClick={() => setViewMode('grid')} className={`p-2 rounded-lg transition-all ${viewMode === 'grid' ? 'bg-slate-700 text-white' : 'text-slate-400 hover:bg-slate-800'}`}><LayoutGrid className="w-4 h-4" /></button>
                            <button onClick={() => setViewMode('list')} className={`p-2 rounded-lg transition-all ${viewMode === 'list' ? 'bg-slate-700 text-white' : 'text-slate-400 hover:bg-slate-800'}`}><ListIcon className="w-4 h-4" /></button>
                        </div>
                    </div>
                </div>

                {/* Content */}
                {loading ? (
                    <div className="flex justify-center py-20"><Loader2 className="w-10 h-10 animate-spin text-blue-500" /></div>
                ) : filteredMeetings.length === 0 ? (
                    <div className="flex flex-col items-center justify-center py-20 text-slate-500 bg-slate-800/20 rounded-3xl border border-slate-700/50 border-dashed">
                        <div className="bg-slate-800/50 p-4 rounded-full mb-4"><HardDrive className="w-8 h-8 opacity-50" /></div>
                        <p className="text-lg">No files found.</p>
                    </div>
                ) : (
                    <div className={viewMode === 'grid' ? "grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6" : "flex flex-col gap-3"}>
                        {filteredMeetings.map((meeting) => (
                            <div
                                key={meeting.id}
                                className={`group relative transition-all duration-300 ${viewMode === 'grid' ? 'bg-slate-800/40 hover:bg-slate-800/60 border border-slate-700/50 hover:border-blue-500/30 rounded-2xl hover:shadow-2xl hover:shadow-blue-500/10 hover:-translate-y-1' : 'bg-slate-800/20 hover:bg-slate-800/40 border border-slate-700/30 rounded-xl p-4 flex items-center justify-between'}`}
                            >
                                <Link
                                    to={`/meetings/${meeting.id}`}
                                    className={viewMode === 'grid' ? "block p-5 space-y-4" : "flex items-center gap-4 w-full"}
                                >

                                    {/* Icon / Thumbnail Box */}
                                    <div className={`
                                        flex items-center justify-center rounded-xl bg-slate-900/50 border border-slate-700/50 overflow-hidden
                                        ${viewMode === 'grid' ? 'h-32 w-full text-slate-400' : 'h-12 w-12 flex-shrink-0'}
                                    `}>
                                        {isImage(meeting.filename) ? (
                                            viewMode === 'grid' ? (
                                                <img
                                                    src={`/api/meetings/${meeting.id}/audio`}
                                                    alt={meeting.filename}
                                                    className="w-full h-full object-cover hover:scale-105 transition-transform duration-500"
                                                    onError={(e) => { e.target.style.display = 'none'; e.target.nextSibling.style.display = 'block' }}
                                                />
                                            ) : (
                                                <img
                                                    src={`/api/meetings/${meeting.id}/audio`}
                                                    alt={meeting.filename}
                                                    className="w-full h-full object-cover"
                                                />
                                            )
                                        ) : (
                                            <Music className={viewMode === 'grid' ? "w-10 h-10 text-blue-400" : "w-6 h-6 text-blue-400"} />
                                        )}
                                        {/* Fallback Icon (hidden if image loads) */}
                                        {isImage(meeting.filename) && viewMode === 'grid' && (
                                            <ImageIcon className="hidden w-10 h-10 text-pink-400 absolute" />
                                        )}
                                    </div>

                                    {/* Info */}
                                    <div className="flex-1 min-w-0 relative">
                                        <h3 className="font-semibold text-slate-200 truncate group-hover:text-white transition-colors">{meeting.filename}</h3>
                                        <div className="flex items-center gap-3 text-xs text-slate-400 mt-1">
                                            <span className="flex items-center gap-1"><Clock className="w-3 h-3" /> {new Date(meeting.upload_timestamp + (meeting.upload_timestamp.endsWith('Z') ? '' : 'Z')).toLocaleString()}</span>
                                            <span className={`px-2 py-0.5 rounded-full border ${getStatusColor(meeting.status)}`}>{meeting.status}</span>
                                        </div>
                                    </div>
                                </Link>

                                {/* Actions */}
                                <div className="absolute top-2 right-2 md:static pointer-events-auto" onClick={(e) => { e.preventDefault(); e.stopPropagation(); }}>
                                    <div className="relative">
                                        <button
                                            onClick={(e) => {
                                                e.preventDefault();
                                                setActiveMenu(activeMenu === meeting.id ? null : meeting.id);
                                            }}
                                            className="p-1.5 rounded-lg hover:bg-slate-700 text-slate-400 hover:text-white transition-colors z-20 relative bg-slate-800/50 backdrop-blur-sm border border-slate-700/50"
                                        >
                                            <MoreVertical className="w-5 h-5" />
                                        </button>

                                        {activeMenu === meeting.id && (
                                            <div ref={menuRef} className="absolute right-0 top-full mt-2 w-48 bg-slate-800 border border-slate-700 rounded-xl shadow-xl z-50 overflow-hidden animate-in fade-in zoom-in-95 duration-200">
                                                <button onClick={(e) => startRename(meeting, e)} className="w-full text-left px-4 py-3 text-sm text-slate-300 hover:bg-slate-700 hover:text-white flex items-center gap-2">
                                                    <Edit2 className="w-4 h-4" /> Rename
                                                </button>
                                                <button onClick={(e) => handleDelete(meeting.id, e)} className="w-full text-left px-4 py-3 text-sm text-rose-400 hover:bg-rose-500/10 hover:text-rose-300 flex items-center gap-2 border-t border-slate-700/50">
                                                    <Trash2 className="w-4 h-4" /> Delete
                                                </button>
                                            </div>
                                        )}
                                    </div>
                                </div>
                            </div>
                        ))}
                    </div>
                )}

                {/* Rename Modal */}
                {renameId && (
                    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center p-4 z-50">
                        <div className="bg-slate-800 border border-slate-700 p-6 rounded-2xl w-full max-w-md shadow-2xl animate-in zoom-in-95">
                            <h3 className="text-xl font-bold mb-4">Rename File</h3>
                            <form onSubmit={submitRename}>
                                <input
                                    autoFocus
                                    type="text"
                                    value={newName}
                                    onChange={(e) => setNewName(e.target.value)}
                                    className="w-full bg-slate-900 border border-slate-600 rounded-xl px-4 py-2 mb-6 focus:outline-none focus:border-blue-500 text-white"
                                />
                                <div className="flex justify-end gap-3">
                                    <button type="button" onClick={() => setRenameId(null)} className="px-4 py-2 rounded-lg text-slate-300 hover:bg-slate-700 transition-colors">Cancel</button>
                                    <button type="submit" className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white font-medium transition-colors">Save Changes</button>
                                </div>
                            </form>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}
