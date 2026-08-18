"""Build-time OAuth defaults.

Release builds may replace GOOGLE_CLIENT_ID before packaging. Runtime environment variables always
win, so developers can test without rebuilding the application.
"""

GOOGLE_CLIENT_ID = ""
