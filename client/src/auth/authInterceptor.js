/**
 * Axios interceptor that automatically attaches the Entra ID Bearer token
 * to every outgoing API request. No per-component changes needed.
 *
 * IMPORTANT: We send the **ID token** (not access token) because:
 * - accessToken with scopes=["User.Read"] is issued for Microsoft Graph (aud=graph.microsoft.com)
 * - idToken is issued for OUR app (aud=CLIENT_ID) — which is what our backend validates
 */
import axios from "axios";
import msalInstance from "./msalInstance";
import { loginRequest } from "./msalConfig";

axios.interceptors.request.use(async (config) => {
    const account = msalInstance.getActiveAccount();
    if (!account) return config;           // No user logged in — pass through

    try {
        const tokenResponse = await msalInstance.acquireTokenSilent({
            ...loginRequest,
            account,
        });
        // Use idToken — its audience matches our CLIENT_ID
        config.headers.Authorization = `Bearer ${tokenResponse.idToken}`;
    } catch (err) {
        // If silent fails, let the request go without a token —
        // the AuthenticatedTemplate in App.jsx ensures we are logged in,
        // so this is a rare edge case that the MSAL event callback will handle.
        console.warn("[Auth] Silent token acquisition failed:", err.message);
    }

    return config;
});
