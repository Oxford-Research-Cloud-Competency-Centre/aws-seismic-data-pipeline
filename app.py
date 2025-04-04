from flask import Flask, render_template, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
import boto3
import os
import subprocess
import time
import threading
import json
import asyncio
import aiohttp  # For asynchronous HTTP requests
from pathlib import Path
import logging
import sys

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder=".")

with open("config.json", "r") as f:
    config = json.load(f)

region = config["region"]
bucket_name = config["bucket_name"]
ZEROTIER_NETWORK_ID = config["network_id"]

# Global variables
next_run_time = datetime.now() + timedelta(days=1)
zerotier_connected = False
zerotier_status = "Not connected"

def check_zerotier_network_status():
    """Check detailed ZeroTier network information"""
    try:
        # Get network status
        network_result = subprocess.Popen(
            f"zerotier-cli -j listnetworks",
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True
        )
        network_output, _ = network_result.communicate()
        logger.info(f"Network status: {network_output}")
        
        # Try to parse JSON output
        try:
            import json
            networks = json.loads(network_output)
            logger.info(f"Parsed network data: {networks}")
            
            # Check if our network exists and has an assigned address
            for network in networks:
                if network.get('id') == ZEROTIER_NETWORK_ID:
                    logger.info(f"Found network: {network}")
                    
                    # Check if we have assigned addresses
                    if network.get('assignedAddresses'):
                        logger.info(f"We have assigned addresses: {network['assignedAddresses']}")
                        return True
            
            return False
        except json.JSONDecodeError:
            logger.error(f"Failed to parse JSON: {network_output}")
            return False
    except Exception as e:
        logger.error(f"Error checking network status: {str(e)}")
        return False

def connect_to_zerotier():
    """Connect to the ZeroTier network and properly capture all output"""
    global zerotier_connected, zerotier_status
    
    try:
        # Check ZeroTier info and capture all output
        logger.info("Checking ZeroTier status")
        info_process = subprocess.Popen(
            "zerotier-cli info",
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # Redirect stderr to stdout
            universal_newlines=True    # Return strings instead of bytes
        )
        info_output, _ = info_process.communicate()
        logger.info(f"ZeroTier info output: {info_output}")
        
        # Try to join the network
        logger.info(f"Attempting to join network: {ZEROTIER_NETWORK_ID}")
        join_process = subprocess.Popen(
            f"zerotier-cli join {ZEROTIER_NETWORK_ID}",
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # Get everything in one stream
            universal_newlines=True
        )
        join_output, _ = join_process.communicate()
        logger.info(f"Join output: {join_output}")
        
        # Continue with your logic based on the output
        if "200" in join_output:
            logger.info("Join successful")
            zerotier_status = "Waiting for authorization..."
            monitor_zerotier_connection()
            return True
        else:
            zerotier_status = f"Join failed: {join_output}"
            return False
            
    except Exception as e:
        logger.error(f"Error connecting to ZeroTier: {str(e)}")
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
                list_process = subprocess.Popen(
                    "zerotier-cli listnetworks",
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    universal_newlines=True
                )
                list_output, _ = list_process.communicate()
                
                if ZEROTIER_NETWORK_ID in list_output:
                    if "OK" in list_output:
                        zerotier_connected = True
                        zerotier_status = "Connected and authorized"
                        logger.info("Successfully connected to ZeroTier network")
                        break
                    else:
                        # Joined but waiting for authorization
                        logger.info("Joined but waiting for authorization")
                        zerotier_status = "Waiting for authorization from network admin"
                
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
                logger.error(f"Error monitoring ZeroTier: {str(e)}")
                time.sleep(30)
    
    # Start monitoring in a separate thread
    thread = threading.Thread(target=monitor_thread)
    thread.daemon = True
    thread.start()

def form_request(sensor_ip, network, station, location, channel, starttime, endtime):
    """
    Form the request URL in the format expected by Certimus devices
    
    Parameters:
    ----------
    sensor_ip : str
        IP address of sensor
    network : str
        Network code
    station : str
        Station code
    location : str
        Location code
    channel : str
        Channel code
    starttime : datetime
        Start time of request
    endtime : datetime
        End time of request
    """
    # Convert datetime to Unix timestamp if needed
    if hasattr(starttime, 'timestamp'):
        start_timestamp = starttime.timestamp()
    else:
        start_timestamp = starttime
        
    if hasattr(endtime, 'timestamp'):
        end_timestamp = endtime.timestamp()
    else:
        end_timestamp = endtime
    
    seed_params = f'{network}.{station}.{location}.{channel}'
    timeselect = f'from={start_timestamp}&to={end_timestamp}'
    request = f'http://{sensor_ip}/data?channel={seed_params}&{timeselect}'
    
    logger.debug(f"Created request URL: {request}")
    return request

