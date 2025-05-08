import os

class Config:
    MONGO_URI = os.getenv('MONGO_URI', "mongodb+srv://sudharson:sudharson@sudharcluster.imomdcz.mongodb.net/url-shortener?retryWrites=true&w=majority&appName=sudharcluster")
    REDIS_HOST = os.getenv('REDIS_HOST', 'redis')
    REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
    BASE_URL = os.getenv('BASE_URL', 'http://localhost:5000')
    FRONTEND_URL = os.getenv('FRONTEND_URL', 'http://localhost:8501')