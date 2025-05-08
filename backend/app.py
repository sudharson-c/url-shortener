from flask import Flask, request, jsonify, redirect
from pymongo import MongoClient
import redis
import hashlib
import os
from datetime import datetime
from config import Config
from bson import ObjectId
import re
import logging
import validators
from bcrypt import hashpw, gensalt, checkpw
from time import sleep

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# MongoDB connection
try:
    if not Config.MONGO_URI:
        raise ValueError("MONGO_URI is not set")
    mongo = MongoClient(Config.MONGO_URI)
    db = mongo.url_shortener
except Exception as e:
    logger.error(f"Failed to connect to MongoDB: {str(e)}")
    raise

# Redis connection with retry logic
def connect_redis():
    for _ in range(3):
        try:
            client = redis.Redis(host=Config.REDIS_HOST, port=Config.REDIS_PORT, decode_responses=True)
            client.ping()
            return client
        except redis.ConnectionError as e:
            logger.warning(f"Redis connection attempt failed: {str(e)}")
            sleep(1)
    raise redis.ConnectionError("Failed to connect to Redis")

redis_client = connect_redis()

def generate_short_url(url):
    hash_object = hashlib.md5(url.encode())
    return hash_object.hexdigest()[:8]

def is_valid_alias(alias):
    return bool(re.match("^[a-zA-Z0-9-]+$", alias))

@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    
    if not username or not password:
        return jsonify({'error': 'Username and password required', 'code': 'MISSING_FIELDS'}), 400
    
    if db.users.find_one({'username': username}):
        return jsonify({'error': 'Username already exists', 'code': 'USERNAME_EXISTS'}), 400
    
    try:
        password_hash = hashpw(password.encode(), gensalt()).decode()
        db.users.insert_one({
            'username': username,
            'password': password_hash,
            'created_at': datetime.utcnow()
        })
        logger.info(f"User registered: {username}")
        return jsonify({'message': 'User registered successfully'}), 201
    except Exception as e:
        logger.error(f"Registration failed: {str(e)}")
        return jsonify({'error': f'Registration failed: {str(e)}', 'code': 'DB_ERROR'}), 500

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    
    user = db.users.find_one({'username': username})
    if user and checkpw(password.encode(), user['password'].encode()):
        logger.info(f"User logged in: {username}")
        return jsonify({'message': 'Login successful', 'user_id': str(user['_id'])})
    logger.warning(f"Invalid login attempt for: {username}")
    return jsonify({'error': 'Invalid credentials', 'code': 'INVALID_CREDENTIALS'}), 401

@app.route('/shorten', methods=['POST'])
def shorten_url():
    data = request.get_json()
    original_url = data.get('url')
    user_id = data.get('user_id')
    custom_alias = data.get('custom_alias')
    frontend_base_url = data.get('frontend_base_url', Config.FRONTEND_URL)
    
    if not original_url:
        return jsonify({'error': 'URL is required', 'code': 'MISSING_URL'}), 400
    
    # Validate URL
    if not validators.url(original_url):
        return jsonify({'error': 'Invalid URL', 'code': 'INVALID_URL'}), 400
    
    # Normalize URL
    if not original_url.startswith(('http://', 'https://')):
        original_url = 'http://' + original_url
    
    # Handle custom alias
    if custom_alias:
        if not is_valid_alias(custom_alias):
            return jsonify({'error': 'Custom alias can only contain letters, numbers, hyphens', 'code': 'INVALID_ALIAS'}), 400
        if len(custom_alias) < 4 or len(custom_alias) > 20:
            return jsonify({'error': 'Custom alias must be between 4 and 20 characters', 'code': 'INVALID_ALIAS_LENGTH'}), 400
        if db.urls.find_one({'short_url': custom_alias}):
            return jsonify({'error': 'This custom alias is already taken', 'code': 'ALIAS_TAKEN'}), 400
        short_url = custom_alias
    else:
        short_url = generate_short_url(original_url)
        while db.urls.find_one({'short_url': short_url}):
            short_url = generate_short_url(original_url + str(os.urandom(4)))
    
    url_data = {
        'original_url': original_url,
        'short_url': short_url,
        'created_at': datetime.utcnow(),
        'user_id': ObjectId(user_id) if user_id else None,
        'is_custom': bool(custom_alias)
    }
    
    try:
        result = db.urls.insert_one(url_data)
        cache_key = f"url:{original_url}:{user_id}" if user_id else f"url:{original_url}"
        redis_client.setex(cache_key, 3600, short_url)
        shortened_url = f"{frontend_base_url}/{short_url}"
        logger.info(f"URL shortened: {original_url} -> {shortened_url}")
        return jsonify({
            'short_url': shortened_url,
            'original_url': original_url,
            'id': str(result.inserted_id)
        }), 200
    except Exception as e:
        logger.error(f"Failed to shorten URL: {str(e)}")
        return jsonify({'error': f'Failed to create shortened URL: {str(e)}', 'code': 'DB_ERROR'}), 500

