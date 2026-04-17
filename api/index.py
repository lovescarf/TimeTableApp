import os
import sys

# Add parent directory to path so we can import kartik_dashboard
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Allow HTTP traffic for OAuth testing
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

from kartik_dashboard import create_app

app = create_app()
