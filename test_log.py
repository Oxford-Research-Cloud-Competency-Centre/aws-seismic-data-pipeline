import boto3
import time

logs = boto3.client('logs', region_name='eu-west-2')
log_group_name = "hello-aws-logs"

# Add a test log event
logs.put_log_events(
    logGroupName=log_group_name,
    logStreamName='test-stream',
    logEvents=[
        {
            'timestamp': int(1000 * time.time()),
            'message': 'Test log message'
        }
    ]
)