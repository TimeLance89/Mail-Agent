"""Build-time OAuth defaults for MAIL-AGENT desktop public clients.

Installed desktop applications are public clients. Distribution-specific environment variables
or CI build variables may override these values without changing the runtime OAuth architecture.
"""

GOOGLE_CLIENT_ID = "915083075738-qnu45r3nq0a6qdusgr8bj0tb930a7u6r.apps.googleusercontent.com"
GOOGLE_CLIENT_SECRET = "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"

# MAIL-AGENT must use its own Microsoft Entra public-client application registration.
# Keep this empty until the project registration exists; the UI will expose Microsoft as
# unavailable instead of borrowing another application's identity.
MICROSOFT_CLIENT_ID = ""
