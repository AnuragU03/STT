import { useMsal } from "@azure/msal-react";
import { loginRequest } from "../auth/msalConfig";

export default function LoginPage() {
    const { instance } = useMsal();

    const handleLogin = () => {
        instance.loginRedirect(loginRequest).catch((e) => {
            console.error("Login failed:", e);
        });
    };

    return (
        <div className="min-h-screen flex items-center justify-center bg-[var(--bg-color)] p-4">
            <div className="clay-card p-10 max-w-md w-full text-center space-y-6">
                {/* Logo / Icon */}
                <div className="flex justify-center">
                    <div className="w-20 h-20 rounded-full bg-indigo-500 flex items-center justify-center shadow-lg">
                        <svg className="w-10 h-10 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
                        </svg>
                    </div>
                </div>

                {/* Title */}
                <div>
                    <h1 className="text-3xl font-extrabold text-slate-700">MeetMind</h1>
                    <p className="text-slate-500 mt-2 text-sm">
                        AI-Powered Meeting Intelligence
                    </p>
                </div>

                {/* Features */}
                <div className="space-y-2 text-left px-4">
                    {[
                        { icon: "🎙️", text: "Live speaker diarization" },
                        { icon: "🤖", text: "GPT-4o meeting summaries" },
                        { icon: "📸", text: "ESP32-CAM image capture" },
                        { icon: "☁️", text: "Azure cloud storage" },
                    ].map((f, i) => (
                        <div key={i} className="flex items-center gap-3 text-sm text-slate-600">
                            <span className="text-lg">{f.icon}</span>
                            <span>{f.text}</span>
                        </div>
                    ))}
                </div>

                {/* Login Button */}
                <button
                    onClick={handleLogin}
                    className="clay-btn clay-btn-primary w-full py-3 px-6 text-base flex items-center justify-center gap-3"
                >
                    {/* Microsoft Logo SVG */}
                    <svg className="w-5 h-5" viewBox="0 0 21 21" fill="none">
                        <rect x="1" y="1" width="9" height="9" fill="#F25022" />
                        <rect x="11" y="1" width="9" height="9" fill="#7FBA00" />
                        <rect x="1" y="11" width="9" height="9" fill="#00A4EF" />
                        <rect x="11" y="11" width="9" height="9" fill="#FFB900" />
                    </svg>
                    Sign in with Microsoft
                </button>

                {/* Footer */}
                <p className="text-xs text-slate-400">
                    Secured by Microsoft Entra ID
                </p>
            </div>
        </div>
    );
}