def make_urls(zerotier_ips, request_params, data_dir=''):
    """Generate URLs and output file paths for the data requests"""
    from pathlib import Path
    import os
    
    # If data dir is empty then use current directory
    if data_dir == '':
        data_dir = Path.cwd()
    else:
        data_dir = Path(data_dir)
    
    # Create directory if it doesn't exist
    os.makedirs(data_dir, exist_ok=True)
    
    urls = []
    outfiles = []
    
    logger.debug(f"zerotier_ips: {zerotier_ips}")
    logger.debug(f"request_params length: {len(request_params)}")
    if request_params:
        logger.debug(f"Sample request_param: {request_params[0]}")
    
    for params in request_params:
        network, station, location, channel, start_time, end_time = params
        
        # Check if the station is in zerotier_ips
        if station not in zerotier_ips:
            logger.warning(f"Station {station} not found in zerotier_ips")
            continue
            
        # Get the sensor IP
        sensor_ip = zerotier_ips[station]
        
        # Create URL using the form_request function to ensure correct URL format
        request_url = form_request(
            sensor_ip, 
            network, 
            station, 
            location, 
            channel, 
            start_time, 
            end_time
        )
        
        # Extract date and time components for the filename
        year = start_time.year
        month = start_time.month
        day = start_time.day
        hour = start_time.hour
        minute = start_time.minute
        second = start_time.second
        
        # Format filename with date in the filename instead of using subfolders
        seed_params = f'{network}.{station}.{location}.{channel}'
        timestamp = f'{year}{month:02d}{day:02d}T{hour:02d}{minute:02d}{second:02d}'
        outfile = data_dir / f"{seed_params}.{timestamp}.mseed"
        
        # Check if the file already exists
        if outfile.is_file():
            logger.info(f"File {outfile} already exists, skipping request")
            continue
            
        urls.append(request_url)
        outfiles.append(outfile)
        
    logger.debug(f"Generated {len(urls)} URLs and outfiles")
    if urls:
        logger.debug(f"Sample URL: {urls[0]}")
        logger.debug(f"Sample outfile: {outfiles[0]}")
    
    return urls, outfiles

async def make_async_request(session, semaphore, request_url, outfile):
    """Make an async HTTP request and save the response to a file"""
    async with semaphore:
        try:
            logger.info(f"Requesting: {request_url}")
            async with session.get(request_url) as resp:
                logger.info(f'Request at {datetime.now()}')
                # Raise HTTP error for 4xx/5xx errors
                resp.raise_for_status()
                
                # Read binary data from the response
                data = await resp.read()
                if len(data) == 0:
                    logger.error(f"Empty response for {request_url}. Won't write a zero byte file.")
                    return
                    
                # Now write data
                with open(outfile, "wb") as f:
                    f.write(data)
                logger.info(f"Successfully wrote data to {outfile}")
                
        except aiohttp.ClientResponseError as e:
            logger.error(f"Client error for {request_url}: {e}")
            # Create a placeholder file to indicate failure
            create_placeholder_file(outfile, "HTTP_ERROR", str(e))
        except Exception as e:
            logger.error(f"Unexpected error for {request_url}: {e}")
            # Create a placeholder file to indicate failure
            create_placeholder_file(outfile, "CONNECTION_ERROR", str(e))

def create_placeholder_file(outfile, error_type, error_message):
    """Create a placeholder file to indicate a failed request"""
    try:
        # Create the directory if it doesn't exist
        outfile.parent.mkdir(exist_ok=True, parents=True)
        
        # Create a placeholder file with error information
        with open(outfile, "w") as f:
            f.write(f"PLACEHOLDER_FILE\n")
            f.write(f"ERROR_TYPE: {error_type}\n")
            f.write(f"ERROR_MESSAGE: {error_message}\n")
            f.write(f"TIMESTAMP: {datetime.now().isoformat()}\n")
            f.write(f"ORIGINAL_REQUEST: {outfile.name}\n")
            f.write(f"STATION: {outfile.name.split('.')[1]}\n")
            f.write(f"CHANNEL: {outfile.name.split('.')[3]}\n")
            f.write(f"TIME_PERIOD: {outfile.name.split('.')[4]}\n")
        
        logger.info(f"Created placeholder file for failed request: {outfile}")
    except Exception as e:
        logger.error(f"Failed to create placeholder file: {str(e)}")

