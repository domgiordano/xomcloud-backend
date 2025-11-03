from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import requests
import yt_dlp
import os
import zipfile
from datetime import datetime
import tempfile
import shutil

app = Flask(__name__)
CORS(app)

# SoundCloud API Configuration
SOUNDCLOUD_CLIENT_ID = os.environ.get('SOUNDCLOUD_CLIENT_ID')
SOUNDCLOUD_CLIENT_SECRET = os.environ.get('SOUNDCLOUD_CLIENT_SECRET')
SOUNDCLOUD_REDIRECT_URI = 'http://localhost:3000/callback'

@app.route('/api/auth/url', methods=['GET'])
def get_auth_url():
    """Generate SoundCloud OAuth URL"""
    auth_url = f"https://soundcloud.com/connect?client_id={SOUNDCLOUD_CLIENT_ID}&redirect_uri={SOUNDCLOUD_REDIRECT_URI}&response_type=code&scope=non-expiring"
    return jsonify({'url': auth_url})

@app.route('/api/auth/token', methods=['POST'])
def exchange_token():
    """Exchange authorization code for access token"""
    data = request.json
    code = data.get('code')
    
    response = requests.post('https://api.soundcloud.com/oauth2/token', data={
        'client_id': SOUNDCLOUD_CLIENT_ID,
        'client_secret': SOUNDCLOUD_CLIENT_SECRET,
        'redirect_uri': SOUNDCLOUD_REDIRECT_URI,
        'grant_type': 'authorization_code',
        'code': code
    })
    
    return jsonify(response.json())

@app.route('/api/user/me', methods=['GET'])
def get_user():
    """Get current user info"""
    token = request.headers.get('Authorization').replace('Bearer ', '')
    
    response = requests.get(
        'https://api.soundcloud.com/me',
        headers={'Authorization': f'OAuth {token}'}
    )
    
    return jsonify(response.json())

@app.route('/api/user/likes', methods=['GET'])
def get_likes():
    """Get user's liked tracks"""
    token = request.headers.get('Authorization').replace('Bearer ', '')
    
    response = requests.get(
        'https://api.soundcloud.com/me/favorites',
        headers={'Authorization': f'OAuth {token}'},
        params={'limit': 200}
    )
    
    return jsonify(response.json())

@app.route('/api/user/playlists', methods=['GET'])
def get_playlists():
    """Get user's playlists"""
    token = request.headers.get('Authorization').replace('Bearer ', '')
    
    response = requests.get(
        'https://api.soundcloud.com/me/playlists',
        headers={'Authorization': f'OAuth {token}'}
    )
    
    return jsonify(response.json())

@app.route('/api/playlist/<playlist_id>', methods=['GET'])
def get_playlist_tracks(playlist_id):
    """Get tracks from a specific playlist"""
    token = request.headers.get('Authorization').replace('Bearer ', '')
    
    response = requests.get(
        f'https://api.soundcloud.com/playlists/{playlist_id}',
        headers={'Authorization': f'OAuth {token}'}
    )
    
    return jsonify(response.json())

@app.route('/api/download', methods=['POST'])
def download_tracks():
    """Download selected tracks and return as zip"""
    data = request.json
    track_urls = data.get('urls', [])
    
    if not track_urls:
        return jsonify({'error': 'No tracks provided'}), 400
    
    # Create temporary directory for downloads
    temp_dir = tempfile.mkdtemp()
    
    try:
        # Configure yt-dlp options
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '320',
            }],
            'quiet': True,
            'no_warnings': True,
        }
        
        # Download all tracks
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            for url in track_urls:
                try:
                    ydl.download([url])
                except Exception as e:
                    print(f"Error downloading {url}: {str(e)}")
        
        # Create zip file
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        zip_filename = f'xomcloud_download_{timestamp}.zip'
        zip_path = os.path.join(tempfile.gettempdir(), zip_filename)
        
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(temp_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    zipf.write(file_path, file)
        
        # Clean up temp directory
        shutil.rmtree(temp_dir)
        
        return send_file(
            zip_path,
            mimetype='application/zip',
            as_attachment=True,
            download_name=zip_filename
        )
        
    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    app.run(debug=True, port=5000)