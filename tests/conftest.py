# tests/conftest.py
import os

# Set CORS_ORIGINS for testing so CORSMiddleware is initialized correctly
os.environ["CORS_ORIGINS"] = '["http://example.com"]'
