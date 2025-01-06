#!/usr/bin/env python3

import argparse
import subprocess
import os
import boto3
import configparser

# --- Configuration file ---

config = configparser.ConfigParser()
config.read('backup_config.ini')

# --- Read configuration from file ---

AWS_ACCESS_KEY_ID = config.get('aws', 'aws_access_key_id')
AWS_SECRET_ACCESS_KEY = config.get('aws', 'aws_secret_access_key')
AWS_DEFAULT_REGION = config.get('aws', 'aws_default_region')
BUCKET_NAME = config.get('aws', 'bucket_name')
RESTIC_REPOSITORY = config.get('restic', 'repository_path')
LVM_VOLUME_NAME = config.get('lvm', 'volume_name')
LVM_SNAPSHOT_NAME = f"{LVM_VOLUME_NAME}_snapshot"
RETENTION_POLICY = config.get('restic', 'retention_policy')
SNAPSHOT_BUFFER = config.get('restic', 'snapshot_buffer')
RESTIC_PASSWORD = config.get('restic', 'password')

# Set environment variables
env = os.environ

extra_vars = {'AWS_ACCESS_KEY_ID': AWS_ACCESS_KEY_ID,
              'AWS_ACCESS_KEY_ID': AWS_ACCESS_KEY_ID,
              'AWS_SECRET_ACCESS_KEY': AWS_SECRET_ACCESS_KEY,
              'AWS_DEFAULT_REGION' : AWS_DEFAULT_REGION,
              'BUCKET_NAME' : BUCKET_NAME,
              'RESTIC_REPOSITORY' : RESTIC_REPOSITORY,
              'LVM_VOLUME_NAME' : LVM_VOLUME_NAME,
              'RETENTION_POLICY' : RETENTION_POLICY,
              'SNAPSHOT_BUFFER' : SNAPSHOT_BUFFER,
              'RESTIC_PASSWORD' : RESTIC_PASSWORD }

env.update(extra_vars)

def run_restic_command(cmd):
    """Executes a restic command and returns the output."""
    try:
        output = subprocess.check_output(cmd, env=env, shell=True, text=True)
        return output
    except subprocess.CalledProcessError as e:
        print(f"Error running restic command: {e}")
        return None

def create_s3_repository():
    """Creates an S3 repository for restic."""
    cmd = f"restic init --repo s3:https://s3.amazonaws.com/{BUCKET_NAME}/{RESTIC_REPOSITORY}"
    output = run_restic_command(cmd)
    if output:
        print(f"S3 repository created: {output}")
        return True
    else:
        print("Failed to create S3 repository.")
    return False

def check_repository_exists():
    """Checks if the restic repository already exists."""
    cmd = f"restic -r s3:https://s3.amazonaws.com/{BUCKET_NAME}/{RESTIC_REPOSITORY} --json snapshots > /dev/null"
    try:
        subprocess.run(cmd, env=env, shell=True, check=True)
        return True
    except subprocess.CalledProcessError as e:
        if e.returncode == 10:  # Repository not found
            return False
        else:
            print(f"Error checking repository existence: {e}")
            return False

def create_lvm_snapshot():
    """Creates a read-only LVM snapshot of the volume."""
    cmd = f"lvcreate -L {SNAPSHOT_BUFFER} -s -pr -n {LVM_SNAPSHOT_NAME} {LVM_VOLUME_NAME}"
    output = subprocess.check_output(cmd, env=env, shell=True, text=True)
    if output:
        print(f"LVM snapshot created: {output}")
    else:
        print("Failed to create LVM snapshot.")

def backup_lvm_snapshot():
    """Backups the LVM snapshot."""
    device = f"{LVM_SNAPSHOT_NAME}"
    cmd = f"""dd if=\"{device}\" bs=4M status=none |
              restic backup -r s3:https://s3.amazonaws.com/{BUCKET_NAME}/{RESTIC_REPOSITORY} --stdin
           """
    output = run_restic_command(cmd)
    if output:
        print(f"Backup successful: {output}")
    else:
        print("Backup failed.")

def delete_lvm_snapshot():
    """Deletes the LVM snapshot."""
    cmd = f"lvremove -f {LVM_SNAPSHOT_NAME}"
    output = subprocess.check_output(cmd, env=env, shell=True, text=True)
    if output:
        print(f"LVM snapshot deleted: {output}")
    else:
        print("Failed to delete LVM snapshot.")

def prune_old_backups():
    """Prunes old backups according to the retention policy."""
    cmd = f"restic forget -r s3:https://s3.amazonaws.com/{BUCKET_NAME}/{RESTIC_REPOSITORY} --keep-within {RETENTION_POLICY}"
    output = run_restic_command(cmd)
    if output:
        print(f"Pruned old backups: {output}")
    else:
        print("Failed to prune old backups.")

# --- Main execution ---

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Restic Backup/Restore LVM volume.")
    parser.add_argument("--backup-volume", action="store_true", help="Backup the specified LVM volume.")
    args = parser.parse_args()

    if not args.backup_volume:
        print("No action specified. Please use --backup-volume for backup.")
        exit(1)

    # Check if AWS credentials are set
    if not AWS_ACCESS_KEY_ID or not AWS_SECRET_ACCESS_KEY:
        print("AWS credentials not found in config file.")
        exit(1)

    # Create S3 client
    s3_client = boto3.client('s3', aws_access_key_id=AWS_ACCESS_KEY_ID, aws_secret_access_key=AWS_SECRET_ACCESS_KEY)

    # Check if S3 bucket exists
    try:
        s3_client.head_bucket(Bucket=BUCKET_NAME)
    except Exception as e:
        print(f"S3 bucket '{BUCKET_NAME}' does not exist or you do not have permission to access it.")
        exit(1)

    # Check if restic repository exists
    if not check_repository_exists():
        if not create_s3_repository():
            exit(1)

    try:
        # Backup LVM snapshot if the --backup-volume option is provided
        if args.backup_volume:
            create_lvm_snapshot()
            backup_lvm_snapshot()
            delete_lvm_snapshot()
            prune_old_backups()

    except Exception as e:
        print(f"An error occurred during the backup process: {e}")
        # Optionally delete the snapshot if it was created successfully
        if os.path.exists(f"/dev/mapper/{LVM_SNAPSHOT_NAME}"):
            delete_lvm_snapshot()
