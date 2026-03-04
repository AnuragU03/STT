/**
 * Singleton MSAL PublicClientApplication instance.
 * Shared across App.jsx (MsalProvider) and the axios interceptor.
 */
import { PublicClientApplication, EventType } from "@azure/msal-browser";
import { msalConfig } from "./msalConfig";

const msalInstance = new PublicClientApplication(msalConfig);

// Handle redirect promise (required for loginRedirect / logoutRedirect flows)
msalInstance.initialize().then(() => {
    msalInstance.handleRedirectPromise().then((response) => {
        if (response?.account) {
            msalInstance.setActiveAccount(response.account);
        } else {
            // Set the first account as active if available (for silent token acquisition)
            const accounts = msalInstance.getAllAccounts();
            if (accounts.length > 0) {
                msalInstance.setActiveAccount(accounts[0]);
            }
        }
    }).catch((error) => {
        console.error("Redirect error:", error);
    });
});

// Listen for login success to set active account
msalInstance.addEventCallback((event) => {
    if (event.eventType === EventType.LOGIN_SUCCESS && event.payload?.account) {
        msalInstance.setActiveAccount(event.payload.account);
    }
});

export default msalInstance;
