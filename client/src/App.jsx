import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { MsalProvider, AuthenticatedTemplate, UnauthenticatedTemplate } from "@azure/msal-react";
import msalInstance from "./auth/msalInstance";
import "./auth/authInterceptor";   // Side-effect: registers axios Bearer-token interceptor
import Dashboard from './pages/Dashboard';
import MeetingDetail from './pages/MeetingDetail';
import UploadPage from './pages/UploadPage';
import LoginPage from './pages/LoginPage';

export default function App() {
    return (
        <MsalProvider instance={msalInstance}>
            <AuthenticatedTemplate>
                <BrowserRouter>
                    <Routes>
                        <Route path="/" element={<Dashboard />} />
                        <Route path="/upload" element={<UploadPage />} />
                        <Route path="/meetings/:id" element={<MeetingDetail />} />
                    </Routes>
                </BrowserRouter>
            </AuthenticatedTemplate>

            <UnauthenticatedTemplate>
                <LoginPage />
            </UnauthenticatedTemplate>
        </MsalProvider>
    );
}
