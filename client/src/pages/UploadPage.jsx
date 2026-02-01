import React, { useState, useCallback, useRef } from 'react';
import { useDropzone } from 'react-dropzone';
import { Link } from 'react-router-dom';
import { Upload, FileAudio, Play, Pause, Copy, Check, Download, Loader2, ArrowLeft } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import axios from 'axios';
import { clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

function cn(...inputs) {
    return twMerge(clsx(inputs));
}

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
        accept: {
            'audio/*': [],
            'video/*': []
        },
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
                headers: {
                    'Content-Type': 'multipart/form-data',
                },
            });

            setTranscription(response.data);
        } catch (err) {
            console.error(err);
            setError(err.response?.data?.detail || 'Transcription failed. Please try again.');
        } finally {
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
            text = transcription.words.map(w => {
                const time = formatTime(w.start);
                return `[${time}] ${w.word}`;
            }).join(' ');
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
        <div className="min-h-screen p-8 flex flex-col items-center bg-slate-900 text-white">
            <div className="w-full max-w-4xl mb-8">
                <Link to="/" className="inline-flex items-center text-slate-400 hover:text-white transition-colors">
                    <ArrowLeft className="w-4 h-4 mr-2" /> Back to Dashboard
                </Link>
            </div>

            <header className="w-full max-w-4xl mb-12 text-center">
                <h1 className="text-5xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-blue-400 to-purple-500 mb-4">
                    Manual Recorder
                </h1>
                <p className="text-slate-400 text-lg">
                    Upload a file manually for instant transcription
                </p>
            </header>

            <main className="w-full max-w-4xl space-y-8">
                {/* Upload Section */}
                <div
                    {...getRootProps()}
                    className={cn(
                        "glass rounded-3xl p-12 transition-all duration-300 cursor-pointer border-2 border-dashed",
                        isDragActive ? "border-blue-500 bg-blue-500/10" : "border-slate-700 hover:border-blue-400/50",
                        file ? "border-green-500/50" : ""
                    )}
                >
                    <input {...getInputProps()} />
                    <div className="flex flex-col items-center gap-4">
                        {file ? (
                            <>
                                <FileAudio className="w-16 h-16 text-green-400" />
                                <div className="text-center">
                                    <p className="text-xl font-semibold text-green-400">{file.name}</p>
                                    <p className="text-slate-400">{(file.size / 1024 / 1024).toFixed(2)} MB</p>
                                </div>
                            </>
                        ) : (
                            <>
                                <Upload className="w-16 h-16 text-blue-400 mb-2" />
                                <p className="text-xl font-medium text-slate-200">
                                    Drag & drop your audio here
                                </p>
                                <p className="text-slate-400">or click to browse files</p>
                            </>
                        )}
                    </div>
                </div>

                {/* Controls */}
                <AnimatePresence>
                    {file && (
                        <motion.div
                            initial={{ opacity: 0, y: 20 }}
                            animate={{ opacity: 1, y: 0 }}
                            className="flex justify-center"
                        >
                            <button
                                onClick={(e) => { e.stopPropagation(); handleTranscribe(); }}
                                disabled={loading}
                                className="bg-blue-600 hover:bg-blue-500 text-white px-8 py-3 rounded-xl font-semibold text-lg flex items-center gap-2 transition-all disabled:opacity-50 disabled:cursor-not-allowed shadow-lg shadow-blue-500/20"
                            >
                                {loading ? (
                                    <>
                                        <Loader2 className="w-5 h-5 animate-spin" />
                                        Transcribing...
                                    </>
                                ) : (
                                    <>
                                        <span>Start Transcription</span>
                                        <Play className="w-5 h-5 fill-current" />
                                    </>
                                )}
                            </button>
                        </motion.div>
                    )}
                </AnimatePresence>

                {/* Error */}
                {error && (
                    <div className="bg-red-500/10 border border-red-500/50 text-red-200 p-4 rounded-xl text-center">
                        {error}
                    </div>
                )}

                {/* Results */}
                {transcription && (
                    <motion.div
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        className="glass rounded-3xl p-8 space-y-6"
                    >
                        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-white/10 pb-6">
                            <h2 className="text-2xl font-semibold">Results</h2>

                            <div className="flex flex-wrap gap-2">
                                <button
                                    onClick={() => setShowTimestamps(!showTimestamps)}
                                    className="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 transition"
                                >
                                    {showTimestamps ? 'Hide Timestamps' : 'Show Timestamps'}
                                </button>

                                <button
                                    onClick={() => handleExport(true)}
                                    className="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 transition flex items-center gap-2"
                                >
                                    <Download className="w-4 h-4" /> Export w/ Time
                                </button>

                                <button
                                    onClick={handleCopy}
                                    className="px-4 py-2 rounded-lg bg-green-600/20 text-green-400 hover:bg-green-600/30 transition flex items-center gap-2"
                                >
                                    {copied ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
                                    {copied ? 'Copied!' : 'Copy Text'}
                                </button>
                            </div>
                        </div>

                        {/* Audio Player */}
                        {audioUrl && (
                            <audio
                                ref={audioRef}
                                controls
                                src={audioUrl}
                                className="w-full mb-4 opacity-80 hover:opacity-100 transition"
                            />
                        )}

                        {/* Text Content */}
                        <div className="bg-slate-950/50 rounded-xl p-6 max-h-[500px] overflow-y-auto leading-relaxed text-lg">
                            {showTimestamps && transcription.words ? (
                                <div className="flex flex-wrap gap-x-1 gap-y-2">
                                    {transcription.words.map((w, i) => (
                                        <span
                                            key={i}
                                            onClick={() => jumpToTime(w.start)}
                                            className="group cursor-pointer hover:bg-blue-500/20 rounded px-1 transition relative"
                                            title={`${formatTime(w.start)} - ${formatTime(w.end)}`}
                                        >
                                            <span className="text-xs text-blue-400 font-mono mr-1 select-none opacity-50 group-hover:opacity-100">
                                                [{formatTime(w.start)}]
                                            </span>
                                            <span className="group-hover:text-blue-200">{w.word}</span>
                                        </span>
                                    ))}
                                </div>
                            ) : (
                                <p>{transcription.transcription}</p>
                            )}
                        </div>
                    </motion.div>
                )}
            </main>
        </div>
    )
}
