from flask_restful import Api, Resource

class Hello(Resource):
    def get(self):
        return {
            "message": "Hello, World!"
        }