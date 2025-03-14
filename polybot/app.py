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
        document = collection.find_one({"prediction_id": prediction_id}, {"_id": 0})
        if document and "_id" in document:
            document["_id"] = str(document["_id"])
        return document
        

    # Example usage
    try:
        prediction_id = request.args.get('predictionId')
        logger.info(f"Received request for prediction_id: {prediction_id}")
    except KeyError as e:
        raise RuntimeError(f"Missing required query parameter: {e}")
    
    document = get_prediction_summary(prediction_id)
    if document:
        logger.info(f"Results found for prediction_id: {prediction_id}")
        # Get chat_id from the document
        try:
            chat_id = document["chat_id"]
            # Send the results to the user
            bot.send_text(chat_id, document)  # Pass the entire document or format as needed
            logger.info(f"Results sent to chat_id: {chat_id}")
            return 'Ok'
        except KeyError as e:
            logger.error(f"Missing chat_id in document: {e}")
            return 'Error: chat_id not found in document'
    else:
        logger.error(f"No results found for prediction_id: {prediction_id}")
        return 'No results found'

@app.route(f'/loadTest/', methods=['POST'])
def load_test():
    req = request.get_json()
    bot.handle_message(req['message'])
    return 'Ok'


if __name__ == "__main__":
    bot = ObjectDetectionBot(TELEGRAM_TOKEN, TELEGRAM_APP_URL)

    app.run(host='0.0.0.0', port=8443)
