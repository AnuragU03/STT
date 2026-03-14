# MeetMind Client Module

## Overview

The MeetMind client module is a React-based web dashboard that provides the frontend interface for the AI-powered meeting intelligence platform. It serves as the primary user interface for viewing meeting insights, transcriptions, speaker diarization results, and AI-generated summaries from audio/video data captured by ESP32 IoT devices.

## Architecture

The client is built using modern web technologies:

- **React** - Core framework for the user interface
- **Vite** - Build tool and development server
- **Tailwind CSS** - Utility-first CSS framework for styling
- **PostCSS** - CSS processing with autoprefixer support

## Key Features

- Real-time meeting dashboard with live updates
- AI-generated meeting transcriptions and summaries
- Speaker diarization visualization
- Microsoft Entra ID authentication integration
- WebSocket support for live meeting status updates
- Role-based access control interface
- Responsive design for desktop and mobile devices

## Project Structure

```
client/
├── src/                    # React source code
│   ├── components/         # Reusable UI components
│   ├── pages/             # Application pages/views
│   ├── hooks/             # Custom React hooks
│   ├── services/          # API service layers
│   └── utils/             # Utility functions
├── public/                # Static assets
├── index.html            # Entry HTML file
├── vite.config.js        # Vite configuration
├── tailwind.config.js    # Tailwind CSS configuration
└── postcss.config.js     # PostCSS configuration
```

## Configuration

### Vite Configuration (`vite.config.js`)

```javascript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      }
    }
  }
})
```

**Features:**
- React plugin integration
- API proxy configuration for backend communication
- Development server setup with hot module replacement

### Tailwind CSS Configuration (`tailwind.config.js`)

```javascript
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
      }
    },
  },
  plugins: [],
}
```

**Features:**
- Content scanning for all React files
- Custom slow pulse animation for UI feedback
- Extensible theming system

### PostCSS Configuration (`postcss.config.js`)

```javascript
export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
}
```

**Features:**
- Tailwind CSS processing
- Autoprefixer for cross-browser compatibility

## Development Setup

### Prerequisites

- Node.js v16 or higher
- npm or yarn package manager

### Installation

1. Navigate to the client directory:
   ```bash
   cd client
   ```

2. Install dependencies:
   ```bash
   npm install
   ```

3. Start the development server:
   ```bash
   npm run dev
   ```

4. Open your browser to `http://localhost:5173`

### Available Scripts

```bash
npm run dev      # Start development server
npm run build    # Build for production
npm run preview  # Preview production build locally
npm run lint     # Run code linting
```

## API Integration

The client communicates with the backend through multiple channels:

- **REST API** - Data retrieval and management via `/api/*` endpoints
- **WebSocket** - Real-time meeting status updates and live data streaming
- **Development Proxy** - Requests to `/api/*` are automatically proxied to `http://localhost:8000`

For API documentation, see the [Backend API Reference](../backend/README.md#api-endpoints).

### Authentication Flow

1. **Microsoft Entra ID Integration** - Secure user authentication
2. **Role-based Access Control** - Feature availability based on user roles  
3. **Token Management** - Secure handling of authentication tokens for API requests

## Styling System

### Tailwind Utilities

The project uses a utility-first CSS approach with Tailwind:

```jsx
// Example component styling
<div className="bg-white shadow-lg rounded-lg p-6 animate-pulse-slow">
  <h2 className="text-xl font-semibold text-gray-800 mb-4">
    Meeting Dashboard
  </h2>
</div>
```

### Responsive Design

- **Mobile-first approach** with progressive enhancement
- **Breakpoint utilities** (`sm:`, `md:`, `lg:`, `xl:`)
- **Flexible grid layouts** for dashboard components

## Production Deployment

### Build Process

1. Generate optimized production build:
   ```bash
   npm run build
   ```

2. Deploy the `dist/` folder contents to your web server
3. Configure reverse proxy for API routes (see [Deployment Guide](../deployment/README.md))
4. Set up SSL/TLS certificates for HTTPS

### Environment Variables

Configure the following environment variables for production:

```bash
VITE_API_BASE_URL=https://your-api-domain.com
VITE_WEBSOCKET_URL=wss://your-websocket-domain.com
VITE_AUTH_CLIENT_ID=your-entra-id-client-id
```

## Browser Compatibility

### Supported Browsers

- **Chrome/Chromium 90+** (recommended)
- **Firefox 88+**
- **Safari 14+**
- **Edge 90+**

### Required Features

- ES6+ JavaScript support
- WebSocket API
- CSS Grid and Flexbox

## Performance Optimization

- **Code Splitting** - Automatic route-based code splitting with React.lazy()
- **Lazy Loading** - Dashboard components loaded on demand
- **WebSocket Management** - Efficient connection pooling and cleanup
- **React Optimization** - Memoization and efficient re-rendering patterns

## Security

### Client-Side Security

- **Content Security Policy (CSP)** headers for XSS protection
- **Secure Token Storage** - Authentication tokens stored securely
- **Input Sanitization** - React's built-in XSS protection
- **HTTPS Enforcement** - All production communication over HTTPS

### Authentication Security

For authentication setup and security best practices, see the [Authentication Guide](../auth/README.md).

## Troubleshooting

### Common Issues

- **Port Conflicts** - If port 5173 is busy, Vite will automatically use the next available port
- **API Connection** - Ensure the backend server is running on port 8000 during development
- **Build Errors** - Clear `node_modules` and reinstall dependencies if encountering build issues

For additional troubleshooting, see the [FAQ](../docs/FAQ.md).