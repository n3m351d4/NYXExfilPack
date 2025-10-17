#!/usr/bin/env python3
"""
AWS S3 Bucket Discovery Tool

Этот скрипт проверяет доступные S3 бакеты для предоставленных AWS ключей.
Используется для аудита безопасности и обнаружения доступных ресурсов.

Требования:
- Файл с ключами в формате: access_key|secret_key|account_id|user_path|timestamp
- Установленные библиотеки: boto3, botocore

Автор: Security Team
Версия: 1.0
"""

import boto3
import csv
import json
import time
import os
import sys
from datetime import datetime
from botocore.exceptions import ClientError, NoCredentialsError
import concurrent.futures
import threading
import argparse
import logging

# Глобальная переменная для записи результатов
results_lock = threading.Lock()
results = []
found_buckets_lock = threading.Lock()

def write_found_bucket_to_file(access_key, account_id, user_path, bucket_name, access_level, output_file):
    """Записывает найденный бакет в файл (маскирует чувствительные данные)"""
    with found_buckets_lock:
        with open(output_file, 'a', encoding='utf-8') as f:
            # Маскируем access key для безопасности
            masked_key = access_key[:8] + "..." + access_key[-4:] if len(access_key) > 12 else access_key[:4] + "..."
            f.write(f"{masked_key}|{account_id}|{user_path}|{bucket_name}|{access_level}\n")

def check_s3_buckets(access_key, secret_key, account_id, user_path, timestamp, output_file):
    """Проверяет доступные S3 бакеты для данного ключа"""
    try:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Проверяю ключ: {access_key[:10]}...")
        
        # Создаем сессию AWS
        session = boto3.Session(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key
        )
        
        s3_client = session.client('s3')
        
        # Получаем список бакетов
        response = s3_client.list_buckets()
        buckets = response.get('Buckets', [])
        
        if len(buckets) > 0:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ✓ Найдено {len(buckets)} бакетов для {access_key[:10]}...")
        
        bucket_details = []
        for bucket in buckets:
            bucket_name = bucket['Name']
            creation_date = bucket['CreationDate'].strftime('%Y-%m-%d %H:%M:%S')
            
            # Проверяем права доступа к бакету
            try:
                # Пробуем получить информацию о бакете
                bucket_info = s3_client.head_bucket(Bucket=bucket_name)
                bucket_location = s3_client.get_bucket_location(Bucket=bucket_name)
                location = bucket_location.get('LocationConstraint', 'us-east-1')
                
                # Пробуем получить список объектов (ограничиваем до 5 для проверки доступа)
                try:
                    objects_response = s3_client.list_objects_v2(Bucket=bucket_name, MaxKeys=5)
                    object_count = objects_response.get('KeyCount', 0)
                    has_objects = object_count > 0
                except:
                    has_objects = False
                
                bucket_details.append({
                    'bucket_name': bucket_name,
                    'creation_date': creation_date,
                    'location': location,
                    'has_objects': has_objects,
                    'access_level': 'READ'
                })
                
                # Сразу записываем найденный бакет в файл
                write_found_bucket_to_file(access_key, account_id, user_path, bucket_name, 'READ', output_file)
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ✓ Бакет: {bucket_name} (READ)")
                
            except ClientError as e:
                error_code = e.response['Error']['Code']
                if error_code == '403':
                    bucket_details.append({
                        'bucket_name': bucket_name,
                        'creation_date': creation_date,
                        'location': 'Unknown',
                        'has_objects': False,
                        'access_level': 'DENIED'
                    })
                    write_found_bucket_to_file(access_key, account_id, user_path, bucket_name, 'DENIED', output_file)
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠ Бакет: {bucket_name} (DENIED)")
                else:
                    bucket_details.append({
                        'bucket_name': bucket_name,
                        'creation_date': creation_date,
                        'location': 'Unknown',
                        'has_objects': False,
                        'access_level': f'ERROR: {error_code}'
                    })
                    write_found_bucket_to_file(access_key, account_id, user_path, bucket_name, f'ERROR: {error_code}', output_file)
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] ✗ Бакет: {bucket_name} (ERROR: {error_code})")
        
        result = {
            'access_key': access_key[:8] + "..." + access_key[-4:] if len(access_key) > 12 else access_key[:4] + "...",
            'secret_key': '***MASKED***',  # Полностью скрываем секретный ключ
            'account_id': account_id,
            'user_path': user_path,
            'timestamp': timestamp,
            'status': 'SUCCESS',
            'bucket_count': len(buckets),
            'buckets': bucket_details
        }
        
    except NoCredentialsError:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ✗ Неверные учетные данные: {access_key[:10]}...")
        result = {
            'access_key': access_key[:8] + "..." + access_key[-4:] if len(access_key) > 12 else access_key[:4] + "...",
            'secret_key': '***MASKED***',
            'account_id': account_id,
            'user_path': user_path,
            'timestamp': timestamp,
            'status': 'INVALID_CREDENTIALS',
            'bucket_count': 0,
            'buckets': []
        }
    except ClientError as e:
        error_code = e.response['Error']['Code']
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ✗ Ошибка AWS: {access_key[:10]}... - {error_code}")
        result = {
            'access_key': access_key[:8] + "..." + access_key[-4:] if len(access_key) > 12 else access_key[:4] + "...",
            'secret_key': '***MASKED***',
            'account_id': account_id,
            'user_path': user_path,
            'timestamp': timestamp,
            'status': f'ERROR: {error_code}',
            'bucket_count': 0,
            'buckets': []
        }
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ✗ Неизвестная ошибка: {access_key[:10]}... - {str(e)}")
        result = {
            'access_key': access_key[:8] + "..." + access_key[-4:] if len(access_key) > 12 else access_key[:4] + "...",
            'secret_key': '***MASKED***',
            'account_id': account_id,
            'user_path': user_path,
            'timestamp': timestamp,
            'status': f'UNKNOWN_ERROR: {str(e)}',
            'bucket_count': 0,
            'buckets': []
        }
    
    # Безопасно добавляем результат
    with results_lock:
        results.append(result)
    
    return result