def iterate_chunks(start, end, chunksize):
    '''
    Function that makes an iterator between two dates (start, end)
    in intervals of <chunksize>.

    Parameters:
    ----------
    start : datetime
        start time
    end : datetime
        end time
    chunksize : timedelta
        timespan of chunks to split timespan into and iterate over
    '''
    chunk_start = start
    while chunk_start < end:
        yield chunk_start
        chunk_start += chunksize

async def get_data(request_params, zerotier_ips, data_dir='', 
                  chunksize=timedelta(hours=1), buffer=timedelta(seconds=120)):
    """Asynchronously download data from the given parameters using chunked requests"""
    # If data dir is empty then use current directory
    if data_dir == '':
        data_dir = Path.cwd()
    else:
        data_dir = Path(data_dir)
    
    # Create directory if it doesn't exist
    os.makedirs(data_dir, exist_ok=True)
    
    # Break down the request_params into smaller time chunks
    chunked_request_params = []
    for params in request_params:
        network, station, location, channel, start_time, end_time = params
        
        # Break the time range into chunks (typically hourly)
        for chunk_start in iterate_chunks(start_time, end_time, chunksize):
            # Add buffer on either side (but respect original boundaries)
            query_start = max(start_time, chunk_start - buffer)
            query_end = min(end_time, chunk_start + chunksize + buffer)
            
            chunked_request_params.append(
                (network, station, location, channel, query_start, query_end)
            )
    
    logger.info(f"Split {len(request_params)} original requests into {len(chunked_request_params)} chunked requests")
    
    # Generate URLs and output file paths for the chunked requests
    urls, outfiles = make_urls(zerotier_ips, chunked_request_params, data_dir)
    
    if not urls:
        logger.error("No URLs generated for data fetching")
        return
        
    # Group requests by IP to prevent overloading any single server
    requests_by_ip = {}
    for url, outfile in zip(urls, outfiles):
        sensor_ip = url.split("/")[2]
        if sensor_ip not in requests_by_ip:
            requests_by_ip[sensor_ip] = []
        requests_by_ip[sensor_ip].append((url, outfile))
    
    # Set up semaphores to limit concurrent requests per IP
    n_async_requests = 3  # Limit concurrent requests per server
    semaphores = {ip: asyncio.Semaphore(n_async_requests) for ip in requests_by_ip}
    
    # Create S3 client for uploading files
    s3 = boto3.client('s3', region_name=region)
    
    # Make the requests
    async with aiohttp.ClientSession() as session:
        # Process each IP's requests in batches
        for ip, reqs in requests_by_ip.items():
            semaphore = semaphores[ip]
            
            # Process requests in batches of n_async_requests
            for i in range(0, len(reqs), n_async_requests):
                batch = reqs[i:i+n_async_requests]
                tasks = []
                
                for request_url, outfile in batch:
                    # Skip if the file already exists
                    if outfile.is_file():
                        logger.info(f"File {outfile} already exists, skipping download")
                        continue
                    
                    task = asyncio.create_task(
                        make_async_request(session, semaphore, request_url, outfile)
                    )
                    tasks.append((task, outfile))
                
                if tasks:
                    logger.info(f"Starting batch of {len(tasks)} download tasks for IP {ip}")
                    # Wait for all tasks in this batch to complete
                    await asyncio.gather(*[task for task, _ in tasks])
                    logger.info(f"Batch of {len(tasks)} download tasks completed for IP {ip}")
                    
                    # Upload completed files to S3 and delete them locally
                    for _, outfile in tasks:
                        if outfile.is_file():
                            try:
                                # Check if this is a placeholder file
                                is_placeholder = False
                                try:
                                    with open(outfile, 'r') as f:
                                        first_line = f.readline().strip()
                                        if first_line == "PLACEHOLDER_FILE":
                                            is_placeholder = True
                                            logger.info(f"Uploading placeholder file: {outfile}")
                                except Exception as e:
                                    logger.warning(f"Error checking if file is placeholder: {str(e)}")
                                
                                # Extract date from filename for S3 folder structure
                                # Format: network.station.location.channel.YYYYMMDDTHHMMSS.mseed
                                filename_parts = outfile.name.split('.')
                                if len(filename_parts) >= 5:
                                    # Extract date part (YYYYMMDD)
                                    date_part = filename_parts[4][:8]
                                    # Create S3 key with date folder
                                    s3_key = f"{date_part}/{outfile.name}"
                                else:
                                    # Fallback if filename doesn't match expected format
                                    s3_key = outfile.name
                                
                                # Upload the file to S3
                                logger.info(f"Uploading {outfile} to {bucket_name}/{s3_key}")
                                s3.upload_file(str(outfile), bucket_name, s3_key)
                                logger.info(f"S3 upload completed successfully for {outfile}")
                                
                                # Add metadata to indicate if this is a placeholder file
                                if is_placeholder:
                                    logger.info(f"Adding placeholder tag to {s3_key}")
                                    s3.put_object_tagging(
                                        Bucket=bucket_name,
                                        Key=s3_key,
                                        Tagging={
                                            'TagSet': [
                                                {
                                                    'Key': 'is_placeholder',
                                                    'Value': 'true'
                                                }
                                            ]
                                        }
                                    )
                                
                                # Delete the file from local storage
                                try:
                                    logger.info(f"Deleting local file: {outfile}")
                                    os.remove(outfile)
                                    logger.info(f"Successfully deleted local file: {outfile}")
                                except Exception as e:
                                    logger.warning(f"Failed to delete local file {outfile}: {str(e)}")
                                    
                            except Exception as upload_error:
                                logger.error(f"Error uploading {outfile}: {str(upload_error)}")
                                logger.error(f"Error details: {type(upload_error).__name__}: {str(upload_error)}")
                                import traceback
                                logger.error(traceback.format_exc())
        
        logger.info("All download tasks completed")

