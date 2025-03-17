#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# © The Chancellor, Masters and Scholars of The University of Oxford. All rights reserved.

# Default configuration variables
REGION = "eu-west-2"
REPOSITORY = "hello-aws"
TAG = "latest"

import os
import subprocess
import sys

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

def create_ecr_repository():
    """Create an ECR repository if it doesn't exist."""
    # Check if repository exists
    check_repo_cmd = f"aws ecr describe-repositories --repository-names {REPOSITORY} --region {REGION} 2>/dev/null"
    result = run_command(check_repo_cmd, check=False)
    
    if result.returncode != 0:
        print(f"Creating ECR repository: {REPOSITORY}")
        create_cmd = f"aws ecr create-repository --repository-name {REPOSITORY} --region {REGION}"
        run_command(create_cmd)
    else:
        print(f"ECR repository {REPOSITORY} already exists")

def get_ecr_login():
    """Get ECR login command and execute it."""
    # Get AWS account ID first
    account_id_cmd = "aws sts get-caller-identity --query Account --output text"
    account_id_result = run_command(account_id_cmd)
    account_id = account_id_result.stdout.strip()
    
    # Get ECR password (silently to avoid displaying the password)
    password_cmd = f"aws ecr get-login-password --region {REGION}"
    password_result = run_command(password_cmd, silent=True)
    password = password_result.stdout.strip()
    
    # Login to Docker (using password-stdin for security)
    print(f"Running: docker login --username AWS --password-stdin {account_id}.dkr.ecr.{REGION}.amazonaws.com")
    login_process = subprocess.run(
        f"echo {password} | docker login --username AWS --password-stdin {account_id}.dkr.ecr.{REGION}.amazonaws.com",
        shell=True, check=True, text=True, capture_output=True
    )
    if login_process.stdout:
        print(login_process.stdout)
    if login_process.stderr:
        print(login_process.stderr, file=sys.stderr)

def build_and_push_image():
    """Build Docker image and push to ECR."""
    # Get AWS account ID
    account_id_cmd = "aws sts get-caller-identity --query Account --output text"
    account_id = run_command(account_id_cmd).stdout.strip()
    
    # Track if we created a temporary Dockerfile
    dockerfile_created = False
    
    # Create Dockerfile temporarily if it doesn't exist
    if not os.path.exists("Dockerfile"):
        print("Creating temporary Dockerfile...")
        with open("Dockerfile", "w") as f:
            f.write("FROM python:3.11-slim\n")
            f.write("WORKDIR /app\n")
            f.write("COPY requirements.txt .\n")
            f.write("RUN pip install --no-cache-dir -r requirements.txt\n")
            f.write("COPY . .\n")
            f.write("EXPOSE 8080\n")
            f.write("CMD [\"python\", \"-m\", \"gunicorn\", \"--bind\", \"0.0.0.0:8080\", \"app:app\"]\n")
        dockerfile_created = True
    
    try:
        # Build the Docker image
        image_uri = f"{account_id}.dkr.ecr.{REGION}.amazonaws.com/{REPOSITORY}:{TAG}"
        build_cmd = f"docker build -t {image_uri} ."
        run_command(build_cmd)
        
        # Push the image to ECR
        push_cmd = f"docker push {image_uri}"
        run_command(push_cmd)
        
        return image_uri
    finally:
        # Clean up temporary Dockerfile if we created it
        if dockerfile_created and os.path.exists("Dockerfile"):
            print("Removing temporary Dockerfile...")
            os.remove("Dockerfile")

def main():
    # Authenticate with ECR
    get_ecr_login()
    
    # Create repository if it doesn't exist
    create_ecr_repository()
    
    # Build and push the image
    image_uri = build_and_push_image()
    
    print(f"\nSuccessfully built and pushed image: {image_uri}")
    print("\nYou can now use this image in your AWS App Runner service or other AWS services.")

if __name__ == "__main__":
    main()
