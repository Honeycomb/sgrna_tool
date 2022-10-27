from flask import Flask, send_from_directory
from flask_restful import Api
from api.hello import Hello

app = Flask(__name__, static_folder="front-end/build")
api = Api(app)

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")

api.add_resource(Hello, '/hello')