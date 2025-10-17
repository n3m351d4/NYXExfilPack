#!/usr/bin/env python3
"""
Скрипт для открытия ВСЕХ портов (1-65535) для EC2 инстансов через Security Groups.
🚨 КРАЙНЕ ОПАСНО! Открывает абсолютно все порты для всех IP адресов!
"""

import boto3
import sys
import os
from datetime import datetime
from botocore.exceptions import ClientError, NoCredentialsError
import logging

def setup_logging(log_file):
    """Настройка логирования в файл и консоль"""
    logger = logging.getLogger('open_access')
    logger.setLevel(logging.INFO)
    
    # Очищаем существующие обработчики
    logger.handlers.clear()
    
    # Обработчик для файла
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    file_formatter = logging.Formatter('%(asctime)s - %(message)s')
    file_handler.setFormatter(file_formatter)
    
    # Обработчик для консоли
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter('%(message)s')
    console_handler.setFormatter(console_formatter)
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

def get_aws_credentials(access_key_short):
    """
    Получает полные AWS credentials из конфигурационного файла.
    ВАЖНО: Замените этот метод на безопасное получение credentials!
    """
    try:
        # Пример: получение из файла с credentials
        # ВАЖНО: Создайте файл credentials.txt с вашими данными в формате:
        # XXXX...|YOUR_SECRET_KEY_HERE
        # XXXX...|YOUR_SECRET_KEY_HERE
        # и т.д.
        
        credentials_file = 'credentials.txt'
        
        if not os.path.exists(credentials_file):
            print(f"❌ Файл credentials не найден: {credentials_file}")
            print("Создайте файл credentials.txt с вашими AWS credentials")
            return None
            
        with open(credentials_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                
                parts = line.split('|')
                if len(parts) >= 2:
                    access_key = parts[0]
                    secret_key = parts[1]
                    
                    if access_key.startswith(access_key_short[:10]):
                        return {
                            'access_key': access_key,
                            'secret_key': secret_key
                        }
        
        print(f"❌ Credentials для {access_key_short} не найдены в файле")
        return None
        
    except Exception as e:
        print(f"❌ Ошибка получения credentials: {e}")
        return None

def open_ports_for_instance(instance_id, region, access_key_short, logger):
    """Открывает необходимые порты для конкретного инстанса"""
    try:
        logger.info(f"\n🔧 Настройка доступа для {instance_id}")
        logger.info(f"   Регион: {region}")
        logger.info(f"   Access Key: {access_key_short}")
        
        # Получаем AWS credentials
        credentials = get_aws_credentials(access_key_short)
        if not credentials:
            logger.error(f"   ❌ {instance_id}: не удалось получить credentials")
            return False
        
        # Создаем клиент EC2
        ec2_client = boto3.client(
            'ec2',
            aws_access_key_id=credentials['access_key'],
            aws_secret_access_key=credentials['secret_key'],
            region_name=region
        )
        
        # Получаем информацию об инстансе
        response = ec2_client.describe_instances(InstanceIds=[instance_id])
        
        if not response['Reservations']:
            logger.error(f"   ❌ {instance_id}: инстанс не найден")
            return False
        
        instance = response['Reservations'][0]['Instances'][0]
        security_groups = instance.get('SecurityGroups', [])
        
        logger.info(f"   🔒 Security Groups: {len(security_groups)}")
        
        # Открываем ВСЕ порты в каждом Security Group
        for sg in security_groups:
            sg_id = sg['GroupId']
            sg_name = sg['GroupName']
            logger.info(f"   🔧 Обновляем {sg_name} ({sg_id})")
            
            # Создаем правило для ВСЕХ портов TCP
            try:
                ec2_client.authorize_security_group_ingress(
                    GroupId=sg_id,
                    IpPermissions=[
                        {
                            'IpProtocol': 'tcp',
                            'FromPort': 1,
                            'ToPort': 65535,
                            'IpRanges': [{'CidrIp': '0.0.0.0/0'}]
                        }
                    ]
                )
                logger.info(f"      ✅ Открыты ВСЕ TCP порты (1-65535)")
            except Exception as e:
                if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
                    logger.info(f"      ⚪ TCP порты уже открыты")
                else:
                    logger.error(f"      ❌ Ошибка TCP портов: {e}")
            
            # Создаем правило для ВСЕХ портов UDP
            try:
                ec2_client.authorize_security_group_ingress(
                    GroupId=sg_id,
                    IpPermissions=[
                        {
                            'IpProtocol': 'udp',
                            'FromPort': 1,
                            'ToPort': 65535,
                            'IpRanges': [{'CidrIp': '0.0.0.0/0'}]
                        }
                    ]
                )
                logger.info(f"      ✅ Открыты ВСЕ UDP порты (1-65535)")
            except Exception as e:
                if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
                    logger.info(f"      ⚪ UDP порты уже открыты")
                else:
                    logger.error(f"      ❌ Ошибка UDP портов: {e}")
            
            # Создаем правило для ICMP
            try:
                ec2_client.authorize_security_group_ingress(
                    GroupId=sg_id,
                    IpPermissions=[
                        {
                            'IpProtocol': 'icmp',
                            'FromPort': -1,
                            'ToPort': -1,
                            'IpRanges': [{'CidrIp': '0.0.0.0/0'}]
                        }
                    ]
                )
                logger.info(f"      ✅ Открыт ICMP (ping)")
            except Exception as e:
                if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
                    logger.info(f"      ⚪ ICMP уже открыт")
                else:
                    logger.error(f"      ❌ Ошибка ICMP: {e}")
        
        logger.info(f"   ✅ {instance_id}: настройка доступа завершена")
        return True
        
    except Exception as e:
        logger.error(f"   ❌ {instance_id}: общая ошибка - {e}")
        return False

def main():
    """Основная функция"""
    log_file = 'access_setup_log.txt'
    
    # Настройка логирования
    logger = setup_logging(log_file)
    
    logger.info("🚨 КРИТИЧЕСКОЕ ПРЕДУПРЕЖДЕНИЕ!")
    logger.info("⚠️  ОТКРЫВАЕМ ВСЕ ПОРТЫ (1-65535) ДЛЯ ВСЕХ IP АДРЕСОВ!")
    logger.info("🔥 ЭТО КРАЙНЕ ОПАСНО И СОЗДАЕТ МАКСИМАЛЬНЫЕ РИСКИ!")
    logger.info("=" * 80)
    
    # Конфигурация инстансов для открытия всех портов
    # ВАЖНО: Замените на ваши реальные данные перед использованием!
    instances_to_process = [
        # Windows инстансы
        {'instance_id': 'i-xxxxxxxxxxxxxxxxx', 'region': 'ap-south-1', 'access_key': 'XXXX...', 'ip': 'X.X.X.X'},
        {'instance_id': 'i-xxxxxxxxxxxxxxxxx', 'region': 'ap-east-1', 'access_key': 'XXXX...', 'ip': 'X.X.X.X'},
        
        # Linux инстансы
        {'instance_id': 'i-xxxxxxxxxxxxxxxxx', 'region': 'us-east-1', 'access_key': 'XXXX...', 'ip': 'X.X.X.X'},
        {'instance_id': 'i-xxxxxxxxxxxxxxxxx', 'region': 'us-east-2', 'access_key': 'XXXX...', 'ip': 'X.X.X.X'},
        {'instance_id': 'i-xxxxxxxxxxxxxxxxx', 'region': 'us-east-2', 'access_key': 'XXXX...', 'ip': 'X.X.X.X'},
        {'instance_id': 'i-xxxxxxxxxxxxxxxxx', 'region': 'ap-south-1', 'access_key': 'XXXX...', 'ip': 'X.X.X.X'},
        {'instance_id': 'i-xxxxxxxxxxxxxxxxx', 'region': 'us-west-2', 'access_key': 'XXXX...', 'ip': 'X.X.X.X'},
        {'instance_id': 'i-xxxxxxxxxxxxxxxxx', 'region': 'eu-north-1', 'access_key': 'XXXX...', 'ip': 'X.X.X.X'},
        {'instance_id': 'i-xxxxxxxxxxxxxxxxx', 'region': 'us-east-1', 'access_key': 'XXXX...', 'ip': 'X.X.X.X'},
        {'instance_id': 'i-xxxxxxxxxxxxxxxxx', 'region': 'us-east-1', 'access_key': 'XXXX...', 'ip': 'X.X.X.X'},
        {'instance_id': 'i-xxxxxxxxxxxxxxxxx', 'region': 'us-east-1', 'access_key': 'XXXX...', 'ip': 'X.X.X.X'},
        {'instance_id': 'i-xxxxxxxxxxxxxxxxx', 'region': 'us-east-1', 'access_key': 'XXXX...', 'ip': 'X.X.X.X'},
        {'instance_id': 'i-xxxxxxxxxxxxxxxxx', 'region': 'us-east-1', 'access_key': 'XXXX...', 'ip': 'X.X.X.X'},
        {'instance_id': 'i-xxxxxxxxxxxxxxxxx', 'region': 'us-east-1', 'access_key': 'XXXX...', 'ip': 'X.X.X.X'},
        {'instance_id': 'i-xxxxxxxxxxxxxxxxx', 'region': 'us-east-1', 'access_key': 'XXXX...', 'ip': 'X.X.X.X'},
        {'instance_id': 'i-xxxxxxxxxxxxxxxxx', 'region': 'us-east-1', 'access_key': 'XXXX...', 'ip': 'X.X.X.X'},
        {'instance_id': 'i-xxxxxxxxxxxxxxxxx', 'region': 'us-east-1', 'access_key': 'XXXX...', 'ip': 'X.X.X.X'},
        {'instance_id': 'i-xxxxxxxxxxxxxxxxx', 'region': 'us-east-1', 'access_key': 'XXXX...', 'ip': 'X.X.X.X'},
        {'instance_id': 'i-xxxxxxxxxxxxxxxxx', 'region': 'us-east-1', 'access_key': 'XXXX...', 'ip': 'X.X.X.X'},
        {'instance_id': 'i-xxxxxxxxxxxxxxxxx', 'region': 'ap-southeast-2', 'access_key': 'XXXX...', 'ip': 'X.X.X.X'},
        {'instance_id': 'i-xxxxxxxxxxxxxxxxx', 'region': 'ap-southeast-2', 'access_key': 'XXXX...', 'ip': 'X.X.X.X'},
        {'instance_id': 'i-xxxxxxxxxxxxxxxxx', 'region': 'ap-southeast-2', 'access_key': 'XXXX...', 'ip': 'X.X.X.X'},
        {'instance_id': 'i-xxxxxxxxxxxxxxxxx', 'region': 'us-east-1', 'access_key': 'XXXX...', 'ip': 'X.X.X.X'},
        {'instance_id': 'i-xxxxxxxxxxxxxxxxx', 'region': 'ap-northeast-1', 'access_key': 'XXXX...', 'ip': 'X.X.X.X'},
        {'instance_id': 'i-xxxxxxxxxxxxxxxxx', 'region': 'us-east-1', 'access_key': 'XXXX...', 'ip': 'X.X.X.X'},
    ]
    
    if not instances_to_process:
        logger.warning("⚠️  Список инстансов пуст. Добавьте инстансы в конфигурацию.")
        return
    
    success_count = 0
    failed_count = 0
    
    for instance in instances_to_process:
        success = open_ports_for_instance(
            instance['instance_id'],
            instance['region'],
            instance['access_key'],
            logger
        )
        
        if success:
            success_count += 1
        else:
            failed_count += 1
    
    logger.info(f"\n✅ Открытие ВСЕХ портов завершено!")
    logger.info(f"📊 Всего инстансов обработано: {len(instances_to_process)}")
    logger.info(f"   ✅ Успешно: {success_count}")
    logger.info(f"   ❌ Ошибки: {failed_count}")
    
    logger.info(f"\n🚨 КРИТИЧЕСКОЕ ПРЕДУПРЕЖДЕНИЕ:")
    logger.info(f"   🔥 ВСЕ ПОРТЫ (1-65535) ОТКРЫТЫ ДЛЯ ВСЕХ IP АДРЕСОВ!")
    logger.info(f"   🔥 TCP: 1-65535")
    logger.info(f"   🔥 UDP: 1-65535")
    logger.info(f"   🔥 ICMP: разрешен")
    logger.info(f"   🔥 CIDR: 0.0.0.0/0 (весь интернет)")
    
    logger.info(f"\n⚠️  НЕМЕДЛЕННЫЕ ДЕЙСТВИЯ:")
    logger.info(f"   1. Ограничьте доступ по IP адресам")
    logger.info(f"   2. Закройте ненужные порты")
    logger.info(f"   3. Используйте VPN для доступа")
    logger.info(f"   4. Настройте мониторинг безопасности")
    logger.info(f"   5. Проверьте логи на подозрительную активность")
    
    logger.info(f"📝 Логи сохранены в: {log_file}")
    logger.info(f"⏰ Время завершения: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

if __name__ == "__main__":
    main()
