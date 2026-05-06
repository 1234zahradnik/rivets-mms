import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-key-change-in-production')
    _db_url = os.environ.get('DATABASE_URL', 'sqlite:///e_maintenance.db')
    # Railway gives postgres:// which SQLAlchemy 2.x requires as postgresql://
    if _db_url.startswith('postgres://'):
        _db_url = _db_url.replace('postgres://', 'postgresql://', 1)
    SQLALCHEMY_DATABASE_URI = _db_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    PER_PAGE = 25
    CSRF_ENABLED = True

class DevelopmentConfig(Config):
    FLASK_DEBUG = True

class ProductionConfig(Config):
    FLASK_DEBUG = False
    SECRET_KEY = os.environ.get('SECRET_KEY')  # must be set in prod

config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}
