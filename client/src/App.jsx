import { BrowserRouter, Routes, Route } from 'react-router-dom';
import Dashboard from './pages/Dashboard';
import MeetingDetail from './pages/MeetingDetail';
import UploadPage from './pages/UploadPage';

export default function App() {
    return (
        <BrowserRouter>
            <Routes>
                <Route path="/" element={<Dashboard />} />
                <Route path="/upload" element={<UploadPage />} />
                <Route path="/meetings/:id" element={<MeetingDetail />} />
            </Routes>
        </BrowserRouter>
    );
}
