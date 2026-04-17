from kartik_dashboard import create_app
import os

# Add this line to allow HTTP traffic for local OAuth testing
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
app = create_app()


if __name__ == "__main__":
    app.run(debug=True)