@app.route('/<short_url>', methods=['GET'])
def redirect_url(short_url):
    cached_original = redis_client.get(f"short:{short_url}")
    if cached_original:
        db.clicks.insert_one({
            'short_url': short_url,
            'timestamp': datetime.utcnow(),
            'user_agent': request.headers.get('User-Agent'),
            'ip_address': request.remote_addr
        })
        logger.info(f"Redirecting cached URL: {short_url}")
        return redirect(cached_original)
    
    url_data = db.urls.find_one({'short_url': short_url})
    if url_data:
        redis_client.setex(f"short:{short_url}", 3600, url_data['original_url'])
        db.clicks.insert_one({
            'short_url': short_url,
            'timestamp': datetime.utcnow(),
            'user_agent': request.headers.get('User-Agent'),
            'ip_address': request.remote_addr
        })
        logger.info(f"Redirecting URL: {short_url} -> {url_data['original_url']}")
        return redirect(url_data['original_url'])
    
    logger.warning(f"URL not found: {short_url}")
    return jsonify({'error': 'URL not found', 'code': 'NOT_FOUND'}), 404

@app.route('/analytics/<short_url>', methods=['GET'])
def get_analytics(short_url):
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({'error': 'User ID required', 'code': 'MISSING_USER_ID'}), 400
    
    url_data = db.urls.find_one({'short_url': short_url, 'user_id': ObjectId(user_id)})
    if not url_data:
        return jsonify({'error': 'URL not found or unauthorized', 'code': 'NOT_FOUND'}), 404
    
    clicks = list(db.clicks.find({'short_url': short_url}))
    total_clicks = len(clicks)
    logger.info(f"Retrieved analytics for: {short_url}")
    return jsonify({
        'short_url': short_url,
        'total_clicks': total_clicks,
        'clicks': [{'timestamp': str(c['timestamp']), 'user_agent': c['user_agent']} for c in clicks]
    })

@app.route('/health', methods=['GET'])
def health_check():
    try:
        mongo.admin.command('ping')
        redis_client.ping()
        url_count = db.urls.count_documents({})
        logger.info("Health check passed")
        return jsonify({
            'status': 'healthy',
            'mongo': 'connected',
            'redis': 'connected',
            'url_count': url_count
        }), 200
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return jsonify({'status': 'unhealthy', 'error': str(e)}), 500

@app.route('/urls', methods=['GET'])
def get_user_urls():
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({'error': 'User ID is required', 'code': 'MISSING_USER_ID'}), 400
    
    try:
        urls = list(db.urls.find({'user_id': ObjectId(user_id)}).sort('created_at', -1))
        for url in urls:
            url['_id'] = str(url['_id'])
            url['user_id'] = str(url['user_id'])
            url['full_short_url'] = f"{Config.BASE_URL}/{url['short_url']}"
        logger.info(f"Retrieved URLs for user: {user_id}")
        return jsonify({'urls': urls})
    except Exception as e:
        logger.error(f"Failed to retrieve URLs: {str(e)}")
        return jsonify({'error': str(e), 'code': 'DB_ERROR'}), 500

@app.route('/urls/<url_id>', methods=['DELETE'])
def delete_url(url_id):
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({'error': 'User ID is required', 'code': 'MISSING_USER_ID'}), 400
    
    try:
        url_data = db.urls.find_one({
            '_id': ObjectId(url_id),
            'user_id': ObjectId(user_id)
        })
        
        if url_data:
            redis_client.delete(f"url:{url_data['original_url']}:{user_id}")
            redis_client.delete(f"short:{url_data['short_url']}")
            result = db.urls.delete_one({
                '_id': ObjectId(url_id),
                'user_id': ObjectId(user_id)
            })
            
            if result.deleted_count:
                logger.info(f"Deleted URL: {url_id}")
                return jsonify({'message': 'URL deleted successfully'})
        
        logger.warning(f"URL deletion failed: {url_id}")
        return jsonify({'error': 'URL not found or unauthorized', 'code': 'NOT_FOUND'}), 404
    except Exception as e:
        logger.error(f"Failed to delete URL: {str(e)}")
        return jsonify({'error': str(e), 'code': 'DB_ERROR'}), 500

@app.route('/urls/<url_id>', methods=['PUT'])
def update_url(url_id):
    user_id = request.args.get('user_id')
    data = request.get_json()
    custom_alias = data.get('custom_alias')
    
    if not user_id:
        return jsonify({'error': 'User ID is required', 'code': 'MISSING_USER_ID'}), 400
    
    try:
        if custom_alias:
            if db.urls.find_one({'short_url': custom_alias, '_id': {'$ne': ObjectId(url_id)}}):
                return jsonify({'error': 'Custom alias already taken', 'code': 'ALIAS_TAKEN'}), 400
        
        update_data = {}
        if custom_alias:
            update_data['short_url'] = custom_alias
        
        if update_data:
            result = db.urls.update_one(
                {
                    '_id': ObjectId(url_id),
                    'user_id': ObjectId(user_id)
                },
                {'$set': update_data}
            )
            
            if result.modified_count:
                logger.info(f"Updated URL: {url_id}")
                return jsonify({'message': 'URL updated successfully'})
            return jsonify({'error': 'URL not found or unauthorized', 'code': 'NOT_FOUND'}), 404
        
        return jsonify({'error': 'No updates provided', 'code': 'NO_CHANGES'}), 400
    except Exception as e:
        logger.error(f"Failed to update URL: {str(e)}")
        return jsonify({'error': str(e), 'code': 'DB_ERROR'}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)