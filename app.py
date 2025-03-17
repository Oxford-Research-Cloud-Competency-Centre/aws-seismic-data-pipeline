from flask import Flask, render_template, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
import boto3
import os

app = Flask(__name__, template_folder=".")

# Global variable to track next scheduled run
next_run_time = datetime.now() + timedelta(minutes=1)

def send_data_to_aws():
    """
    Pull data and send it to AWS.
    This is a placeholder function that creates a bucket and writes an empty file.
    """
    global next_run_time
    
    try:
        # Create an S3 client
        s3 = boto3.client('s3')
        
        # Create a unique bucket name (this is just for demonstration)
        bucket_name = f"seismic-data-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        # Create the bucket (note: in production, you'd check if it exists first)
        # This will likely fail without proper AWS credentials
        try:
            s3.create_bucket(Bucket=bucket_name)
            
            # Create an empty file and upload it to the bucket
            empty_file_path = "/tmp/empty_file.txt"
            with open(empty_file_path, "w") as f:
                pass
            
            s3.upload_file(empty_file_path, bucket_name, "empty_file.txt")
            os.remove(empty_file_path)
            
            print(f"Successfully created bucket {bucket_name} and uploaded empty file")
        except Exception as e:
            print(f"AWS operation failed: {str(e)}")
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