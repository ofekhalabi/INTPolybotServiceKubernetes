import time
from pathlib import Path
from flask import Flask, request
from detect import run
import uuid
from pymongo import MongoClient
import yaml
import boto3
from botocore.exceptions import NoCredentialsError
from loguru import logger
import os
import json

BUCKET_NAME = os.environ['BUCKET_NAME']
SQS_URL = os.environ['SQS_URL']

sqs_client = boto3.client('sqs', region_name='eu-north-1')

with open("data/coco128.yaml", "r") as stream:
    names = yaml.safe_load(stream)['names']


def consume():
    while True:
        response = sqs_client.receive_message(QueueUrl=SQS_URL, MaxNumberOfMessages=1, WaitTimeSeconds=5)

        if 'Messages' in response:
            message = response['Messages'][0]['Body']
            # You must use this ReceiptHandle to delete the message after processing it, preventing it from being processed again.
            receipt_handle = response['Messages'][0]['ReceiptHandle']

            # Use the ReceiptHandle as a prediction UUID
            prediction_id = response['Messages'][0]['MessageId']

            logger.info(f'prediction: {prediction_id}. start processing')

            # Extract the message from the SQS message and CHAT_ID
            message = json.loads(message)
            img_name = message["imgName"]
            chat_id = img_name.split("_")[0]
            original_img_path = f'/tmp/{chat_id}_{img_name}'  # Temporary storage for downloaded image
            
            # Initialize the S3 client
            s3_client = boto3.client('s3')
            # Download the image from S3 that polybot has uploaded
            try:
                # Download the file from S3
                s3_client.download_file(BUCKET_NAME, img_name, original_img_path)
                logger.info(f'prediction: {prediction_id}. Downloaded {img_name} to {original_img_path}')
                logger.info(f'prediction: {prediction_id}/{original_img_path}. Download img completed')
            except Exception as e:
                logger.error(f'Error downloading {img_name}: {e}')

            # Predicts the objects in the image
            run(
                weights='yolov5s.pt',
                data='data/coco128.yaml',
                source=original_img_path,
                project='static/data',
                name=prediction_id,
                save_txt=True
            )

            logger.info(f'prediction: {prediction_id}/{original_img_path}. done')

            # This is the path for the predicted image with labels
            # The predicted image typically includes bounding boxes drawn around the detected objects, along with class labels and possibly confidence scores.
            predicted_img_path = f'static/data/{prediction_id}/{original_img_path}'

            # predict the image and upload it to S3
            s3_image_key_upload = f'predictions/{chat_id}_picture.jpg'
            try:
                # Upload predicted image back to S3
                s3_client.upload_file(predicted_img_path, BUCKET_NAME, s3_image_key_upload)
                logger.info(f"File uploaded successfully to {BUCKET_NAME}/{s3_image_key_upload}")
            except FileNotFoundError:
                logger.error("The file was not found.")
                return "Predicted image not found", 404
            except NoCredentialsError:
                logger.error("AWS credentials not available to S3.")
                return "AWS credentials not available to S3", 403
            except Exception as e:
                logger.error(f"Error uploading file: {e}")
                return f"Error uploading file: {e}", 500

            # Parse prediction labels and create a summary
            pred_summary_path = Path(f'static/data/{prediction_id}/labels/{original_img_path.split(".")[0]}.txt')
            if pred_summary_path.exists():
                with open(pred_summary_path) as f:
                    labels = f.read().splitlines()
                    labels = [line.split(' ') for line in labels]
                    labels = [{
                        'class': names[int(l[0])],
                        'cx': float(l[1]),
                        'cy': float(l[2]),
                        'width': float(l[3]),
                        'height': float(l[4]),
                    } for l in labels]

                logger.info(f'prediction: {prediction_id}/{original_img_path}. prediction summary:\n\n{labels}')

                prediction_summary = {
                    'prediction_id': prediction_id,
                    'original_img_path': original_img_path,
                    'predicted_img_path': predicted_img_path,
                    'labels': labels,
                    'time': time.time()
                }

                # Connect to MongoDB
                MongoClient = MongoClient('mongodb://mongodb-0:27017,mongodb-1:27017,mongodb-2:27017/?replicaSet=myReplicaSet')
                # Select the database (polybot-info) and collection (prediction_images)
                db = MongoClient['polybot-info']
                collection = db['prediction_images']
                # Insert the prediction_summary into MongoDB
                collection.insert_one(prediction_summary)
                print("Prediction summary inserted successfully.")
                if "_id" in prediction_summary:
                    prediction_summary["_id"] = str(prediction_summary["_id"])
                
                # Delete the message from the queue as the job is considered as DONE
                sqs_client.delete_message(QueueUrl=SQS_URL, ReceiptHandle=receipt_handle)
                
                return prediction_summary
                # TODO perform a GET request to Polybot to `/results` endpoint
            else:
                # Delete the message from the queue as the job is considered as DONE
                sqs_client.delete_message(QueueUrl=SQS_URL, ReceiptHandle=receipt_handle)
                logger.error(f'prediction: {prediction_id}/{original_img_path}. prediction result not found')
                return f'prediction: {prediction_id}/{original_img_path}. prediction result not found', 404
            


if __name__ == "__main__":
    consume()
