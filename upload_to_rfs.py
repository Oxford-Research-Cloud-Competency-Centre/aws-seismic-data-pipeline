import os
import shutil
import subprocess
from pathlib import Path
import time
import getpass
import boto3
import tempfile

# The script assumes your machine is authenticated to AWS (aws authenticate)
# The script assumes you are connected to the University network (vpn)

s3_bucket = "paul-demanze-test-seismic-data"
rfs_directory = "Cloud Computing For Research"

def get_s3_files():
    """
    Get list of all files in S3 bucket
    Returns:
        list: List of S3 object keys
    """
    try:
        s3 = boto3.client('s3')
        paginator = s3.get_paginator('list_objects_v2')
        files = []
        
        for page in paginator.paginate(Bucket=s3_bucket):
            if 'Contents' in page:
                files.extend([obj['Key'] for obj in page['Contents']])
                
        print(f"Found {len(files)} files in S3 bucket {s3_bucket}")
        return files
    except Exception as e:
        print(f"Error listing S3 files: {str(e)}")
        return []

def download_from_s3(key, local_path):
    """
    Download a file from S3
    """
    try:
        s3 = boto3.client('s3')
        print(f"Downloading {key} from S3...")
        # Ensure the directory exists
        local_path.parent.mkdir(parents=True, exist_ok=True)
        s3.download_file(s3_bucket, key, str(local_path))
        return True
    except Exception as e:
        print(f"Error downloading {key} from S3: {str(e)}")
        return False

def delete_from_s3(key):
    """
    Delete a file from S3
    """
    try:
        s3 = boto3.client('s3')
        print(f"Deleting {key} from S3...")
        s3.delete_object(Bucket=s3_bucket, Key=key)
        return True
    except Exception as e:
        print(f"Error deleting {key} from S3: {str(e)}")
        return False

def verify_file_in_rfs(s3_key, rfs_base_path):
    """
    Verify that a file exists in RFS and has the correct size
    Args:
        s3_key: The full S3 key including path
        rfs_base_path: Base RFS path to check against
    """
    try:
        # Preserve the directory structure from S3
        rfs_file = rfs_base_path / s3_key
        return rfs_file.exists() and rfs_file.stat().st_size > 0
    except Exception:
        return False

def list_available_directories(drive_letter='R'):
    """
    List available directories in the RFS root
    """
    try:
        rfs_path = Path(f"{drive_letter}:")
        dirs = [d.name for d in rfs_path.iterdir() if d.is_dir()]
        print("\nAvailable directories in RFS:")
        for d in sorted(dirs):
            print(f"- {d}")
        return dirs
    except Exception as e:
        print(f"Error listing directories: {str(e)}")
        return []

def is_drive_mounted(drive_letter='R'):
    """
    Check if the drive is already mounted and accessible
    """
    try:
        rfs_path = Path(f"{drive_letter}:")
        # Try to list directory contents to verify access
        list(rfs_path.iterdir())
        print(f"Drive {drive_letter}: is already mounted and accessible")
        return True
    except:
        return False

def mount_rfs(drive_letter='R', username=None):
    """
    Mount the Oxford RFS network drive
    Args:
        drive_letter (str): Drive letter to map RFS to
        username (str): Oxford username (will prompt if None)
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Check if drive is already mounted and accessible
        if is_drive_mounted(drive_letter):
            return True
            
        print("Attempting to mount RFS...")
        
        # Get credentials if not provided
        if username is None:
            print("\nPlease enter your Oxford credentials:")
            username = input("Username (e.g. abcd1234): ")
        
        password = getpass.getpass("Password: ")
        
        # Format the full username
        full_username = f"connect.ox.ac.uk\\{username}"
        
        # Mount the RFS drive with explicit credentials
        print("Mounting RFS drive...")
        result = subprocess.run(
            ['net', 'use', f'{drive_letter}:', r'\\connect.ox.ac.uk\RFS', 
             '/user:' + full_username, password],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            print(f"Successfully mounted RFS to {drive_letter}:")
            return is_drive_mounted(drive_letter)
        else:
            print(f"Failed to mount RFS. Error message:")
            print(result.stderr)
            return False
            
    except Exception as e:
        print(f"Error mounting RFS: {str(e)}")
        return False

def migrate_s3_to_rfs(drive_letter='R', username=None):
    """
    Migrate all files from S3 to RFS, preserving folder structure
    """
    try:
        # First mount RFS
        if not mount_rfs(drive_letter, username):
            return False
            
        # Verify RFS directory exists
        rfs_path = Path(f"{drive_letter}:") / rfs_directory
        if not rfs_path.exists():
            print(f"\nError: Directory '{rfs_directory}' not found in RFS")
            print("Please check the directory name or choose from the following directories:")
            list_available_directories(drive_letter)
            return False
            
        # Get list of S3 files
        s3_files = get_s3_files()
        if not s3_files:
            print("No files found in S3 bucket")
            return True
            
        # Create temporary directory for downloads
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir_path = Path(temp_dir)
            
            # Process each file
            for s3_key in s3_files:
                print(f"\nProcessing {s3_key}...")
                
                # Skip if file already exists in RFS with same structure
                if verify_file_in_rfs(s3_key, rfs_path):
                    print(f"{s3_key} already exists in RFS, skipping download")
                    if delete_from_s3(s3_key):
                        print(f"Deleted {s3_key} from S3")
                    continue
                
                # Download from S3 (preserving structure in temp dir)
                local_path = temp_dir_path / s3_key
                if not download_from_s3(s3_key, local_path):
                    continue
                
                # Copy to RFS
                try:
                    dest_path = rfs_path / s3_key
                    print(f"Copying {s3_key} to RFS...")
                    # Ensure the destination directory exists
                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(local_path, dest_path)
                    
                    # Verify the copy
                    if verify_file_in_rfs(s3_key, rfs_path):
                        print(f"Successfully copied {s3_key} to RFS")
                        # Delete from S3
                        if delete_from_s3(s3_key):
                            print(f"Deleted {s3_key} from S3")
                    else:
                        print(f"Failed to verify {s3_key} in RFS, keeping S3 copy")
                        
                except Exception as e:
                    print(f"Error copying {s3_key} to RFS: {str(e)}")
                    continue
                    
        print("\nMigration completed!")
        return True
        
    except Exception as e:
        print(f"Error during migration: {str(e)}")
        return False

if __name__ == "__main__":
    migrate_s3_to_rfs() 