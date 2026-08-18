"""Build-time OAuth defaults for the MAIL-AGENT desktop Google client.

Google classifies installed/desktop applications as public clients: a desktop client secret
cannot be kept confidential and may be embedded in the installed application. Runtime
environment variables can still override these defaults for alternate distributions.
"""

GOOGLE_CLIENT_ID = "915083075738-qnu45r3nq0a6qdusgr8bj0tb930a7u6r.apps.googleusercontent.com"
GOOGLE_CLIENT_SECRET = "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"
