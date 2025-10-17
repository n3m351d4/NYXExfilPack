#!/usr/bin/env python3
"""
Enhanced EC2 instance discovery script with progress bar and logging
"""

import boto3
import csv
import sys
from datetime import datetime
from botocore.exceptions import ClientError, NoCredentialsError
import concurrent.futures
import threading
import logging
import os

# List of all AWS regions
AWS_REGIONS = [
    'us-east-1', 'us-east-2', 'us-west-1', 'us-west-2',
    'eu-west-1', 'eu-west-2', 'eu-west-3', 'eu-central-1', 'eu-north-1',
    'ap-southeast-1', 'ap-southeast-2', 'ap-northeast-1', 'ap-northeast-2', 'ap-south-1',
    'ca-central-1', 'sa-east-1', 'af-south-1', 'ap-east-1', 'me-south-1',
    'eu-south-1', 'ap-southeast-3', 'ap-northeast-3', 'us-gov-east-1', 'us-gov-west-1'
]

# Thread-safe file writing
file_lock = threading.Lock()
log_lock = threading.Lock()

def setup_logging(log_file):
    """Setup logging to file and console"""
    logger = logging.getLogger('ec2_checker')
    logger.setLevel(logging.INFO)
    
    # Clear existing handlers
    logger.handlers.clear()
    
    # File handler
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    file_formatter = logging.Formatter('%(asctime)s - %(message)s')
    file_handler.setFormatter(file_formatter)
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter('%(message)s')
    console_handler.setFormatter(console_formatter)
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

