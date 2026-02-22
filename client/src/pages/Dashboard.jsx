import { useState, useEffect, useRef, useCallback } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import axios from 'axios';
import { useDropzone } from 'react-dropzone';

export default function Dashboard() {
    const navigate = useNavigate();

    // =================== STATE ===================
    const [meetings, setMeetings] = useState([]);
    const [loading, setLoading] = useState(true);
    const [activeView, setActiveView] = useState('dashboard'); // 'dashboard' or 'storage'

    // ESP32 Status
    const [esp32Online, setEsp32Online] = useState(false);
    const [cam1Online, setCam1Online] = useState(false);
    const [cam2Online, setCam2Online] = useState(false);

    // ESP32 Remote Control
    const [isEsp32Recording, setIsEsp32Recording] = useState(false);
    const [recordingTime, setRecordingTime] = useState(0);
    const recordingTimerRef = useRef(null);





    // Upload
    const [uploadFile, setUploadFile] = useState(null);
    const [uploading, setUploading] = useState(false);
    const [uploadProgress, setUploadProgress] = useState(0);

    // Transcript
    const [transcriptData, setTranscriptData] = useState(null);
    const [transcriptText, setTranscriptText] = useState('');

    // AI Summary (real GPT-4o)
    const [summary, setSummary] = useState(null);
    const [generatingSummary, setGeneratingSummary] = useState(false);

    // Audio
    const audioRef = useRef(null);
    const [audioUrl, setAudioUrl] = useState(null);


    // Storage
    const [storageFilter, setStorageFilter] = useState('all'); // 'all', 'live', 'uploads', 'images'
    const [deletingId, setDeletingId] = useState(null);

    // =================== EFFECTS ===================
    useEffect(() => {
        fetchMeetings();
        checkEsp32Status();
        const statusInterval = setInterval(checkEsp32Status, 5000);
        return () => {
            clearInterval(statusInterval);
            if (recordingTimerRef.current) clearInterval(recordingTimerRef.current);
        };
    }, []);



    // =================== API ===================
    const fetchMeetings = async () => {
        try {
            const res = await axios.get('/api/meetings');
            setMeetings(res.data);
        } catch (e) {
            console.error("Fetch meetings failed", e);
        } finally {
            setLoading(false);
        }
    };

    const checkEsp32Status = async () => {
        try {
            const [micRes, cam1Res, cam2Res] = await Promise.allSettled([
                axios.get('/api/device/status?mac_address=MIC_DEVICE_01'),
                axios.get('/api/device/status?mac_address=CAM_DEVICE_01'),
                axios.get('/api/device/status?mac_address=CAM_DEVICE_02')
            ]);

            const micData = micRes.status === 'fulfilled' ? micRes.value.data : {};
            setEsp32Online(micData.connected);

            // Sync recording state from backend if needed (optional, adds robustness)
            if (micData.command === 'start' && !isEsp32Recording) {
                setIsEsp32Recording(true);
                // We don't know exact start time, so we just start timer from 0 or keep as is
                if (!recordingTimerRef.current) recordingTimerRef.current = setInterval(() => setRecordingTime(t => t + 1), 1000);
            } else if (micData.command === 'idle' && isEsp32Recording) {
                setIsEsp32Recording(false);
                if (recordingTimerRef.current) { clearInterval(recordingTimerRef.current); recordingTimerRef.current = null; }
                setRecordingTime(0);
            }

            setCam1Online(cam1Res.status === 'fulfilled' && cam1Res.value.data.connected);
            setCam2Online(cam2Res.status === 'fulfilled' && cam2Res.value.data.connected);
        } catch (e) {
            setEsp32Online(false);
            setCam1Online(false);
            setCam2Online(false);
        }
    };

    const deleteMeeting = async (id, e) => {
        e.stopPropagation();
        if (!confirm('Delete this file? This will remove audio, images, and all data from Azure.')) return;
        setDeletingId(id);
        try {
            await axios.delete(`/api/meetings/${id}`);
            setMeetings(prev => prev.filter(m => m.id !== id));
        } catch (err) {
            console.error("Delete failed:", err);
            alert('Failed to delete. Please try again.');
        } finally {
            setDeletingId(null);
        }
    };

    // =================== UPLOAD ===================
    const onDrop = useCallback((files) => {
        if (files[0]) {
            setUploadFile(files[0]);
            setAudioUrl(URL.createObjectURL(files[0]));
            setTranscriptData(null);
            setTranscriptText('');
            setSummary(null);
        }
    }, []);

    const { getRootProps, getInputProps, isDragActive } = useDropzone({
        onDrop,
        accept: { 'audio/*': [], 'video/*': [] },
        maxFiles: 1,
        noClick: false
    });

    const handleTranscribe = async () => {
        if (!uploadFile) return;
        setUploading(true);
        setUploadProgress(0);

        const formData = new FormData();
        formData.append('file', uploadFile);

        // Fake progress for upload phase (0-30%)
        const uploadInterval = setInterval(() => {
            setUploadProgress(prev => Math.min(prev + 5, 30));
        }, 200);

        try {
            // 1. Upload file — returns immediately with meeting_id
            const res = await axios.post('/api/transcribe', formData, {
                headers: { 'Content-Type': 'multipart/form-data' }
            });
            clearInterval(uploadInterval);
            setUploadProgress(35);

            const meetingId = res.data.meeting_id;
            if (!meetingId) {
                // Legacy sync response (fallback)
                setUploadProgress(100);
                setTranscriptData(res.data);
                setTranscriptText(res.data.transcription || '');
                setTimeout(() => { setUploading(false); }, 500);
                fetchMeetings();
                if (res.data.transcription && res.data.transcription.length > 10) {
                    generateSummaryFromText(res.data.transcription);
                }
                return;
            }

            // 2. Poll for completion
            let progress = 35;
            const pollInterval = setInterval(async () => {
                try {
                    const pollRes = await axios.get(`/api/meetings/${meetingId}`);
                    const meeting = pollRes.data;
                    
                    // Slowly increase progress while processing
                    progress = Math.min(progress + 1, 95);
                    setUploadProgress(progress);
                    
                    if (meeting.status === 'completed') {
                        clearInterval(pollInterval);
                        setUploadProgress(100);
                        
                        // Parse transcript data
                        let words = [];
                        try { words = JSON.parse(meeting.transcription_json || '[]'); } catch(e) {}
                        
                        setTranscriptData({ transcription: meeting.transcription_text, words });
                        setTranscriptText(meeting.transcription_text || '');
                        setTimeout(() => { setUploading(false); }, 500);
                        fetchMeetings();
                        
                        // Summary should already be generated by backend
                        if (meeting.summary) {
                            try {
                                const parsed = JSON.parse(meeting.summary);
                                setSummary(parsed);
                            } catch(e) {
                                setSummary({ summary: meeting.summary });
                            }
                        } else if (meeting.transcription_text && meeting.transcription_text.length > 10) {
                            generateSummaryFromText(meeting.transcription_text);
                        }
                    } else if (meeting.status === 'failed') {
                        clearInterval(pollInterval);
                        setUploading(false);
                        alert('Transcription failed: ' + (meeting.summary || 'Unknown error'));
                    }
                } catch (pollErr) {
                    console.error('Poll error:', pollErr);
                }
            }, 3000); // Poll every 3 seconds

        } catch (err) {
            clearInterval(uploadInterval);
            setUploading(false);
            console.error(err);
            alert(err.response?.data?.detail || 'Upload failed');
        }
    };



    // Real AI Summary using GPT-4o
    const generateSummaryFromText = async (text) => {
        if (!text || text.length < 10) return;
        setGeneratingSummary(true);
        try {
            const res = await axios.post('/api/summarize', { text });
            setSummary(res.data);
        } catch (e) {
            console.error("Summary failed:", e);
            setSummary({ summary: "Summary generation failed. Please try again.", action_items: e.response?.data?.detail || "Error occurred" });
        } finally {
            setGeneratingSummary(false);
        }
    };

    const handleGenerateInsights = () => {
        const text = transcriptText || transcriptData?.transcription || '';
        generateSummaryFromText(text);
    };

    // =================== ESP32 REMOTE CONTROL ===================
    const toggleEsp32Recording = async () => {
        if (!isEsp32Recording) {
            // Send START command
            try {
                await Promise.all([
                    axios.post('/api/device/command', { mac_address: 'MIC_DEVICE_01', command: 'start' }),
                    axios.post('/api/device/command', { mac_address: 'CAM_DEVICE_01', command: 'start' }),
                    axios.post('/api/device/command', { mac_address: 'CAM_DEVICE_02', command: 'start' }),
                ]);
                setIsEsp32Recording(true);
                setRecordingTime(0);
                recordingTimerRef.current = setInterval(() => setRecordingTime(t => t + 1), 1000);
            } catch (e) {
                console.error("Failed to start ESP32", e);
                alert("Failed to send start command to ESP32");
            }
        } else {
            // Send STOP command
            try {
                await Promise.all([
                    axios.post('/api/device/command', { mac_address: 'MIC_DEVICE_01', command: 'stop' }),
                    axios.post('/api/device/command', { mac_address: 'CAM_DEVICE_01', command: 'stop' }),
                    axios.post('/api/device/command', { mac_address: 'CAM_DEVICE_02', command: 'stop' }),
                ]);
                setIsEsp32Recording(false);
                if (recordingTimerRef.current) { clearInterval(recordingTimerRef.current); recordingTimerRef.current = null; }

                // Fetch meetings after a short delay to allow upload to finish
                setTimeout(fetchMeetings, 3000);
            } catch (e) {
                console.error("Failed to stop ESP32", e);
                alert("Failed to send stop command to ESP32");
            }
        }
    };




    // =================== HELPERS ===================
    const formatTime = (seconds) => {
        if (!seconds && seconds !== 0) return '00:00';
        return `${Math.floor(seconds / 60).toString().padStart(2, '0')}:${Math.floor(seconds % 60).toString().padStart(2, '0')}`;
    };

    const jumpToTime = (time) => { if (audioRef.current) { audioRef.current.currentTime = time; audioRef.current.play(); } };

    const getMeetingIcon = (m) => {
        if (m.device_type === 'cam1' || m.device_type === 'cam2') return '📸';
        if (m.filename?.startsWith('live')) return '🎙️';
        return '🎵';
    };

    const getMeetingType = (m) => {
        if (m.device_type === 'cam1' || m.device_type === 'cam2') return 'images';
        if (m.filename?.startsWith('live')) return 'live';
        return 'uploads';
    };

    const filteredMeetings = storageFilter === 'all'
        ? meetings
        : meetings.filter(m => getMeetingType(m) === storageFilter);

    // =================== RENDER ===================
    return (
        <div className="h-screen flex overflow-hidden">

            {/* ===== SIDEBAR ===== */}
            <aside className="w-20 lg:w-64 flex flex-col justify-between p-4 lg:p-6 z-10 transition-all duration-300 flex-shrink-0">
                <div className="flex flex-col gap-8">
                    <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-xl bg-indigo-500 flex items-center justify-center text-white shadow-lg text-xl">🎙️</div>
                        <h1 className="text-2xl font-extrabold text-slate-700 hidden lg:block tracking-tight">
                            Meet<span className="text-indigo-500">Mind</span>
                        </h1>
                    </div>

                    <nav className="flex flex-col gap-3">
                        <button
                            onClick={() => setActiveView('dashboard')}
                            className={`clay-btn p-4 flex items-center gap-3 ${activeView === 'dashboard' ? 'active text-indigo-600' : 'text-slate-500 hover:text-indigo-500'}`}
                        >
                            <span className="text-xl">📊</span>
                            <span className="hidden lg:block">Dashboard</span>
                        </button>
                        <Link to="/upload" className="clay-btn p-4 flex items-center gap-3 text-slate-500 hover:text-indigo-500">
                            <span className="text-xl">🎵</span>
                            <span className="hidden lg:block">Recordings</span>
                        </Link>
                        <button
                            onClick={() => setActiveView('storage')}
                            className={`clay-btn p-4 flex items-center gap-3 ${activeView === 'storage' ? 'active text-indigo-600' : 'text-slate-500 hover:text-indigo-500'}`}
                        >
                            <span className="text-xl">☁️</span>
                            <span className="hidden lg:block">Storage</span>
                        </button>
                    </nav>
                </div>

                <div className="clay-card p-4 hidden lg:flex items-center gap-3 cursor-pointer hover:scale-105 transition-transform">
                    <div className="w-10 h-10 rounded-full bg-indigo-200 flex items-center justify-center text-indigo-800 font-bold text-sm">VK</div>
                    <div className="flex flex-col">
                        <span className="text-sm font-bold text-slate-700">Vinshanks</span>
                        <span className="text-xs text-slate-500">Enterprise Plan</span>
                    </div>
                </div>
            </aside>

            {/* ===== MAIN CONTENT ===== */}
            <main className="flex-1 p-4 lg:p-6 overflow-y-auto flex flex-col gap-6 relative scroll-hide">

                <div className="flex justify-end mb-1">
                    <div className="flex items-center gap-2 px-4 py-2 rounded-full bg-blue-100 text-blue-700 font-bold text-xs shadow-sm">
                        ☁️ Azure Blob Storage Connected
                    </div>
                </div>

                {/* =============== DASHBOARD VIEW =============== */}
                {activeView === 'dashboard' && (
                    <>
                        {/* TOP ROW */}
                        <div className="grid grid-cols-1 md:grid-cols-12 gap-6 min-h-[370px]">
                            <div className="col-span-1 md:col-span-7 clay-card p-5 flex flex-col justify-between relative overflow-hidden">
                                <div className="absolute top-0 right-0 w-40 h-40 bg-indigo-400 rounded-full mix-blend-multiply filter blur-3xl opacity-15 -translate-y-1/2 translate-x-1/2"></div>
                                <div className="absolute bottom-0 left-0 w-32 h-32 bg-blue-300 rounded-full mix-blend-multiply filter blur-3xl opacity-10 translate-y-1/2 -translate-x-1/2"></div>
                                
                                <div className="flex justify-between items-start z-10">
                                    <div>
                                        <h2 className="text-xl font-bold text-slate-700 flex items-center gap-2">
                                            <span className="text-2xl">🧠</span> Live Meeting Intelligence
                                        </h2>
                                        <p className="text-sm mt-1 flex items-center gap-2">
                                            <span className={`w-2.5 h-2.5 rounded-full inline-block ${esp32Online ? 'bg-green-400 recording-dot' : 'bg-slate-300'}`}></span>
                                            <span className={esp32Online ? 'text-green-600 font-semibold' : 'text-slate-400'}>
                                                {esp32Online ? 'ESP32 Connected • Ready' : 'ESP32 Offline'}
                                            </span>
                                        </p>
                                    </div>
                                    {isEsp32Recording && (
                                        <div className="flex items-center gap-2 text-red-500 font-bold bg-red-50 px-4 py-1.5 rounded-full shadow-sm border border-red-100">
                                            <div className="w-2.5 h-2.5 bg-red-500 rounded-full recording-dot"></div>
                                            <span className="text-xs">REC</span>
                                            <span className="text-xs font-mono bg-red-100 px-2 py-0.5 rounded-full">{formatTime(recordingTime)}</span>
                                        </div>
                                    )}
                                </div>

                                <div className="flex-1 flex items-center justify-center my-3 z-10">
                                    <div className="flex flex-col items-center gap-2">
                                        <button 
                                            onClick={toggleEsp32Recording} 
                                            className={`w-20 h-20 rounded-full flex items-center justify-center text-3xl transition-all duration-300 ${
                                                isEsp32Recording 
                                                    ? 'bg-red-500 text-white shadow-lg shadow-red-200 scale-110 hover:bg-red-600' 
                                                    : 'clay-btn text-slate-400 hover:text-indigo-500 hover:scale-105'
                                            }`}
                                        >
                                            {isEsp32Recording ? '⏹️' : '🎙️'}
                                        </button>
                                        <p className="text-xs text-slate-400 font-medium">
                                            {isEsp32Recording ? 'Recording in progress...' : 'Tap to start recording'}
                                        </p>
                                    </div>
                                </div>

                                <div className="z-10">
                                    <label className="text-[10px] text-slate-400 font-bold tracking-widest uppercase ml-1 mb-2 block">Device Status</label>
                                    <div className="flex gap-2">
                                        <div className={`flex-1 rounded-xl px-3 py-2.5 flex items-center gap-2.5 transition-all duration-300 ${
                                            esp32Online 
                                                ? 'bg-green-50 border border-green-200' 
                                                : 'bg-slate-50 border border-slate-200'
                                        }`}>
                                            <div className={`w-8 h-8 rounded-lg flex items-center justify-center text-sm ${
                                                esp32Online ? 'bg-green-100 text-green-600' : 'bg-slate-100 text-slate-400'
                                            }`}>🎙️</div>
                                            <div className="flex flex-col">
                                                <span className={`text-xs font-bold ${esp32Online ? 'text-green-700' : 'text-slate-500'}`}>Microphone</span>
                                                <span className={`text-[10px] ${esp32Online ? 'text-green-500' : 'text-slate-400'}`}>
                                                    {esp32Online ? 'Connected' : 'Offline'}
                                                </span>
                                            </div>
                                        </div>
                                        <div className={`flex-1 rounded-xl px-3 py-2.5 flex items-center gap-2.5 transition-all duration-300 ${
                                            cam1Online 
                                                ? 'bg-green-50 border border-green-200' 
                                                : 'bg-slate-50 border border-slate-200'
                                        }`}>
                                            <div className={`w-8 h-8 rounded-lg flex items-center justify-center text-sm ${
                                                cam1Online ? 'bg-green-100 text-green-600' : 'bg-slate-100 text-slate-400'
                                            }`}>📷</div>
                                            <div className="flex flex-col">
                                                <span className={`text-xs font-bold ${cam1Online ? 'text-green-700' : 'text-slate-500'}`}>Camera A</span>
                                                <span className={`text-[10px] ${cam1Online ? 'text-green-500' : 'text-slate-400'}`}>
                                                    {cam1Online ? 'Connected' : 'Offline'}
                                                </span>
                                            </div>
                                        </div>
                                        <div className={`flex-1 rounded-xl px-3 py-2.5 flex items-center gap-2.5 transition-all duration-300 ${
                                            cam2Online 
                                                ? 'bg-green-50 border border-green-200' 
                                                : 'bg-slate-50 border border-slate-200'
                                        }`}>
                                            <div className={`w-8 h-8 rounded-lg flex items-center justify-center text-sm ${
                                                cam2Online ? 'bg-green-100 text-green-600' : 'bg-slate-100 text-slate-400'
                                            }`}>📷</div>
                                            <div className="flex flex-col">
                                                <span className={`text-xs font-bold ${cam2Online ? 'text-green-700' : 'text-slate-500'}`}>Camera B</span>
                                                <span className={`text-[10px] ${cam2Online ? 'text-green-500' : 'text-slate-400'}`}>
                                                    {cam2Online ? 'Connected' : 'Offline'}
                                                </span>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>

                            <div className={`col-span-1 md:col-span-5 clay-card p-6 flex flex-col items-center justify-center text-center relative border-dashed border-2 ${isDragActive ? 'border-indigo-400' : 'border-indigo-200'} transition-colors`} {...getRootProps()}>
                                <input {...getInputProps()} />
                                {uploading ? (
                                    <div className="w-full px-8 pointer-events-none">
                                        <p className="font-bold text-indigo-600 mb-2">Transcribing...</p>
                                        <div className="w-full bg-gray-200 rounded-full h-2.5 overflow-hidden">
                                            <div className="bg-indigo-600 h-2.5 rounded-full transition-all duration-300" style={{ width: `${uploadProgress}%` }}></div>
                                        </div>
                                        <p className="text-xs text-slate-400 mt-2">Azure Cognitive Services Processing</p>
                                    </div>
                                ) : uploadFile && transcriptData ? (
                                    <div className="text-green-500 pointer-events-none"><span className="text-3xl">✅</span><h3 className="font-bold text-slate-700 mt-2">File Processed!</h3><p className="text-xs text-slate-400">AI Summary auto-generated</p></div>
                                ) : (
                                    <div className="pointer-events-none">
                                        <div className="w-16 h-16 rounded-full bg-indigo-50 text-indigo-500 flex items-center justify-center mx-auto mb-4 clay-btn text-2xl">☁️</div>
                                        <h3 className="font-bold text-slate-700">Drag & Drop file</h3>
                                        <p className="text-slate-400 text-sm mt-1">MP3, M4A, WAV supported</p>
                                        {uploadFile && <p className="text-indigo-600 font-bold text-sm mt-2">{uploadFile.name}</p>}
                                    </div>
                                )}
                                {uploadFile && !uploading && !transcriptData && (
                                    <button onClick={(e) => { e.stopPropagation(); handleTranscribe(); }} className="mt-4 clay-btn-primary px-6 py-2 rounded-xl text-sm font-bold shadow-lg pointer-events-auto">🚀 Start Transcription</button>
                                )}
                            </div>
                        </div>

                        {/* MIDDLE ROW */}
                        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 min-h-[350px]">
                            <div className="md:col-span-2 clay-card flex flex-col overflow-hidden relative">
                                <div className="p-5 border-b border-white/50 flex justify-between items-center">
                                    <h3 className="font-bold text-slate-700">📝 Smart Transcript</h3>
                                    <div className="text-xs text-slate-500 bg-white px-2 py-1 rounded-lg shadow-sm">Speaker ID Active</div>
                                </div>
                                <div className="flex-1 overflow-y-auto p-5 space-y-4 scroll-hide pb-20">
                                    {transcriptData?.words && transcriptData.words.length > 0 ? (
                                        transcriptData.words.map((w, i) => {
                                            const colors = ['bg-purple-100 text-purple-600', 'bg-blue-100 text-blue-600', 'bg-green-100 text-green-600', 'bg-orange-100 text-orange-600'];
                                            const si = w.speaker ? w.speaker.charCodeAt(w.speaker.length - 1) % colors.length : 0;
                                            return (
                                                <div key={i} className="flex items-start gap-3">
                                                    <div className={`w-8 h-8 rounded-full ${colors[si]} flex items-center justify-center text-xs font-bold flex-shrink-0`}>{w.speaker ? w.speaker.substring(0, 2).toUpperCase() : 'S1'}</div>
                                                    <div className={`${w.speaker === 'Guest-1' ? 'bubble-right' : 'bubble-left'} p-3 text-sm text-slate-600`}>
                                                        <span className="text-xs text-indigo-500 font-mono mr-2 cursor-pointer hover:underline" onClick={() => jumpToTime(w.start)}>[{formatTime(w.start)}]</span>
                                                        <span className="font-semibold text-slate-700 mr-1">{w.speaker || 'Speaker'}:</span>{w.word}
                                                    </div>
                                                </div>
                                            );
                                        })
                                    ) : transcriptText ? (
                                        <div className="bubble-left p-3 text-sm text-slate-600">{transcriptText}</div>
                                    ) : (
                                        <div className="flex items-start gap-3 opacity-50">
                                            <div className="w-8 h-8 rounded-full bg-purple-100 flex items-center justify-center text-purple-600 text-xs font-bold flex-shrink-0">SYS</div>
                                            <div className="bubble-right p-3 text-sm text-slate-600">Upload a file or start recording to see real-time transcription here.</div>
                                        </div>
                                    )}
                                </div>
                                {audioUrl && (
                                    <div className="absolute bottom-4 left-4 right-4 clay-card p-3 flex items-center gap-4 bg-white/90 backdrop-blur-md">
                                        <audio ref={audioRef} src={audioUrl} className="w-full h-8" controls />
                                    </div>
                                )}
                            </div>

                            <div className="md:col-span-1 clay-card flex flex-col overflow-hidden">
                                <div className="p-5 border-b border-white/50 flex items-center justify-between flex-shrink-0">
                                    <h3 className="font-bold text-slate-700">✨ AI Summary</h3>
                                    <span className="text-xs px-2 py-1 bg-indigo-100 text-indigo-600 rounded-md font-bold">GPT-4o</span>
                                </div>
                                <div className="flex-1 overflow-y-auto p-5 scroll-hide">
                                    {generatingSummary ? (
                                        <div className="flex flex-col items-center justify-center text-center h-full">
                                            <div className="animate-spin w-8 h-8 border-2 border-indigo-500 border-t-transparent rounded-full mb-4"></div>
                                            <p className="text-sm text-indigo-600 font-bold">Generating AI Summary...</p>
                                            <p className="text-xs text-slate-400 mt-1">GPT-4o is analyzing your transcript</p>
                                        </div>
                                    ) : !summary ? (
                                        <div className="flex flex-col items-center justify-center text-center h-full">
                                            <span className="text-4xl mb-2">🤖</span>
                                            <p className="text-sm text-slate-500">Waiting for meeting data...</p>
                                            <button onClick={handleGenerateInsights} disabled={!transcriptData && !transcriptText}
                                                className={`clay-btn-primary px-6 py-2 rounded-xl mt-4 text-sm font-bold shadow-lg ${(!transcriptData && !transcriptText) ? 'opacity-50 cursor-not-allowed' : ''}`}>
                                                Generate Insights
                                            </button>
                                        </div>
                                    ) : (
                                        <div className="space-y-4">
                                            <div className="clay-card p-4 bg-white">
                                                <h4 className="text-xs font-bold text-slate-400 uppercase mb-2 tracking-wider">Executive Summary</h4>
                                                <p className="text-sm text-slate-700 leading-relaxed whitespace-pre-wrap">{summary.summary}</p>
                                            </div>
                                            {summary.topics_discussed && Array.isArray(summary.topics_discussed) && summary.topics_discussed.length > 0 && (
                                                <div className="clay-card p-4 bg-white">
                                                    <h4 className="text-xs font-bold text-slate-400 uppercase mb-2 tracking-wider">Topics Discussed</h4>
                                                    <div className="flex flex-wrap gap-2">
                                                        {summary.topics_discussed.map((topic, i) => (
                                                            <span key={i} className="text-xs bg-indigo-50 text-indigo-600 px-2 py-1 rounded-full font-bold">{topic}</span>
                                                        ))}
                                                    </div>
                                                </div>
                                            )}
                                            {summary.key_decisions && Array.isArray(summary.key_decisions) && summary.key_decisions.length > 0 && (
                                                <div className="clay-card p-4 bg-white">
                                                    <h4 className="text-xs font-bold text-slate-400 uppercase mb-2 tracking-wider">Key Decisions</h4>
                                                    <ul className="space-y-2">
                                                        {summary.key_decisions.map((d, i) => (
                                                            <li key={i} className="flex items-start gap-2 text-sm text-slate-600">
                                                                <span className="text-green-500 flex-shrink-0">✔</span>
                                                                <span>{typeof d === 'string' ? d : JSON.stringify(d)}</span>
                                                            </li>
                                                        ))}
                                                    </ul>
                                                </div>
                                            )}
                                            {summary.action_items && (
                                                <div className="clay-card p-4 bg-white">
                                                    <h4 className="text-xs font-bold text-slate-400 uppercase mb-2 tracking-wider">Action Items</h4>
                                                    {Array.isArray(summary.action_items) ? (
                                                        <ul className="space-y-2">{summary.action_items.map((item, i) => (
                                                            <li key={i} className="flex items-start gap-2 text-sm text-slate-600">
                                                                <input type="checkbox" className="mt-1 rounded text-indigo-500" />
                                                                <span>{typeof item === 'string' ? item : JSON.stringify(item)}</span>
                                                            </li>
                                                        ))}</ul>
                                                    ) : (
                                                        <p className="text-sm text-slate-700 whitespace-pre-wrap">{typeof summary.action_items === 'string' ? summary.action_items : JSON.stringify(summary.action_items, null, 2)}</p>
                                                    )}
                                                </div>
                                            )}
                                            <button onClick={handleGenerateInsights} className="clay-btn px-4 py-2 text-xs text-indigo-600 w-full">🔄 Regenerate</button>
                                        </div>
                                    )}
                                </div>
                            </div>
                        </div>

                        {/* BOTTOM ROW: Recent 3 */}
                        <div className="clay-card p-6">
                            <div className="flex justify-between items-center mb-4">
                                <h3 className="font-bold text-slate-700">📋 Recent Meetings</h3>
                                <button onClick={() => setActiveView('storage')} className="text-xs text-indigo-600 font-bold hover:underline">View All →</button>
                            </div>
                            {loading ? (
                                <div className="text-center py-8 text-slate-400">Loading...</div>
                            ) : meetings.length === 0 ? (
                                <div className="text-center py-8 text-slate-400"><span className="text-3xl">📭</span><p className="mt-2 text-sm">No meetings yet.</p></div>
                            ) : (
                                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                                    {meetings.slice(0, 3).map(m => (
                                        <button key={m.id} onClick={() => navigate(`/meetings/${m.id}`)} className="clay-btn p-4 flex items-center gap-3 text-slate-600 hover:text-indigo-600 transition-colors text-left w-full">
                                            <span className="text-xl flex-shrink-0">{getMeetingIcon(m)}</span>
                                            <div className="flex-1 min-w-0">
                                                <p className="font-bold text-sm truncate">{m.filename}</p>
                                                <span className={`text-xs font-bold ${m.status === 'completed' ? 'text-green-600' : m.status === 'processing' ? 'text-blue-600' : 'text-red-600'}`}>
                                                    {m.status === 'completed' ? '✅' : m.status === 'processing' ? '⏳' : '❌'} {m.status}
                                                </span>
                                            </div>
                                            <span className="text-slate-400">→</span>
                                        </button>
                                    ))}
                                </div>
                            )}
                        </div>
                    </>
                )}

                {/* =============== STORAGE VIEW (Drive-like) =============== */}
                {activeView === 'storage' && (
                    <div className="flex flex-col gap-6">
                        <div className="flex items-center justify-between flex-wrap gap-4">
                            <div>
                                <h2 className="text-2xl font-extrabold text-slate-700">☁️ Storage</h2>
                                <p className="text-sm text-slate-500 mt-1">Manage your recordings, live streams & captured images</p>
                            </div>
                            <button onClick={() => setActiveView('dashboard')} className="clay-btn px-4 py-2 text-sm text-slate-600 font-bold">← Back to Dashboard</button>
                        </div>

                        {/* Stats */}
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                            {[
                                { label: 'All Files', filter: 'all', count: meetings.length, icon: '📂', color: 'text-slate-700' },
                                { label: 'Live Sessions', filter: 'live', count: meetings.filter(m => getMeetingType(m) === 'live').length, icon: '🎙️', color: 'text-indigo-600' },
                                { label: 'Uploads', filter: 'uploads', count: meetings.filter(m => getMeetingType(m) === 'uploads').length, icon: '🎵', color: 'text-green-600' },
                                { label: 'Images', filter: 'images', count: meetings.filter(m => getMeetingType(m) === 'images').length, icon: '📸', color: 'text-orange-600' },
                            ].map(s => (
                                <button
                                    key={s.filter}
                                    onClick={() => setStorageFilter(s.filter)}
                                    className={`clay-btn p-4 text-center transition-all ${storageFilter === s.filter ? 'active' : ''}`}
                                >
                                    <span className="text-2xl">{s.icon}</span>
                                    <p className={`text-2xl font-extrabold mt-1 ${s.color}`}>{s.count}</p>
                                    <p className="text-xs text-slate-500">{s.label}</p>
                                </button>
                            ))}
                        </div>

                        {/* File List with CRUD */}
                        <div className="clay-card p-6">
                            <div className="flex justify-between items-center mb-4">
                                <h3 className="font-bold text-slate-700">
                                    {storageFilter === 'all' ? '📂 All Files' : storageFilter === 'live' ? '🎙️ Live Sessions' : storageFilter === 'uploads' ? '🎵 Uploaded Files' : '📸 Camera Images'}
                                    <span className="text-slate-400 font-normal ml-2">({filteredMeetings.length})</span>
                                </h3>
                            </div>

                            {filteredMeetings.length === 0 ? (
                                <div className="text-center py-12 text-slate-400">
                                    <span className="text-4xl">📭</span>
                                    <p className="mt-3 text-sm">No files in this category.</p>
                                </div>
                            ) : (
                                <div className="space-y-3 max-h-[500px] overflow-y-auto scroll-hide pr-2">
                                    {filteredMeetings.map(m => (
                                        <div
                                            key={m.id}
                                            className="clay-btn p-4 flex items-center gap-4 w-full text-left text-slate-600 hover:text-indigo-600 transition-colors group"
                                        >
                                            <span className="text-2xl flex-shrink-0">{getMeetingIcon(m)}</span>

                                            {/* Clickable content area */}
                                            <button onClick={() => navigate(`/meetings/${m.id}`)} className="flex-1 min-w-0 text-left">
                                                <p className="font-bold text-sm truncate">{m.filename}</p>
                                                <div className="flex items-center gap-3 mt-1 flex-wrap">
                                                    <span className={`text-xs font-bold ${m.status === 'completed' ? 'text-green-600' : m.status === 'processing' ? 'text-blue-600' : 'text-red-600'}`}>
                                                        {m.status === 'completed' ? '✅' : m.status === 'processing' ? '⏳' : '❌'} {m.status}
                                                    </span>
                                                    {m.mac_address && <span className="text-xs text-slate-400">🔌 {m.mac_address}</span>}
                                                    {m.device_type && <span className="text-xs text-slate-400">📟 {m.device_type}</span>}
                                                    <span className="text-xs text-slate-400">
                                                        🕐 {m.upload_timestamp ? new Date(m.upload_timestamp).toLocaleString() : 'N/A'}
                                                    </span>
                                                </div>
                                            </button>

                                            {/* Action Buttons */}
                                            <div className="flex items-center gap-2 flex-shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
                                                <button
                                                    onClick={() => navigate(`/meetings/${m.id}`)}
                                                    className="clay-btn w-9 h-9 rounded-lg flex items-center justify-center text-indigo-600 hover:bg-indigo-50 text-sm"
                                                    title="Open"
                                                >👁️</button>
                                                <button
                                                    onClick={(e) => deleteMeeting(m.id, e)}
                                                    disabled={deletingId === m.id}
                                                    className="clay-btn w-9 h-9 rounded-lg flex items-center justify-center text-red-500 hover:bg-red-50 text-sm"
                                                    title="Delete from Azure & DB"
                                                >
                                                    {deletingId === m.id ? (
                                                        <div className="animate-spin w-4 h-4 border-2 border-red-400 border-t-transparent rounded-full"></div>
                                                    ) : '🗑️'}
                                                </button>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>
                    </div>
                )}
            </main>
        </div>
    );
}