def send_data_to_aws():
    """
    Pull data and send it to AWS.
    Checks if a bucket exists, creates it if needed, downloads data and uploads to S3.
    """
    global next_run_time
    
    logger.info("================= STARTING DATA SEND OPERATION =================")
    
    # Check if ZeroTier is connected before proceeding
    # Comment out this check to allow testing without VPN
    # if not zerotier_connected:
    #     logger.info("ZeroTier not connected, skipping data send")
    #     next_run_time = datetime.now() + timedelta(days=1)
    #     return
    
    try:
        # Verify S3 configuration before proceeding
        if not verify_s3_configuration():
            logger.error("S3 configuration verification failed. Aborting data send operation.")
            next_run_time = datetime.now() + timedelta(days=1)
            return
            
        # Create an S3 client
        logger.info("Creating S3 client for region:", region)
        s3 = boto3.client('s3', region_name=region)
               
        # Generate timestamp folder for organizing files
        timestamp_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        timestamp_folder = f"data_{timestamp_str}"
        logger.info(f"Using timestamp folder: {timestamp_folder}")
        
        # Check if bucket exists
        try:
            s3.head_bucket(Bucket=bucket_name)
            logger.info(f"Bucket {bucket_name} already exists")
        except s3.exceptions.ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == '404':
                # Bucket doesn't exist, create it
                try:
                    logger.info(f"Creating bucket {bucket_name} in region {region}")
                    s3.create_bucket(
                        Bucket=bucket_name,
                        CreateBucketConfiguration={
                            'LocationConstraint': region
                        }
                    )
                    logger.info(f"Bucket {bucket_name} created successfully")
                except Exception as bucket_create_error:
                    logger.error(f"Failed to create bucket: {str(bucket_create_error)}")
                    return
            else:
                # Some other error occurred
                logger.error(f"Error checking bucket: {str(e)}")
                return
        
        logger.info("Generating request parameters...")        
        # Generate request URLs and output file paths
        request_params = []
        
        # Get the current date and truncate to midnight
        today = datetime.utcnow()
        today_midnight = datetime(today.year, today.month, today.day, 0, 0, 0)
        
        # Calculate the start time (24 hours before midnight)
        start_time = today_midnight - timedelta(hours=24)
        end_time = today_midnight
        
        logger.info(f"Requesting data from {start_time} to {end_time}")
        
        for network in config["networks"]:
            for station in config["stations"]:
                for location in config["locations"]:
                    for channel in config["channels"]:
                        request_params.append((network, station, location, channel, 
                                              start_time, 
                                              end_time))
        
        logger.info(f"Generated {len(request_params)} request parameters")
        if request_params:
            logger.info(f"Sample request param: {request_params[0]}")
        else:
            logger.warning("No request params generated")
        
        # Make asynchronous requests to download data
        logger.info("Starting asynchronous data download...")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # Configure chunk size and buffer for optimal performance
            # Use 1-hour chunks with a 2-minute buffer on each side
            loop.run_until_complete(get_data(
                request_params, 
                config["zerotier_ips"], 
                data_dir=timestamp_folder,
                chunksize=timedelta(hours=1),  # Break 24-hour request into 1-hour chunks
                buffer=timedelta(seconds=120)  # Add 2-minute buffer to each chunk
            ))
        except Exception as e:
            logger.error(f"Error during asynchronous data download: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
        finally:
            loop.close()
            
        # Clean up the timestamp folder if it's empty
        try:
            if os.path.exists(timestamp_folder) and not os.listdir(timestamp_folder):
                os.rmdir(timestamp_folder)
                logger.info(f"Removed empty directory: {timestamp_folder}")
        except Exception as e:
            logger.warning(f"Failed to remove directory {timestamp_folder}: {str(e)}")
    except Exception as e:
        logger.error(f"Error in send_data_to_aws: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
    
    # Update the next run time to be exactly 24 hours from now
    next_run_time = datetime.now() + timedelta(days=1)  # Production: 1 day
    logger.info("================= DATA SEND OPERATION COMPLETE =================")
    logger.info(f"Next run scheduled for: {next_run_time}")

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/get-next-run-time")
def get_next_run_time():
    """Return the time until the next scheduled run in seconds"""
    # Calculate time until next run
    time_remaining = (next_run_time - datetime.now()).total_seconds()
    
    # Format the next run time for display
    next_run_formatted = next_run_time.strftime("%Y-%m-%d %H:%M:%S UTC")
    
    return jsonify({
        "next_run_seconds": max(0, time_remaining),
        "next_run_formatted": next_run_formatted,
        "zerotier_connected": zerotier_connected,
        "zerotier_status": zerotier_status
    })

@app.route("/trigger-manually", methods=["POST"])
def trigger_manually():
    """Manually trigger the data send function"""
    # Remove the VPN connection check to allow testing without VPN
    # if not zerotier_connected:
    #     return jsonify({
    #         "status": "error", 
    #         "message": f"ZeroTier not connected. Status: {zerotier_status}"
    #     })
    
    # Start the data send in a separate thread to avoid blocking the response
    threading.Thread(target=send_data_to_aws, daemon=True).start()
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
    logger.info("Starting ZeroTier connection attempt...")
    connect_to_zerotier()

# Start the connection process in a separate thread
threading.Thread(target=delayed_zerotier_connect, daemon=True).start()

# Initialize the scheduler
scheduler = BackgroundScheduler()
# Schedule the job to run at 00:05 UTC every day (5 minutes after midnight)
# This ensures we're collecting data for the previous day
scheduler.add_job(func=send_data_to_aws, trigger="cron", hour=0, minute=5)
scheduler.start()

def verify_s3_configuration():
    """Verify S3 bucket configuration and permissions"""
    try:
        logger.info("Verifying S3 configuration...")
        s3 = boto3.client('s3', region_name=region)
        
        # Check if bucket exists
        try:
            s3.head_bucket(Bucket=bucket_name)
            logger.info(f"Bucket {bucket_name} exists")
        except s3.exceptions.ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == '404':
                logger.error(f"Bucket {bucket_name} does not exist")
                return False
            elif error_code == '403':
                logger.error(f"Access denied to bucket {bucket_name}. Check permissions.")
                return False
            else:
                logger.error(f"Error checking bucket: {str(e)}")
                return False
        
        # Try to upload a small test file
        test_file_path = Path("s3_test.txt")
        try:
            with open(test_file_path, "w") as f:
                f.write("S3 test file")
            
            logger.info(f"Uploading test file to {bucket_name}/s3_test.txt")
            s3.upload_file(str(test_file_path), bucket_name, "s3_test.txt")
            logger.info("Test file uploaded successfully")
            
            # Clean up test file
            os.remove(test_file_path)
            logger.info("Test file deleted")
            
            return True
        except Exception as e:
            logger.error(f"Error uploading test file: {str(e)}")
            logger.error(f"Error details: {type(e).__name__}: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    except Exception as e:
        logger.error(f"Error verifying S3 configuration: {str(e)}")
        logger.error(f"Error details: {type(e).__name__}: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False

@app.route("/verify-s3", methods=["POST"])
def verify_s3():
    """Manually verify S3 configuration"""
    result = verify_s3_configuration()
    if result:
        return jsonify({
            "status": "success", 
            "message": "S3 configuration verified successfully"
        })
    else:
        return jsonify({
            "status": "error", 
            "message": "S3 configuration verification failed. Check logs for details."
        })