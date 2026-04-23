from backend.app import app
import os

if __name__ == '__main__':
    port = int(os.getenv('PORT', '5000'))
    debug = os.getenv('FLASK_DEBUG') == '1'
    app.run(host='0.0.0.0', debug=debug, port=port)