def process_keys_file(filename):
    """Обрабатывает файл с ключами"""
    keys = []
    
    with open(filename, 'r') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
                
            parts = line.split('|')
            if len(parts) >= 5:
                access_key = parts[0]
                secret_key = parts[1]
                account_id = parts[2]
                user_path = parts[3]
                timestamp = parts[4]
                
                keys.append((access_key, secret_key, account_id, user_path, timestamp))
            else:
                print(f"Предупреждение: Строка {line_num} имеет неправильный формат: {line}")
    
    return keys

def setup_logging():
    """Настройка логирования"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('s3_discovery.log'),
            logging.StreamHandler()
        ]
    )

def parse_arguments():
    """Парсинг аргументов командной строки"""
    parser = argparse.ArgumentParser(description='AWS S3 Bucket Discovery Tool')
    parser.add_argument('--keys-file', '-k', 
                       default=os.getenv('KEYS_FILE', './aws_keys.txt'),
                       help='Путь к файлу с AWS ключами')
    parser.add_argument('--output-dir', '-o',
                       default=os.getenv('OUTPUT_DIR', './output'),
                       help='Директория для сохранения результатов')
    parser.add_argument('--max-workers', '-w',
                       type=int, default=10,
                       help='Максимальное количество потоков')
    parser.add_argument('--verbose', '-v',
                       action='store_true',
                       help='Подробный вывод')
    return parser.parse_args()

def main():
    args = parse_arguments()
    setup_logging()
    
    print("=" * 60)
    print("🔍 AWS S3 BUCKET DISCOVERY TOOL")
    print("=" * 60)
    print(f"⏰ Время начала: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Конфигурируемые пути
    output_dir = args.output_dir
    keys_file = args.keys_file
    
    # Создаем директорию для результатов если не существует
    os.makedirs(output_dir, exist_ok=True)
    
    # Создаем файл для найденных бакетов
    timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')
    found_buckets_file = os.path.join(output_dir, f'found_buckets_{timestamp_str}.txt')
    
    # Записываем заголовок в файл
    with open(found_buckets_file, 'w', encoding='utf-8') as f:
        f.write("Access Key|Account ID|User Path|Bucket Name|Access Level\n")
    
    print(f"📁 Файл для найденных бакетов: {found_buckets_file}")
    
    # Читаем ключи из файла
    if not os.path.exists(keys_file):
        print(f"❌ Ошибка: Файл с ключами не найден: {keys_file}")
        print("Создайте файл с ключами в формате: access_key|secret_key|account_id|user_path|timestamp")
        return
    
    keys = process_keys_file(keys_file)
    
    # Используем ThreadPoolExecutor для параллельной обработки
    max_workers = min(args.max_workers, len(keys))  # Ограничиваем количество потоков
    
    print(f"🔑 Найдено {len(keys)} ключей для проверки")
    print(f"⚙️  Используем {max_workers} потоков для параллельной обработки")
    print("-" * 60)
    
    start_time = time.time()
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Запускаем проверку всех ключей
        futures = []
        for access_key, secret_key, account_id, user_path, timestamp in keys:
            future = executor.submit(check_s3_buckets, access_key, secret_key, account_id, user_path, timestamp, found_buckets_file)
            futures.append(future)
        
        # Ждем завершения всех задач
        completed = 0
        for future in concurrent.futures.as_completed(futures):
            completed += 1
            if completed % 10 == 0 or completed == len(keys):
                elapsed = time.time() - start_time
                rate = completed / elapsed if elapsed > 0 else 0
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 📊 Прогресс: {completed}/{len(keys)} ключей ({rate:.1f} ключей/сек)")
    
    elapsed_time = time.time() - start_time
    print("-" * 60)
    print(f"✅ ПРОВЕРКА ЗАВЕРШЕНА!")
    print(f"⏱️  Время выполнения: {elapsed_time:.1f} секунд")
    print(f"📊 Обработано ключей: {len(results)}")
    
    # Статистика
    successful = len([r for r in results if r['status'] == 'SUCCESS'])
    with_buckets = len([r for r in results if r['status'] == 'SUCCESS' and r['bucket_count'] > 0])
    total_buckets = sum([r['bucket_count'] for r in results if r['status'] == 'SUCCESS'])
    
    print(f"\n📈 СТАТИСТИКА:")
    print(f"   🔑 Всего ключей: {len(results)}")
    print(f"   ✅ Успешно проверено: {successful}")
    print(f"   🪣 С доступными бакетами: {with_buckets}")
    print(f"   📦 Всего найдено бакетов: {total_buckets}")
    
    # Проверяем количество найденных бакетов в файле
    try:
        with open(found_buckets_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            found_count = len(lines) - 1  # Минус заголовок
        print(f"   📄 Записано в файл: {found_count} бакетов")
    except:
        print(f"   📄 Не удалось подсчитать записи в файле")
    
    print(f"\n📁 РЕЗУЛЬТАТЫ СОХРАНЕНЫ:")
    print(f"   🪣 Найденные бакеты: {found_buckets_file}")
    
    # Создаем краткий отчет
    summary_filename = os.path.join(output_dir, f's3_check_summary_{timestamp_str}.txt')
    with open(summary_filename, 'w', encoding='utf-8') as f:
        f.write(f"S3 Buckets Check Summary\n")
        f.write(f"========================\n")
        f.write(f"Время проверки: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Время выполнения: {elapsed_time:.1f} секунд\n")
        f.write(f"Всего ключей: {len(results)}\n")
        f.write(f"Успешно проверено: {successful}\n")
        f.write(f"С доступными бакетами: {with_buckets}\n")
        f.write(f"Всего найдено бакетов: {total_buckets}\n\n")
        
        f.write("Ключи с доступными бакетами:\n")
        f.write("=" * 50 + "\n")
        
        for result in results:
            if result['status'] == 'SUCCESS' and result['bucket_count'] > 0:
                f.write(f"Access Key: {result['access_key']}\n")
                f.write(f"Account ID: {result['account_id']}\n")
                f.write(f"User Path: {result['user_path']}\n")
                f.write(f"Buckets ({result['bucket_count']}):\n")
                for bucket in result['buckets']:
                    f.write(f"  - {bucket['bucket_name']} ({bucket['access_level']})\n")
                f.write("\n")
    
    print(f"   📋 Краткий отчет: {summary_filename}")
    print("=" * 60)

if __name__ == "__main__":
    main()
