import flask
from flask import request
import os
from bot import ObjectDetectionBot
from pymongo import MongoClient
from loguru import logger


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
    try:
        prediction_id = request.args.get('predictionId')
        logger.info(f"Received request for prediction_id: {prediction_id}")
    except KeyError as e:
        raise RuntimeError(f"Missing required query parameter: {e}")
    
    text_results = get_prediction_summary(prediction_id)
    if text_results:
        # Convert ObjectId to string if exists
        logger.info(f"Results found for prediction_id: {prediction_id}")
        if "_id" in text_results:
            text_results["_id"] = str(text_results["_id"])
        logger.info(f"Results: {text_results}")
        
        # Send the results to the user
        try:
            chat_id = text_results["chat_id"]
            bot.send_text(chat_id, text_results)
            logger.info(f"Results sent to chat_id: {chat_id}")
            return 'Ok'
        except KeyError as e:
            logger.error(f"Missing required field in results: {e}")
    else:
        return 'No results found'

@app.route(f'/loadTest/', methods=['POST'])
def load_test():
    req = request.get_json()
    bot.handle_message(req['message'])
    return 'Ok'


if __name__ == "__main__":
    bot = ObjectDetectionBot(TELEGRAM_TOKEN, TELEGRAM_APP_URL)

    app.run(host='0.0.0.0', port=8443)
