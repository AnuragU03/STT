/**
 * Custom hook to make authenticated API calls.
 * Automatically attaches the Entra ID Bearer token to every request.
 */
import { useState, useEffect } from "react";
import { useMsal } from "@azure/msal-react";
import { loginRequest } from "./msalConfig";
import axios from "axios";

export function useAuthFetch() {
    const { instance, accounts } = useMsal();

    /**
     * Authenticated fetch wrapper.
     * @param {string} url - API endpoint
     * @param {RequestInit} options - Standard fetch options
     * @returns {Promise<Response>}
     */
    const authFetch = async (url, options = {}) => {
        if (!accounts[0]) {
            throw new Error("No authenticated user");
        }

        try {
            const tokenResponse = await instance.acquireTokenSilent({
                ...loginRequest,
                account: accounts[0],
            });

            return fetch(url, {
                ...options,
                headers: {
                    ...options.headers,
                    Authorization: `Bearer ${tokenResponse.accessToken}`,
                },
            });
        } catch (error) {
            // If silent acquisition fails, force interactive login
            if (error.name === "InteractionRequiredAuthError") {
                await instance.acquireTokenPopup(loginRequest);
                return authFetch(url, options);  // Retry after interactive login
            }
            throw error;
        }
    };

    return authFetch;
}

/**
 * Get the current user's display info from MSAL account + role from backend.
 */
export function useCurrentUser() {
    const { accounts } = useMsal();
    const account = accounts[0];
    const [role, setRole] = useState(null);

    useEffect(() => {
        if (!account) return;
        // Fetch role from backend (interceptor handles auth token)
        axios
            .get("/api/me")
            .then((res) => setRole(res.data.role || "user"))
            .catch(() => setRole("user"));
    }, [account?.username]);

    if (!account) return null;

    return {
        name: account.name || account.username,
        email: account.username,
        initials: (account.name || account.username || "U")
            .split(" ")
            .map((w) => w[0])
            .join("")
            .toUpperCase()
            .slice(0, 2),
        role: role || "user",
        isAdmin: role === "admin" || role === "owner",
    };
}
