import flask
from flask import request
import os
from bot import ObjectDetectionBot
from pymongo import MongoClient


app = flask.Flask(__name__)


try:
    TELEGRAM_TOKEN = os.environ['TELEGRAM_TOKEN']
    TELEGRAM_APP_URL = os.environ['TELEGRAM_APP_URL']
except KeyError as e:
    raise RuntimeError(f"Missing required environment variable: {e}")


@app.route('/', methods=['GET'])
def index():
    return 'Ok'


@app.route(f'/{TELEGRAM_TOKEN}/', methods=['POST'])
def webhook():
    req = request.get_json()
    bot.handle_message(req['message'])
    return 'Ok'

@app.route(f'/results', methods=['POST'])
def results():
    # Connect to MongoDB
    client = MongoClient('mongodb://mongodb.default.svc.cluster.local:27017/?replicaSet=rs0')
    db = client["polybot-info"]
    collection = db["prediction_images"]
    # Function to retrieve only the 'prediction_summary' for a given prediction_id
    def get_prediction_summary(prediction_id):
        document = collection.find_one({"prediction_summary.prediction_id": prediction_id}, {"_id": 0, "prediction_summary": 1})
        return document.get("prediction_summary") if document else None

    # Example usage
    prediction_id = request.args.get('predictionId')
    text_results = get_prediction_summary(prediction_id)
    chat_id = text_results["chat_id"]
    bot.send_text(chat_id, text_results)
    return 'Ok'


@app.route(f'/loadTest/', methods=['POST'])
def load_test():
    req = request.get_json()
    bot.handle_message(req['message'])
    return 'Ok'


if __name__ == "__main__":
    bot = ObjectDetectionBot(TELEGRAM_TOKEN, TELEGRAM_APP_URL)

    app.run(host='0.0.0.0', port=8443)
