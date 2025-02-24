from flask import Flask
from flask_cors import CORS
import logging

def create_app():
    # Configure logging
    logger = logging.getLogger(__name__)
    
    app = Flask(__name__)
    CORS(app)
    
    from app.routes.main import main
    app.register_blueprint(main)
    
    return app