import telebot
from loguru import logger
import os
import time
from telebot.types import InputFile
import boto3
from botocore.exceptions import NoCredentialsError
import requests
import json

try:
    BUCKET_NAME = os.environ['BUCKET_NAME']
    SQS_URL = os.environ['SQS_URL']
except KeyError as e:
    raise RuntimeError(f"Missing required environment variable: {e}")

class Bot:

    def __init__(self, token, telegram_chat_url):
        # create a new instance of the TeleBot class.
        # all communication with Telegram servers are done using self.telegram_bot_client
        self.telegram_bot_client = telebot.TeleBot(token)
        # remove any existing webhooks configured in Telegram servers
        self.telegram_bot_client.remove_webhook()
        time.sleep(0.5)
        # set the webhook URL
        self.telegram_bot_client.set_webhook(url=f'{telegram_chat_url}/{token}/', timeout=60)
        logger.info(f'Telegram Bot information\n\n{self.telegram_bot_client.get_me()}')

    def send_text(self, chat_id, text):
        self.telegram_bot_client.send_message(chat_id, text)

    def send_text_with_quote(self, chat_id, text, quoted_msg_id):
        self.telegram_bot_client.send_message(chat_id, text, reply_to_message_id=quoted_msg_id)

    def is_current_msg_photo(self, msg):
        return 'photo' in msg

    def download_user_photo(self, msg):
        """
        Downloads the photos that sent to the Bot to `photos` directory (should be existed)
        :return:
        """
        if not self.is_current_msg_photo(msg):
            raise RuntimeError(f'Message content of type \'photo\' expected')

        file_info = self.telegram_bot_client.get_file(msg['photo'][-1]['file_id'])
        data = self.telegram_bot_client.download_file(file_info.file_path)
        folder_name = file_info.file_path.split('/')[0]

        if not os.path.exists(folder_name):
            os.makedirs(folder_name)

        with open(file_info.file_path, 'wb') as photo:
            photo.write(data)

        return file_info.file_path

    def send_photo(self, chat_id, img_path):
        if not os.path.exists(img_path):
            raise RuntimeError("Image path doesn't exist")

        self.telegram_bot_client.send_photo(
            chat_id,
            InputFile(img_path)
        )

    def handle_photo_message(self, msg):
        chat_id = msg['chat']['id']
        photo_path = self.download_user_photo(msg)
        # upload the image to S3 Bucket ofekh-polybotservicedocker-project
        s3 = boto3.client('s3')
        bucket_name = BUCKET_NAME
        s3_image_key_upload = f'{chat_id}_teleBOT_picture.jpg'
        try:
            # Upload predicted image back to S3
            s3.upload_file(str(photo_path), bucket_name, s3_image_key_upload)
            logger.info(f"File uploaded successfully to {bucket_name}/{s3_image_key_upload}")
        except FileNotFoundError:
            logger.error("The file was not found.")
            return "Predicted image not found", 404
        except NoCredentialsError:
            logger.error("AWS credentials not available.")
            return "AWS credentials not available", 403
        except Exception as e:
            logger.error(f"Error uploading file: {e}")
            return f"Error uploading file: {e}", 500
        
        # send an HTTP request to the `SQS` service for prediction
        params = {"imgName": s3_image_key_upload}
        sqs_client = boto3.client('sqs', region_name='eu-north-1')
        try:
            response = sqs_client.send_message(
                QueueUrl=str(SQS_URL),
                MessageBody=json.dumps(params)
            )
            logger.info(f"Message sent to SQS. Message ID: {response['MessageId']}")
        except Exception as e:
            logger.error(f"Error sending message to SQS: {e}")
            return f"Error sending message to SQS: {e}", 500
        
        time.sleep(5)  # Wait for the prediction to complete
        s3_image_key_download = f'predictions/{chat_id}_picture.jpg'
        original_img_path = f'/tmp/image.jpg'  # Temporary storage for downloaded image
        try:
            # Download predicted image from S3
            s3.download_file(bucket_name, s3_image_key_download, original_img_path)
            logger.info(f'Downloaded prediction image completed from {bucket_name}/{s3_image_key_download}')
            # send photo results to the Telegram end-user
            self.send_photo(chat_id, original_img_path)
        except FileNotFoundError:
            logger.error("The file was not found.")
            return "Predicted image not found", 404
        except NoCredentialsError:
            logger.error("AWS credentials not available.")
            return "AWS credentials not available", 403
        except Exception as e:
            logger.error(f"Error downloading file: {e}")
            return f"Error downloading file: {e}", 500

    
    def handle_message(self, msg):
        """Bot Main message handler"""
        logger.info(f'Incoming message: {msg}')
        if 'text' in msg:
            self.send_text(msg['chat']['id'], f'Your original message: {msg["text"]}')
        elif self.is_current_msg_photo(msg):
            self.handle_photo_message(msg)
        else:
            self.send_text(msg['chat']['id'], "Unsupported message type")
        

class ObjectDetectionBot(Bot):
    def handle_message(self, msg):
        logger.info(f'Incoming message: {msg}')

        if self.is_current_msg_photo(msg):
            self.handle_photo_message(msg)

            
            # TODO send message to the Telegram end-user (e.g. Your image is being processed. Please wait...)
