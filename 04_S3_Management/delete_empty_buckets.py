#!/usr/bin/env python3
"""
S3 Empty Buckets Cleanup Script
⚠️  WARNING: This script deletes buckets! Use with caution!

This script checks AWS S3 buckets for all provided access keys and removes empty buckets.
It supports both dry-run mode (simulation) and actual execution mode.

Usage:
    python3 delete_empty_buckets.py          # Dry run mode (safe)
    python3 delete_empty_buckets.py --execute # Actual deletion mode

Requirements:
    - boto3 library
    - AWS access keys file in format: access_key|secret_key|account_id|user_path|timestamp
"""

import boto3
import json
import time
from datetime import datetime
from botocore.exceptions import ClientError, NoCredentialsError
import concurrent.futures
import threading
import sys

# Global variables for results recording
results_lock = threading.Lock()
results = []
deleted_buckets_lock = threading.Lock()

def write_deleted_bucket_to_file(access_key, account_id, user_path, bucket_name, output_file):
    """Writes deleted bucket information to file"""
    with deleted_buckets_lock:
        with open(output_file, 'a', encoding='utf-8') as f:
            f.write(f"{access_key}|{account_id}|{user_path}|{bucket_name}|DELETED|{datetime.now().isoformat()}| Deleted\n")

def check_and_delete_empty_bucket(access_key, secret_key, account_id, user_path, timestamp, output_file, dry_run=True):
    """Checks and deletes empty buckets for the given access key"""
    try:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Checking key: {access_key[:10]}...")
        
        # Create AWS session
        session = boto3.Session(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key
        )
        
        s3_client = session.client('s3')
        
        # Get list of buckets
        response = s3_client.list_buckets()
        buckets = response.get('Buckets', [])
        
        if len(buckets) == 0:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ℹ️  No buckets found for {access_key[:10]}...")
            return
        
        bucket_details = []
        deleted_count = 0
        
        for bucket in buckets:
            bucket_name = bucket['Name']
            creation_date = bucket['CreationDate'].strftime('%Y-%m-%d %H:%M:%S')
            
            try:
                # Check bucket access permissions
                bucket_info = s3_client.head_bucket(Bucket=bucket_name)
                bucket_location = s3_client.get_bucket_location(Bucket=bucket_name)
                location = bucket_location.get('LocationConstraint', 'us-east-1')
                
                # Check if bucket has any objects
                try:
                    objects_response = s3_client.list_objects_v2(Bucket=bucket_name, MaxKeys=1)
                    object_count = objects_response.get('KeyCount', 0)
                    is_empty = object_count == 0
                except ClientError as e:
                    if e.response['Error']['Code'] == 'AccessDenied':
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️  Access denied to bucket: {bucket_name}")
                        continue
                    else:
                        is_empty = False
                
                bucket_details.append({
                    'bucket_name': bucket_name,
                    'creation_date': creation_date,
                    'location': location,
                    'is_empty': is_empty,
                    'access_level': 'READ'
                })
                
                if is_empty:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🗑️  Empty bucket found: {bucket_name}")
                    
                    if dry_run:
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔍 DRY RUN: Bucket {bucket_name} would be deleted")
                        write_deleted_bucket_to_file(access_key, account_id, user_path, bucket_name, output_file)
                    else:
                        # Delete empty bucket
                        try:
                            s3_client.delete_bucket(Bucket=bucket_name)
                            print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Bucket deleted: {bucket_name}")
                            write_deleted_bucket_to_file(access_key, account_id, user_path, bucket_name, output_file)
                            deleted_count += 1
                        except ClientError as e:
                            error_code = e.response['Error']['Code']
                            print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ Error deleting {bucket_name}: {error_code}")
                else:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Bucket contains data: {bucket_name}")
                
            except ClientError as e:
                error_code = e.response['Error']['Code']
                if error_code == '403':
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️  Access denied to bucket: {bucket_name}")
                else:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ Error accessing {bucket_name}: {error_code}")
        
        result = {
            'access_key': access_key,
            'secret_key': secret_key[:10] + '...',
            'account_id': account_id,
            'user_path': user_path,
            'timestamp': timestamp,
            'status': 'SUCCESS',
            'bucket_count': len(buckets),
            'empty_buckets_found': len([b for b in bucket_details if b.get('is_empty', False)]),
            'buckets_deleted': deleted_count,
            'buckets': bucket_details
        }
        
    except NoCredentialsError:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ Invalid credentials: {access_key[:10]}...")
        result = {
            'access_key': access_key,
            'secret_key': secret_key[:10] + '...',
            'account_id': account_id,
            'user_path': user_path,
            'timestamp': timestamp,
            'status': 'INVALID_CREDENTIALS',
            'bucket_count': 0,
            'empty_buckets_found': 0,
            'buckets_deleted': 0,
            'buckets': []
        }
    except ClientError as e:
        error_code = e.response['Error']['Code']
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ AWS error: {access_key[:10]}... - {error_code}")
        result = {
            'access_key': access_key,
            'secret_key': secret_key[:10] + '...',
            'account_id': account_id,
            'user_path': user_path,
            'timestamp': timestamp,
            'status': f'ERROR: {error_code}',
            'bucket_count': 0,
            'empty_buckets_found': 0,
            'buckets_deleted': 0,
            'buckets': []
        }
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ Unknown error: {access_key[:10]}... - {str(e)}")
        result = {
            'access_key': access_key,
            'secret_key': secret_key[:10] + '...',
            'account_id': account_id,
            'user_path': user_path,
            'timestamp': timestamp,
            'status': f'UNKNOWN_ERROR: {str(e)}',
            'bucket_count': 0,
            'empty_buckets_found': 0,
            'buckets_deleted': 0,
            'buckets': []
        }
    
    # Safely add result
    with results_lock:
        results.append(result)
    
    return result

