/**
 * Microsoft Entra ID (Azure AD) MSAL configuration for MeetMind.
 * 
 * TENANT_ID and CLIENT_ID come from the App Registration in Azure Portal.
 * The redirectUri must match the one registered in the App Registration.
 */

const CLIENT_ID = "3de8d03b-a1c9-4ad8-8553-604e842eb7ce";

export const msalConfig = {
    auth: {
        clientId: CLIENT_ID,
        // "common" allows multi-tenant + personal Microsoft accounts (live.com, outlook.com, etc.)
        authority: "https://login.microsoftonline.com/common",
        redirectUri: window.location.origin,
        postLogoutRedirectUri: window.location.origin,
        navigateToLoginRequestUrl: true,
    },
    cache: {
        cacheLocation: "localStorage",
        storeAuthStateInCookie: false,
    },
};

export const loginRequest = {
    scopes: ["User.Read"],
};

export const graphConfig = {
    graphMeEndpoint: "https://graph.microsoft.com/v1.0/me",
};
