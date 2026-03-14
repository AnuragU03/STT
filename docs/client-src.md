# MeetMind Client Source Module

The `client/src` module contains the React frontend application for MeetMind, an AI-powered meeting intelligence platform. This module provides the user interface for managing meetings, viewing AI-generated insights, and handling Microsoft Entra ID authentication.

## Module Overview

The client application is built with React and provides:

- Microsoft Entra ID authentication with MSAL (Microsoft Authentication Library)
- Protected routes for authenticated users
- Automatic API authentication via axios interceptors
- Meeting dashboard and detail views
- File upload functionality for meeting recordings

## Architecture

```
client/src/
├── App.jsx                    # Main application component with routing
├── auth/                      # Authentication configuration and utilities
│   ├── authInterceptor.js     # Axios interceptor for API authentication
│   ├── msalConfig.js          # MSAL configuration and constants
│   └── msalInstance.js        # MSAL singleton instance
└── pages/                     # Application pages
    ├── Dashboard.jsx          # Meeting list view
    ├── MeetingDetail.jsx      # Individual meeting details
    ├── UploadPage.jsx         # File upload interface
    └── LoginPage.jsx          # Authentication page
```

## Key Components

### App.jsx

The main application component that handles routing and authentication flow.

**Features:**
- Uses `MsalProvider` for Microsoft authentication context
- Conditionally renders authenticated vs. unauthenticated templates
- Defines protected routes for the main application

**Routes:**
- `/` - Dashboard (meeting list)
- `/upload` - File upload page
- `/meetings/:id` - Meeting detail view

### Authentication Module

#### msalConfig.js

Contains Microsoft Entra ID configuration for the application.

**Key Configuration:**

```javascript
const CLIENT_ID = "3de8d03b-a1c9-4ad8-8553-604e842eb7ce";

export const msalConfig = {
    auth: {
        clientId: CLIENT_ID,
        authority: "https://login.microsoftonline.com/common", // Multi-tenant
        redirectUri: window.location.origin,
    },
    cache: {
        cacheLocation: "localStorage",
    },
};

export const loginRequest = {
    scopes: ["User.Read"],
};
```

#### msalInstance.js

Singleton MSAL instance that manages authentication state across the application.

**Features:**
- Handles redirect promises for login flows
- Automatically sets active account after authentication
- Event listeners for login success

#### authInterceptor.js

Axios interceptor that automatically attaches authentication tokens to API requests.

**Important:** Uses ID token (not access token) because:
- Access token is scoped for Microsoft Graph (`aud=graph.microsoft.com`)
- ID token is issued for the MeetMind app (`aud=CLIENT_ID`)
- Backend validates the ID token

For more details on token usage, see [Security Features](#security-features).

## Usage Examples

### Basic App Setup

```jsx
import { MsalProvider } from "@azure/msal-react";
import msalInstance from "./auth/msalInstance";
import App from "./App";

// Wrap your app with MsalProvider
function Root() {
    return (
        <MsalProvider instance={msalInstance}>
            <App />
        </MsalProvider>
    );
}
```

### Making Authenticated API Calls

The auth interceptor automatically handles token attachment:

```javascript
// No manual token handling needed - interceptor handles it
const response = await axios.get('/api/meetings');
const meetings = response.data;
```

### Checking Authentication Status

```jsx
import { useIsAuthenticated } from "@azure/msal-react";

function MyComponent() {
    const isAuthenticated = useIsAuthenticated();
    
    if (!isAuthenticated) {
        return <div>Please log in</div>;
    }
    
    return <div>Welcome to MeetMind!</div>;
}
```

## Configuration

### Environment Setup

Ensure the following are configured:

1. **Azure App Registration**: Create an app registration in Azure Portal
2. **Redirect URIs**: Add your domain to the app registration's redirect URIs
3. **Client ID**: Update `CLIENT_ID` in `msalConfig.js` to match your app registration

### Multi-tenant Configuration

The app is configured for multi-tenant access:

- Authority: `https://login.microsoftonline.com/common`
- Supports organizational and personal Microsoft accounts

## Security Features

### Token Management
- **Automatic Refresh**: Token refresh handled via MSAL
- **Secure Storage**: Tokens stored in localStorage (configurable in [msalConfig.js](#msalconfigjs))
- **Token Type**: Uses ID tokens for API authentication (see [authInterceptor.js](#authinterceptorjs))

### Access Control
- **Protected Routes**: Unauthenticated users see only the login page
- **API Security**: All API calls automatically include bearer tokens via interceptor

### Authentication Flow
- **Public Client**: Uses public client flow (no client secrets exposed)
- **Multi-tenant Support**: Configured for organizational and personal accounts

## Dependencies

Key external dependencies:

- `@azure/msal-browser` - Microsoft Authentication Library
- `@azure/msal-react` - React bindings for MSAL
- `axios` - HTTP client with interceptor support
- `react-router-dom` - Client-side routing

## Error Handling

The authentication system includes:

- Graceful fallback when token acquisition fails
- Automatic retry mechanisms via MSAL
- Console warnings for debugging authentication issues

## Best Practices

1. **Token Usage**: Always use ID tokens for backend API calls (not access tokens)
2. **Error Handling**: Monitor console for authentication warnings
3. **Testing**: Test with different account types (organizational vs. personal)
4. **Security**: Never expose client secrets in frontend code (using public client flow)
5. **Configuration**: Keep sensitive configuration in environment variables where possible

## Related Documentation

- For backend API integration, see the server module documentation
- For deployment configuration, see the deployment guide
- For Azure app registration setup, see the authentication setup guide