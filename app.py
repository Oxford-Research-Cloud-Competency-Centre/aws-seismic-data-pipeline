from flask import Flask, render_template, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
import boto3
import os
import subprocess
import time
import threading
import json

app = Flask(__name__, template_folder=".")
region = "eu-west-2"
bucket_name = "paul-demanze-test-seismic-data"  # name must be unique across all of S3 buckets of all users
ZEROTIER_NETWORK_ID = "fada62b015140480"

# Global variables
next_run_time = datetime.now() + timedelta(minutes=1)
zerotier_connected = False
zerotier_status = "Not connected"

def check_zerotier_status():
    """Check if already connected to ZeroTier network"""
    try:
        result = subprocess.run(
            ["zerotier-cli", "listnetworks"], 
            capture_output=True, 
            text=True,
            shell=True  # Use shell=True to help with command resolution
        )
        return ZEROTIER_NETWORK_ID in result.stdout
    except Exception as e:
        print(f"Error checking ZeroTier status: {str(e)}")
        return False

def connect_to_zerotier():
    """Connect to the ZeroTier network and wait for approval"""
    global zerotier_connected, zerotier_status
    
    try:
        # Check if already connected
        if check_zerotier_status():
            zerotier_connected = True
            zerotier_status = "Already connected"
            print("Already connected to ZeroTier network")
            return True
            
        # Attempt to join the network
        print(f"Attempting to join ZeroTier network: {ZEROTIER_NETWORK_ID}")
        zerotier_status = "Joining network..."
        
        join_result = subprocess.run(
            ["zerotier-cli", "join", ZEROTIER_NETWORK_ID],
            capture_output=True,
            text=True,
            shell=True
        )
        
        if "200" in join_result.stdout:
            print("Join command successful, waiting for authorization...")
            zerotier_status = "Waiting for authorization..."
            
            # Start monitoring for successful connection
            monitor_zerotier_connection()
            return True
        else:
            print(f"Failed to join ZeroTier network: {join_result.stdout}")
            zerotier_status = f"Join failed: {join_result.stdout}"
            return False
            
    except Exception as e:
        print(f"Error connecting to ZeroTier: {str(e)}")
        zerotier_status = f"Connection error: {str(e)}"
        return False

def monitor_zerotier_connection():
    """Monitor ZeroTier connection status in background thread"""
    def monitor_thread():
        global zerotier_connected, zerotier_status
        attempts = 0
        
        # Wait indefinitely until connected or the application is terminated
        while not zerotier_connected:
            try:
                # Check network status
                result = subprocess.run(
                    ["zerotier-cli", "listnetworks"], 
                    capture_output=True, 
                    text=True,
                    shell=True
                )
                
                # Parse output to check for connection and authorization
                if ZEROTIER_NETWORK_ID in result.stdout:
                    # Check if OK/ACTIVE and we have an IP
                    if "OK" in result.stdout and "PRIVATE" not in result.stdout:
                        zerotier_connected = True
                        zerotier_status = "Connected and authorized"
                        print("Successfully connected to ZeroTier network")
                        break
                
                attempts += 1
                time.sleep(10)  # Check every 10 seconds
                
                # Update status message with waiting time
                minutes_waiting = attempts // 6
                hours_waiting = minutes_waiting // 60
                
                if hours_waiting > 0:
                    remaining_minutes = minutes_waiting % 60
                    zerotier_status = f"Waiting for authorization... ({hours_waiting}h {remaining_minutes}m)"
                else:
                    zerotier_status = f"Waiting for authorization... ({minutes_waiting}m)"
                
            except Exception as e:
                print(f"Error monitoring ZeroTier: {str(e)}")
                # Sleep before retrying to avoid tight error loops
                time.sleep(30)
    
    # Start monitoring in a separate thread
    thread = threading.Thread(target=monitor_thread)
    thread.daemon = True
    thread.start()

def send_data_to_aws():
    """
    Pull data and send it to AWS.
    This is a placeholder function that checks if a bucket exists, creates it if needed,
    and writes a file.
    """
    global next_run_time
    
    # Check if ZeroTier is connected before proceeding
    if not zerotier_connected:
        print("ZeroTier not connected, skipping data send")
        next_run_time = datetime.now() + timedelta(minutes=1)
        return
    
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
    return jsonify({
        "next_run_seconds": max(0, time_remaining),
        "zerotier_connected": zerotier_connected,
        "zerotier_status": zerotier_status
    })

@app.route("/trigger-manually", methods=["POST"])
def trigger_manually():
    """Manually trigger the data send function"""
    if not zerotier_connected:
        return jsonify({
            "status": "error", 
            "message": f"ZeroTier not connected. Status: {zerotier_status}"
        })
    
    send_data_to_aws()
    return jsonify({"status": "success", "message": "Data send triggered manually"})

@app.route("/reconnect-zerotier", methods=["POST"])
def reconnect_zerotier():
    """Manually trigger ZeroTier reconnection"""
    connect_to_zerotier()
    return jsonify({
        "status": "success", 
        "message": f"ZeroTier reconnection initiated. Status: {zerotier_status}"
    })

# Initialize ZeroTier connection after a short delay to ensure all modules are loaded
def delayed_zerotier_connect():
    # Wait a few seconds before trying to connect to avoid startup race conditions
    time.sleep(5)
    print("Starting ZeroTier connection attempt...")
    connect_to_zerotier()

# Start the connection process in a separate thread
threading.Thread(target=delayed_zerotier_connect, daemon=True).start()

# Initialize the scheduler
scheduler = BackgroundScheduler()
# Schedule the job to run every minute for testing
scheduler.add_job(func=send_data_to_aws, trigger="interval", minutes=1)
# For production use daily schedule:
# scheduler.add_job(func=send_data_to_aws, trigger="interval", days=1)
scheduler.start()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)