def process_keys_file(filename):
    """Processes the keys file"""
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
                print(f"Warning: Line {line_num} has incorrect format: {line}")
    
    return keys

def main():
    print("=" * 80)
    print("🗑️  S3 EMPTY BUCKETS CLEANUP")
    print("=" * 80)
    print(f"⏰ Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Check command line arguments
    dry_run = True
    if len(sys.argv) > 1 and sys.argv[1] == '--execute':
        dry_run = False
        print("⚠️  EXECUTION MODE: Buckets will be actually deleted!")
    else:
        print("🔍 DRY RUN MODE: Buckets will NOT be deleted (simulation only)")
    
    # User confirmation
    if not dry_run:
        print("\n" + "=" * 80)
        print("⚠️  WARNING! YOU ARE ABOUT TO DELETE BUCKETS!")
        print("⚠️  THIS OPERATION IS IRREVERSIBLE!")
        print("=" * 80)
        print("✅ Automatic confirmation for non-interactive mode")
        # confirm = input("Type 'DELETE' to confirm: ")
        # if confirm != 'DELETE':
        #     print("❌ Operation cancelled by user")
        #     return
    
    # Create file for deleted buckets
    timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')
    mode_str = "dry_run" if dry_run else "executed"
    deleted_buckets_file = f'deleted_buckets_{mode_str}_{timestamp_str}.txt'
    
    # Write header to file
    with open(deleted_buckets_file, 'w', encoding='utf-8') as f:
        f.write("Access Key|Account ID|User Path|Bucket Name|Status|Timestamp|Action\n")
    
    print(f"📁 Deleted buckets file: {deleted_buckets_file}")
    
    # Read keys from file
    keys_file = 'aws_keys.txt'  # Change this to your keys file path
    try:
        keys = process_keys_file(keys_file)
    except FileNotFoundError:
        print(f"❌ Keys file not found: {keys_file}")
        print("Please create a file with AWS keys in format: access_key|secret_key|account_id|user_path|timestamp")
        return
    
    print(f"🔑 Found {len(keys)} keys to check")
    print(f"⚙️  Using {min(5, len(keys))} threads for parallel processing")
    print("-" * 80)
    
    # Use ThreadPoolExecutor for parallel processing
    max_workers = min(5, len(keys))  # Limit threads for safety
    
    start_time = time.time()
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Start checking all keys
        futures = []
        for access_key, secret_key, account_id, user_path, timestamp in keys:
            future = executor.submit(check_and_delete_empty_bucket, access_key, secret_key, account_id, user_path, timestamp, deleted_buckets_file, dry_run)
            futures.append(future)
        
        # Wait for all tasks to complete
        completed = 0
        for future in concurrent.futures.as_completed(futures):
            completed += 1
            if completed % 10 == 0 or completed == len(keys):
                elapsed = time.time() - start_time
                rate = completed / elapsed if elapsed > 0 else 0
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 📊 Progress: {completed}/{len(keys)} keys ({rate:.1f} keys/sec)")
    
    elapsed_time = time.time() - start_time
    print("-" * 80)
    print(f"✅ CHECK COMPLETED!")
    print(f"⏱️  Execution time: {elapsed_time:.1f} seconds")
    print(f"📊 Processed keys: {len(results)}")
    
    # Statistics
    successful = len([r for r in results if r['status'] == 'SUCCESS'])
    total_empty_buckets = sum([r['empty_buckets_found'] for r in results if r['status'] == 'SUCCESS'])
    total_deleted = sum([r['buckets_deleted'] for r in results if r['status'] == 'SUCCESS'])
    
    print(f"\n📈 STATISTICS:")
    print(f"   🔑 Total keys: {len(results)}")
    print(f"   ✅ Successfully checked: {successful}")
    print(f"   🗑️  Empty buckets found: {total_empty_buckets}")
    print(f"   🗑️  Buckets deleted: {total_deleted}")
    
    # Check number of records in file
    try:
        with open(deleted_buckets_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            deleted_count = len(lines) - 1  # Minus header
        print(f"   📄 Written to file: {deleted_count} buckets")
    except:
        print(f"   📄 Could not count records in file")
    
    print(f"\n📁 RESULTS SAVED:")
    print(f"   🗑️  Deleted buckets: {deleted_buckets_file}")
    
    # Create summary report
    summary_filename = f'empty_buckets_summary_{mode_str}_{timestamp_str}.txt'
    with open(summary_filename, 'w', encoding='utf-8') as f:
        f.write(f"Empty S3 Buckets Cleanup Summary\n")
        f.write(f"================================\n")
        f.write(f"Mode: {'DRY RUN' if dry_run else 'EXECUTION'}\n")
        f.write(f"Check time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Execution time: {elapsed_time:.1f} seconds\n")
        f.write(f"Total keys: {len(results)}\n")
        f.write(f"Successfully checked: {successful}\n")
        f.write(f"Empty buckets found: {total_empty_buckets}\n")
        f.write(f"Buckets deleted: {total_deleted}\n\n")
        
        f.write("Empty buckets by keys:\n")
        f.write("=" * 50 + "\n")
        
        for result in results:
            if result['status'] == 'SUCCESS' and result['empty_buckets_found'] > 0:
                f.write(f"Access Key: {result['access_key']}\n")
                f.write(f"Account ID: {result['account_id']}\n")
                f.write(f"User Path: {result['user_path']}\n")
                f.write(f"Empty buckets: {result['empty_buckets_found']}\n")
                f.write(f"Deleted: {result['buckets_deleted']}\n")
                f.write("Buckets:\n")
                for bucket in result['buckets']:
                    if bucket.get('is_empty', False):
                        f.write(f"  - {bucket['bucket_name']} (empty)\n")
                f.write("\n")
    
    print(f"   📋 Summary report: {summary_filename}")
    print("=" * 80)
    
    if dry_run:
        print("\n💡 For actual deletion run:")
        print(f"   python3 {sys.argv[0]} --execute")

if __name__ == "__main__":
    main()
