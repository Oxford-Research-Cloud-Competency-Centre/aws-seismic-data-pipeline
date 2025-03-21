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
    
    print(f"[DEBUG] Created request URL: {request}")
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
    
    print(f"[DEBUG] zerotier_ips: {zerotier_ips}")
    print(f"[DEBUG] request_params length: {len(request_params)}")
    if request_params:
        print(f"[DEBUG] Sample request_param: {request_params[0]}")
    
    for params in request_params:
        network, station, location, channel, start_time, end_time = params
        
        # Check if the station is in zerotier_ips
        if station not in zerotier_ips:
            print(f"[WARNING] Station {station} not found in zerotier_ips")
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
        
        # Create directory structure for year/month/day
        year = start_time.year
        month = start_time.month
        day = start_time.day
        hour = start_time.hour
        minute = start_time.minute
        second = start_time.second
        
        ddir = data_dir / f"{year}/{month:02d}/{day:02d}"
        ddir.mkdir(exist_ok=True, parents=True)
        
        # Format filename according to the same pattern used in data_pipeline.py
        seed_params = f'{network}.{station}.{location}.{channel}'
        timestamp = f'{year}{month:02d}{day:02d}T{hour:02d}{minute:02d}{second:02d}'
        outfile = ddir / f"{seed_params}.{timestamp}.mseed"
        
        # Check if the file already exists
        if outfile.is_file():
            print(f"File {outfile} already exists, skipping request")
            continue
            
        urls.append(request_url)
        outfiles.append(outfile)
        
    print(f"[DEBUG] Generated {len(urls)} URLs and outfiles")
    if urls:
        print(f"[DEBUG] Sample URL: {urls[0]}")
        print(f"[DEBUG] Sample outfile: {outfiles[0]}")
    
    return urls, outfiles

async def make_async_request(session, semaphore, request_url, outfile):
    """Make an async HTTP request and save the response to a file"""
    async with semaphore:
        try:
            print(f"Requesting: {request_url}")
            async with session.get(request_url) as resp:
                print(f'Request at {datetime.now()}')
                # Raise HTTP error for 4xx/5xx errors
                resp.raise_for_status()
                
                # Read binary data from the response
                data = await resp.read()
                if len(data) == 0:
                    print(f"[ERROR] Empty response for {request_url}. Won't write a zero byte file.")
                    return
                    
                # Now write data
                with open(outfile, "wb") as f:
                    f.write(data)
                print(f"Successfully wrote data to {outfile}")
                
        except aiohttp.ClientResponseError as e:
            print(f"[ERROR] Client error for {request_url}: {e}")
        except Exception as e:
            print(f"[ERROR] Unexpected error for {request_url}: {e}")

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
    
    print(f"Split {len(request_params)} original requests into {len(chunked_request_params)} chunked requests")
    
    # Generate URLs and output file paths for the chunked requests
    urls, outfiles = make_urls(zerotier_ips, chunked_request_params, data_dir)
    
    if not urls:
        print("[ERROR] No URLs generated for data fetching")
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
    
    # Make the requests
    async with aiohttp.ClientSession() as session:
        tasks = []
        for ip, reqs in requests_by_ip.items():
            semaphore = semaphores[ip]
            for request_url, outfile in reqs:
                # Skip if the file already exists
                if outfile.is_file():
                    print(f"File {outfile} already exists, skipping download")
                    continue
                
                task = asyncio.create_task(
                    make_async_request(session, semaphore, request_url, outfile)
                )
                tasks.append(task)
        
        if tasks:
            print(f"Starting {len(tasks)} download tasks")
            await asyncio.gather(*tasks)
            print("All download tasks completed")
        else:
            print("No download tasks to execute")

def send_data_to_aws():
    """
    Pull data and send it to AWS.
    Checks if a bucket exists, creates it if needed, downloads data and uploads to S3.
    """
    global next_run_time
    
    print("================= STARTING DATA SEND OPERATION =================")
    
    # Check if ZeroTier is connected before proceeding
    if not zerotier_connected:
        print("ZeroTier not connected, skipping data send")
        next_run_time = datetime.now() + timedelta(days=1)
        return
    
    try:
        # Create an S3 client
        print("Creating S3 client for region:", region)
        s3 = boto3.client('s3', region_name=region)
               
        # Generate timestamp folder for organizing files
        timestamp_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        timestamp_folder = f"data_{timestamp_str}"
        print(f"Using timestamp folder: {timestamp_folder}")
        
        # Check if bucket exists
        try:
            s3.head_bucket(Bucket=bucket_name)
            print(f"Bucket {bucket_name} already exists")
        except s3.exceptions.ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == '404':
                # Bucket doesn't exist, create it
                try:
                    print(f"Creating bucket {bucket_name} in region {region}")
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
        
        print("Generating request parameters...")        
        # Generate request URLs and output file paths
        request_params = []
        for network in config["networks"]:
            for station in config["stations"]:
                for location in config["locations"]:
                    for channel in config["channels"]:
                        # Get data for exactly the past 24 hours
                        end_time = datetime.utcnow()
                        start_time = end_time - timedelta(hours=24)
                        request_params.append((network, station, location, channel, 
                                              start_time, 
                                              end_time))
        
        print(f"Generated {len(request_params)} request parameters")
        print(f"Sample request param: {request_params[0] if request_params else 'No request params'}")
        
        # Make asynchronous requests to download data
        print("Starting asynchronous data download...")
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
            print(f"Error during asynchronous data download: {str(e)}")
            import traceback
            traceback.print_exc()
        finally:
            loop.close()
            
        # Check if there are any files to upload
        files_to_upload = list(Path(timestamp_folder).glob('**/*.mseed'))
        print(f"Found {len(files_to_upload)} files to upload")
        
        if not files_to_upload:
            print("No files were downloaded. Skipping S3 upload.")
            next_run_time = datetime.now() + timedelta(days=1)
            return
        
        # Upload downloaded files to S3
        uploaded_count = 0
        for file_path in files_to_upload:
            s3_key = str(file_path)  # Keep the same directory structure in S3
            print(f"Uploading {file_path} to {bucket_name}/{s3_key}")
            try:
                s3.upload_file(str(file_path), bucket_name, s3_key)
                print(f"Successfully uploaded file to {bucket_name}/{s3_key}")
                uploaded_count += 1
            except Exception as upload_error:
                print(f"Error uploading {file_path}: {str(upload_error)}")
        
        print(f"Uploaded {uploaded_count} out of {len(files_to_upload)} files to S3")
    except Exception as e:
        print(f"Error in send_data_to_aws: {str(e)}")
        import traceback
        traceback.print_exc()
    
    # Update the next run time
    next_run_time = datetime.now() + timedelta(days=1)  # Production: 1 day
    print("================= DATA SEND OPERATION COMPLETE =================")
    print(f"Next run scheduled for: {next_run_time}")

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
    print("Starting ZeroTier connection attempt...")
    connect_to_zerotier()

# Start the connection process in a separate thread
threading.Thread(target=delayed_zerotier_connect, daemon=True).start()

# Initialize the scheduler
scheduler = BackgroundScheduler()
scheduler.add_job(func=send_data_to_aws, trigger="interval", days=1)
scheduler.start()
