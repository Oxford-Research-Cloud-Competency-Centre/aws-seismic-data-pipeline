#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# © The Chancellor, Masters and Scholars of The University of Oxford. All rights reserved.

# Default configuration variables
REGION = "eu-west-2"
REPOSITORY = "hello-aws"
TAG = "latest"
SERVICE_NAME = "hello-aws"
CPU = "1 vCPU"
MEMORY = "2 GB"

import subprocess
import sys
import time
import json

def run_command(command, check=True, silent=False):
    """Run a shell command and return the output."""
    if not silent:
        print(f"Running: {command}")
    result = subprocess.run(command, shell=True, check=check, text=True, capture_output=True)
    if result.stdout and not silent:
        print(result.stdout)
    if result.stderr and not silent:
        print(result.stderr, file=sys.stderr)
    return result

def get_account_id():
    """Get the AWS account ID."""
    account_id_cmd = "aws sts get-caller-identity --query Account --output text"
    account_id_result = run_command(account_id_cmd)
    return account_id_result.stdout.strip()

def create_app_runner_service():
    """Create an AWS App Runner service using the ECR image."""
    # Get AWS account ID
    account_id = get_account_id()
    
    # ECR image URI
    image_uri = f"{account_id}.dkr.ecr.{REGION}.amazonaws.com/{REPOSITORY}:{TAG}"
    
    print(f"Creating App Runner service: {SERVICE_NAME}")
    print(f"Using ECR image: {image_uri}")
    
    try:
        # Check if service already exists using AWS CLI
        list_cmd = f"aws apprunner list-services --region {REGION} --output json"
        list_result = run_command(list_cmd, silent=True)
        services = json.loads(list_result.stdout)
        
        # Check if service with our name exists
        service_arn = None
        for service in services.get('ServiceSummaryList', []):
            if service['ServiceName'] == SERVICE_NAME:
                service_arn = service['ServiceArn']
                describe_cmd = f"aws apprunner describe-service --service-arn \"{service_arn}\" --region {REGION} --output json"
                describe_result = run_command(describe_cmd)
                service_details = json.loads(describe_result.stdout)
                print(f"Service {SERVICE_NAME} already exists. Service ARN: {service_arn}")
                print(f"Service URL: {service_details['Service']['ServiceUrl']}")
                return service_arn
        
        # Create the service using AWS CLI
        create_cmd = (
            f"aws apprunner create-service "
            f"--service-name {SERVICE_NAME} "
            f"--source-configuration \"{{\\\"ImageRepository\\\":{{\\\"ImageIdentifier\\\":\\\"{image_uri}\\\",\\\"ImageConfiguration\\\":{{\\\"Port\\\":\\\"8080\\\"}},\\\"ImageRepositoryType\\\":\\\"ECR\\\"}},\\\"AutoDeploymentsEnabled\\\":true,\\\"AuthenticationConfiguration\\\":{{\\\"AccessRoleArn\\\":\\\"arn:aws:iam::{account_id}:role/service-role/AppRunnerECRAccessRole\\\"}}}}\" "
            f"--instance-configuration \"{{\\\"Cpu\\\":\\\"{CPU}\\\",\\\"Memory\\\":\\\"{MEMORY}\\\"}}\" "
            f"--region {REGION} "
            f"--output json"
        )
        
        create_result = run_command(create_cmd)
        service_details = json.loads(create_result.stdout)
        service_arn = service_details['Service']['ServiceArn']
        print(f"Service creation initiated. Service ARN: {service_arn}")
        
        # Wait for the service to be created
        print("Waiting for service to be created (this may take a few minutes)...")
        while True:
            describe_cmd = f"aws apprunner describe-service --service-arn \"{service_arn}\" --region {REGION} --output json"
            describe_result = run_command(describe_cmd, silent=True)
            status = json.loads(describe_result.stdout)['Service']['Status']
            if status == "RUNNING":
                break
            elif status in ["CREATE_FAILED", "DELETE_FAILED", "OPERATION_IN_PROGRESS"]:
                print(f"Service creation failed with status: {status}")
                return None
            print(f"Current status: {status}. Waiting...")
            time.sleep(30)
        
        # Get the service URL
        describe_cmd = f"aws apprunner describe-service --service-arn \"{service_arn}\" --region {REGION} --output json"
        describe_result = run_command(describe_cmd)
        service_details = json.loads(describe_result.stdout)
        service_url = service_details['Service']['ServiceUrl']
        print(f"Service created successfully!")
        print(f"Service URL: https://{service_url}")
        
        return service_arn
    
    except Exception as e:
        print(f"Error creating App Runner service: {e}")
        return None

def main():
    print("Creating AWS App Runner service from ECR image...")
    
    # Create the App Runner service
    service_arn = create_app_runner_service()
    
    if service_arn:
        print("\nService creation completed successfully.")
        print("\nYou can now access your service at the URL provided above.")
        print("To delete this service when you're done, use the AWS Console or run:")
        print(f"aws apprunner delete-service --service-arn {service_arn}")
    else:
        print("\nService creation failed. Please check the error messages above.")

if __name__ == "__main__":
    main()