def print_progress(current, total, prefix="Progress"):
    """Print progress bar"""
    percent = (current / total) * 100
    bar_length = 50
    filled_length = int(bar_length * current // total)
    bar = '█' * filled_length + '-' * (bar_length - filled_length)
    print(f'\r{prefix}: |{bar}| {current}/{total} ({percent:.1f}%)', end='', flush=True)

def check_ec2_in_region(access_key, secret_key, region, account_id, user_info):
    """Check for EC2 instances in a specific region"""
    try:
        # Create EC2 client for specific region
        ec2_client = boto3.client(
            'ec2',
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region
        )
        
        # Get list of all instances (including stopped ones)
        response = ec2_client.describe_instances()
        
        instances = []
        for reservation in response['Reservations']:
            for instance in reservation['Instances']:
                instances.append({
                    'InstanceId': instance['InstanceId'],
                    'State': instance['State']['Name'],
                    'InstanceType': instance['InstanceType'],
                    'LaunchTime': instance['LaunchTime'].strftime('%Y-%m-%d %H:%M:%S'),
                    'Tags': {tag['Key']: tag['Value'] for tag in instance.get('Tags', [])}
                })
        
        return {
            'region': region,
            'instances': instances,
            'account_id': account_id,
            'user_info': user_info,
            'access_key': access_key[:10] + '...'  # Show only first 10 characters
        }
        
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code in ['UnauthorizedOperation', 'AccessDenied']:
            return {
                'region': region,
                'instances': [],
                'account_id': account_id,
                'user_info': user_info,
                'access_key': access_key[:10] + '...',
                'error': f'Access denied: {error_code}'
            }
        else:
            return {
                'region': region,
                'instances': [],
                'account_id': account_id,
                'user_info': user_info,
                'access_key': access_key[:10] + '...',
                'error': f'Error: {error_code}'
            }
    except Exception as e:
        return {
            'region': region,
            'instances': [],
            'account_id': account_id,
            'user_info': user_info,
            'access_key': access_key[:10] + '...',
            'error': f'Unexpected error: {str(e)}'
        }

def process_account(access_key, secret_key, account_id, user_info, logger, current_account, total_accounts):
    """Process one account - check all regions"""
    logger.info(f"\n🔍 [{current_account}/{total_accounts}] Checking account {account_id} ({user_info})")
    logger.info(f"   Access Key: {access_key[:10]}...")
    
    # Use ThreadPoolExecutor for parallel region checking
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        # Create tasks for all regions
        future_to_region = {
            executor.submit(check_ec2_in_region, access_key, secret_key, region, account_id, user_info): region
            for region in AWS_REGIONS
        }
        
        # Collect results
        regions_with_instances = []
        regions_checked = 0
        
        for future in concurrent.futures.as_completed(future_to_region):
            region = future_to_region[future]
            regions_checked += 1
            
            try:
                result = future.result()
                
                if result['instances']:
                    regions_with_instances.append(result)
                    logger.info(f"   ✅ {region}: {len(result['instances'])} instances")
                    
                    # Output instance details to console and file
                    for instance in result['instances']:
                        logger.info(f"      - {instance['InstanceId']} ({instance['State']}) - {instance['InstanceType']}")
                elif 'error' in result:
                    logger.info(f"   ❌ {region}: {result['error']}")
                else:
                    logger.info(f"   ⚪ {region}: no instances")
                    
            except Exception as exc:
                logger.info(f"   ❌ {region}: execution error - {exc}")
            
            # Show progress by regions
            print_progress(regions_checked, len(AWS_REGIONS), f"   Regions for account {account_id}")
    
    print()  # New line after progress bar
    return regions_with_instances

def write_to_file(regions_with_instances, output_file):
    """Write results to file (only regions with instances)"""
    with file_lock:
        with open(output_file, 'a', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            
            for region_data in regions_with_instances:
                account_id = region_data['account_id']
                user_info = region_data['user_info']
                access_key = region_data['access_key']
                region = region_data['region']
                
                for instance in region_data['instances']:
                    writer.writerow([
                        account_id,
                        user_info,
                        access_key,
                        region,
                        instance['InstanceId'],
                        instance['State'],
                        instance['InstanceType'],
                        instance['LaunchTime'],
                        str(instance['Tags'])
                    ])

def count_total_accounts(keys_file):
    """Count total number of accounts"""
    count = 0
    try:
        with open(keys_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and len(line.split('|')) >= 4:
                    count += 1
    except Exception:
        pass
    return count

def main():
    """Main function"""
    # Get file paths from environment variables or use defaults
    keys_file = os.getenv('AWS_KEYS_FILE', 'aws_keys.txt')
    output_file = os.getenv('EC2_OUTPUT_FILE', 'ec2_instances_found.csv')
    log_file = os.getenv('EC2_LOG_FILE', 'ec2_check_log.txt')
    
    # Setup logging
    logger = setup_logging(log_file)
    
    # Count total number of accounts
    total_accounts_count = count_total_accounts(keys_file)
    
    logger.info("🚀 Starting EC2 instance check across all AWS regions")
    logger.info(f"📁 Keys file: {keys_file}")
    logger.info(f"📄 Results will be saved to: {output_file}")
    logger.info(f"📝 Logs will be saved to: {log_file}")
    logger.info(f"🌍 Checking {len(AWS_REGIONS)} regions")
    logger.info(f"📊 Total accounts to check: {total_accounts_count}")
    logger.info("=" * 80)
    
    # Create CSV file headers
    with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow([
            'Account ID', 'User Info', 'Access Key', 'Region', 
            'Instance ID', 'State', 'Instance Type', 'Launch Time', 'Tags'
        ])
    
    total_accounts = 0
    accounts_with_instances = 0
    
    try:
        with open(keys_file, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                
                # Parse line: access_key|secret_key|account_id|user_info|timestamp
                parts = line.split('|')
                if len(parts) < 4:
                    logger.warning(f"⚠️  Skipping line {line_num}: invalid format")
                    continue
                
                access_key = parts[0]
                secret_key = parts[1]
                account_id = parts[2]
                user_info = parts[3]
                
                total_accounts += 1
                
                # Check all regions for this account
                regions_with_instances = process_account(
                    access_key, secret_key, account_id, user_info, 
                    logger, total_accounts, total_accounts_count
                )
                
                if regions_with_instances:
                    accounts_with_instances += 1
                    # Write results to file
                    write_to_file(regions_with_instances, output_file)
                
                # Show overall progress
                print_progress(total_accounts, total_accounts_count, "Overall progress")
                print()
                
    except FileNotFoundError:
        logger.error(f"❌ File {keys_file} not found!")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Error reading file: {e}")
        sys.exit(1)
    
    logger.info("\n" + "=" * 80)
    logger.info("✅ Check completed!")
    logger.info(f"📊 Total accounts checked: {total_accounts}")
    logger.info(f"🎯 Accounts with EC2 instances: {accounts_with_instances}")
    logger.info(f"📄 Results saved to: {output_file}")
    logger.info(f"📝 Logs saved to: {log_file}")
    logger.info(f"⏰ Completion time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

if __name__ == "__main__":
    main()
