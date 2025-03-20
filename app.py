from flask import Flask, render_template, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
import boto3
import os

app = Flask(__name__, template_folder=".")
region = "eu-west-2"
bucket_name = "paul-demanze-test-seismic-data" # name must be unique across all of S3 buckets of all users

# Global variable to track next scheduled run
next_run_time = datetime.now() + timedelta(minutes=1)

def send_data_to_aws():
    """
    Pull data and send it to AWS.
    This is a placeholder function that checks if a bucket exists, creates it if needed,
    and writes a file.
    """
    global next_run_time
    
    try:
        # Create an S3 client
        s3 = boto3.client('s3')
               
        # Generate timestamp folder for organizing files
        timestamp_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        timestamp_folder = f"data_{timestamp_str}"
        
        # Check if bucket exists
        try:
            s3.head_bucket(Bucket=bucket_name)
            print(f"Bucket {bucket_name} already exists")
        except s3.exceptions.ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == '404':
                # Bucket doesn't exist, create it
                try:
                    s3.create_bucket(
                        Bucket=bucket_name,
                        CreateBucketConfiguration={
                            'LocationConstraint': region
                        }
                    )
                    print(f"Bucket {bucket_name} created successfully")
                except Exception as bucket_create_error:
                    print(f"Failed to create bucket: {str(bucket_create_error)}")
                    return
            else:
                # Some other error occurred
                print(f"Error checking bucket: {str(e)}")
                return
            
        # Create an empty file and upload it to the bucket
        try:
            empty_file_path = "empty_file.txt"
            with open(empty_file_path, "w") as f:
                pass
            
            file_path = f"{timestamp_folder}/empty_file.txt"
            
            s3.upload_file(empty_file_path, bucket_name, file_path)
            
            os.remove(empty_file_path)
            
            print(f"Successfully uploaded file to {bucket_name}/{file_path}")
        except Exception as file_error:
            print(f"File operation failed: {str(file_error)}")
    except Exception as e:
        print(f"Error in send_data_to_aws: {str(e)}")
    
    # Update the next run time
    next_run_time = datetime.now() + timedelta(minutes=1)  # For testing: 1 minute
    # next_run_time = datetime.now() + timedelta(days=1)  # Production: 1 day

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/get-next-run-time")
def get_next_run_time():
    """Return the time until the next scheduled run in seconds"""
    time_remaining = (next_run_time - datetime.now()).total_seconds()
    return jsonify({"next_run_seconds": max(0, time_remaining)})

@app.route("/trigger-manually", methods=["POST"])
def trigger_manually():
    """Manually trigger the data send function"""
    send_data_to_aws()
    return jsonify({"status": "success", "message": "Data send triggered manually"})

# Initialize the scheduler
scheduler = BackgroundScheduler()
# Schedule the job to run every minute for testing
scheduler.add_job(func=send_data_to_aws, trigger="interval", minutes=1)
# For production use daily schedule:
# scheduler.add_job(func=send_data_to_aws, trigger="interval", days=1)
scheduler.start()