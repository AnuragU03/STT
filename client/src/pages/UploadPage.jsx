import React, { useState, useCallback, useRef } from 'react';
import { useDropzone } from 'react-dropzone';
import { Link } from 'react-router-dom';
import axios from 'axios';

export default function UploadPage() {
    const [file, setFile] = useState(null);
    const [transcription, setTranscription] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [copied, setCopied] = useState(false);
    const [showTimestamps, setShowTimestamps] = useState(true);

    const audioRef = useRef(null);
    const [audioUrl, setAudioUrl] = useState(null);

    const onDrop = useCallback((acceptedFiles) => {
        const selected = acceptedFiles[0];
        if (selected) {
            setFile(selected);
            setAudioUrl(URL.createObjectURL(selected));
            setError(null);
            setTranscription(null);
        }
    }, []);

    const { getRootProps, getInputProps, isDragActive } = useDropzone({
        onDrop,
        accept: { 'audio/*': [], 'video/*': [] },
        maxFiles: 1
    });

    const handleTranscribe = async () => {
        if (!file) return;
        setLoading(true);
        setError(null);

        const formData = new FormData();
        formData.append('file', file);

        try {
            const response = await axios.post('/api/transcribe', formData, {
                headers: { 'Content-Type': 'multipart/form-data' }
            });
            
            const meetingId = response.data.meeting_id;
            if (!meetingId) {
                // Legacy sync response
                setTranscription(response.data);
                setLoading(false);
                return;
            }
            
            // Poll for completion
            const pollForResult = () => {
                const poll = setInterval(async () => {
                    try {
                        const pollRes = await axios.get(`/api/meetings/${meetingId}`);
                        const meeting = pollRes.data;
                        
                        if (meeting.status === 'completed') {
                            clearInterval(poll);
                            let words = [];
                            try { words = JSON.parse(meeting.transcription_json || '[]'); } catch(e) {}
                            setTranscription({ transcription: meeting.transcription_text, words });
                            setLoading(false);
                        } else if (meeting.status === 'failed') {
                            clearInterval(poll);
                            setError('Transcription failed: ' + (meeting.summary || 'Unknown error'));
                            setLoading(false);
                        }
                    } catch (pollErr) {
                        console.error('Poll error:', pollErr);
                    }
                }, 3000);
            };
            pollForResult();
            
        } catch (err) {
            console.error(err);
            setError(err.response?.data?.detail || 'Upload failed. Please try again.');
            setLoading(false);
        }
    };

    const handleCopy = () => {
        if (!transcription) return;
        let text = "";
        if (showTimestamps && transcription.words) {
            text = transcription.words.map(w => {
                const time = formatTime(w.start);
                return `[${time}] ${w.word}`;
            }).join(' ');
        } else {
            text = transcription.transcription;
        }
        navigator.clipboard.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
    };

    const handleExport = (withTimestamps) => {
        if (!transcription) return;
        let text = "";
        if (withTimestamps && transcription.words) {
            text = transcription.words.map(w => `[${formatTime(w.start)}] ${w.word}`).join(' ');
        } else {
            text = transcription.transcription;
        }
        const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = withTimestamps ? 'transcription-with-timestamps.txt' : 'transcription.txt';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
    };

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

    return (
        <div className="min-h-screen p-8 flex flex-col items-center" style={{ backgroundColor: '#f0f4f8' }}>
            <div className="w-full max-w-4xl mb-8">
                <Link to="/" className="inline-flex items-center text-slate-500 hover:text-indigo-600 transition-colors font-bold">
                    ← Back to Dashboard
                </Link>
            </div>

            <header className="w-full max-w-4xl mb-12 text-center">
                <h1 className="text-5xl font-extrabold text-slate-700 mb-4">
                    🎙️ Manual <span className="text-indigo-500">Recorder</span>
                </h1>
                <p className="text-slate-500 text-lg">
                    Upload a file manually for instant transcription
                </p>
            </header>

            <main className="w-full max-w-4xl space-y-8">
                {/* Upload Section */}
                <div
                    {...getRootProps()}
                    className={`clay-card p-12 transition-all duration-300 cursor-pointer border-2 border-dashed text-center ${isDragActive ? 'border-indigo-500 bg-indigo-50' : 'border-slate-300 hover:border-indigo-400'
                        } ${file ? 'border-green-400' : ''}`}
                >
                    <input {...getInputProps()} />
                    <div className="flex flex-col items-center gap-4">
                        {file ? (
                            <>
                                <span className="text-5xl">🎵</span>
                                <div className="text-center">
                                    <p className="text-xl font-bold text-green-600">{file.name}</p>
                                    <p className="text-slate-500">{(file.size / 1024 / 1024).toFixed(2)} MB</p>
                                </div>
                            </>
                        ) : (
                            <>
                                <span className="text-5xl">☁️</span>
                                <p className="text-xl font-bold text-slate-700">
                                    Drag & drop your audio here
                                </p>
                                <p className="text-slate-400">or click to browse files</p>
                            </>
                        )}
                    </div>
                </div>

                {/* Controls */}
                {file && (
                    <div className="flex justify-center">
                        <button
                            onClick={(e) => { e.stopPropagation(); handleTranscribe(); }}
                            disabled={loading}
                            className={`clay-btn-primary px-8 py-3 rounded-xl font-bold text-lg flex items-center gap-2 transition-all shadow-lg ${loading ? 'opacity-50 cursor-not-allowed' : ''
                                }`}
                        >
                            {loading ? (
                                <>
                                    <div className="animate-spin w-5 h-5 border-2 border-white border-t-transparent rounded-full"></div>
                                    Transcribing...
                                </>
                            ) : (
                                <>
                                    🚀 Start Transcription
                                </>
                            )}
                        </button>
                    </div>
                )}

                {/* Error */}
                {error && (
                    <div className="clay-card bg-red-50 border-2 border-red-200 text-red-600 p-4 text-center font-bold">
                        ❌ {error}
                    </div>
                )}

                {/* Results */}
                {transcription && (
                    <div className="clay-card p-8 space-y-6">
                        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-white/50 pb-6">
                            <h2 className="text-2xl font-bold text-slate-700">📝 Results</h2>

                            <div className="flex flex-wrap gap-2">
                                <button
                                    onClick={() => setShowTimestamps(!showTimestamps)}
                                    className="clay-btn px-4 py-2 text-sm text-slate-600"
                                >
                                    {showTimestamps ? '🕐 Hide Timestamps' : '🕐 Show Timestamps'}
                                </button>
                                <button
                                    onClick={() => handleExport(true)}
                                    className="clay-btn px-4 py-2 text-sm text-slate-600 flex items-center gap-1"
                                >
                                    📥 Export w/ Time
                                </button>
                                <button
                                    onClick={handleCopy}
                                    className="clay-btn px-4 py-2 text-sm text-green-600 flex items-center gap-1"
                                >
                                    {copied ? '✅ Copied!' : '📋 Copy Text'}
                                </button>
                            </div>
                        </div>

                        {/* Audio Player */}
                        {audioUrl && (
                            <audio ref={audioRef} controls src={audioUrl} className="w-full" />
                        )}

                        {/* Text Content */}
                        <div className="clay-card p-6 bg-white max-h-[500px] overflow-y-auto leading-relaxed text-lg scroll-hide">
                            {showTimestamps && transcription.words ? (
                                <div className="space-y-3">
                                    {transcription.words.map((w, i) => {
                                        const colors = ['bg-purple-100 text-purple-600', 'bg-blue-100 text-blue-600', 'bg-green-100 text-green-600', 'bg-orange-100 text-orange-600'];
                                        const speakerIndex = w.speaker ? w.speaker.charCodeAt(w.speaker.length - 1) % colors.length : 0;

                                        return (
                                            <div key={i} className="flex items-start gap-3">
                                                <div className={`w-8 h-8 rounded-full ${colors[speakerIndex]} flex items-center justify-center text-xs font-bold flex-shrink-0`}>
                                                    {w.speaker ? w.speaker.substring(0, 2).toUpperCase() : 'S1'}
                                                </div>
                                                <div className="bubble-left p-3 text-sm text-slate-600">
                                                    <span
                                                        className="text-xs text-indigo-500 font-mono mr-2 cursor-pointer hover:underline"
                                                        onClick={() => jumpToTime(w.start)}
                                                    >
                                                        [{formatTime(w.start)}]
                                                    </span>
                                                    {w.speaker && (
                                                        <span className="font-bold text-slate-700 mr-1">{w.speaker}:</span>
                                                    )}
                                                    <span>{w.word}</span>
                                                </div>
                                            </div>
                                        );
                                    })}
                                </div>
                            ) : (
                                <p className="text-slate-700">{transcription.transcription}</p>
                            )}
                        </div>
                    </div>
                )}
            </main>
        </div>
    );
}
