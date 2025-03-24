#!/usr/bin/env python3
import boto3
import json
import time

# Load config
with open("config.json") as f:
    config = json.load(f)

# Initialize AWS clients
ec2 = boto3.client('ec2', region_name='eu-west-2')
iam = boto3.client('iam')
sts = boto3.client('sts')

# Get account ID and image URI
account_id = sts.get_caller_identity()['Account']
repository = config["repository"]
service_name = config["service_name"]
image_uri = f"{account_id}.dkr.ecr.eu-west-2.amazonaws.com/{repository}:latest"

print(f"Deploying {image_uri} to Ubuntu EC2 with full AWS access...")

# Create IAM role with full AWS access
role_name = f"{service_name}-admin-role"
try:
    # Create the role
    assume_role_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "ec2.amazonaws.com"},
                "Action": "sts:AssumeRole"
            }
        ]
    }
    
    iam.create_role(
        RoleName=role_name,
        AssumeRolePolicyDocument=json.dumps(assume_role_policy)
    )
    
    # Attach AdministratorAccess policy for full access to all AWS services
    iam.attach_role_policy(
        RoleName=role_name,
        PolicyArn="arn:aws:iam::aws:policy/AdministratorAccess"
    )
    
    # Create instance profile and add role
    try:
        iam.create_instance_profile(InstanceProfileName=role_name)
    except iam.exceptions.EntityAlreadyExistsException:
        print(f"Instance profile {role_name} already exists")
    
    # Add role to instance profile if not already added
    try:
        iam.add_role_to_instance_profile(
            InstanceProfileName=role_name,
            RoleName=role_name
        )
    except iam.exceptions.LimitExceededException:
        print(f"Role already added to instance profile {role_name}")
        
    print(f"Created IAM role and instance profile with full AWS access: {role_name}")
    # Wait for role propagation
    print("Waiting for IAM role propagation...")
    time.sleep(15)
except Exception as e:
    print(f"Using existing IAM role: {role_name} - {str(e)}")

# Create security group
vpc_response = ec2.describe_vpcs(Filters=[{'Name': 'isDefault', 'Values': ['true']}])
vpc_id = vpc_response['Vpcs'][0]['VpcId']

sg_name = f"{service_name}-sg-full"
try:
    sg_response = ec2.create_security_group(
        GroupName=sg_name,
        Description=f"Web and SSH access for {service_name}",
        VpcId=vpc_id
    )
    sg_id = sg_response['GroupId']
    
    # Open port 8080 for web access
    ec2.authorize_security_group_ingress(
        GroupId=sg_id,
        IpPermissions=[
            {
                'IpProtocol': 'tcp',
                'FromPort': 8080,
                'ToPort': 8080,
                'IpRanges': [{'CidrIp': '0.0.0.0/0'}]
            }
        ]
    )
    
    # Open port 22 for SSH access
    ec2.authorize_security_group_ingress(
        GroupId=sg_id,
        IpPermissions=[
            {
                'IpProtocol': 'tcp',
                'FromPort': 22,
                'ToPort': 22,
                'IpRanges': [{'CidrIp': '0.0.0.0/0'}]
            }
        ]
    )
    
    print(f"Created security group: {sg_id}")
except Exception as e:
    # Get existing security group
    sg_response = ec2.describe_security_groups(
        Filters=[{'Name': 'group-name', 'Values': [sg_name]}]
    )
    sg_id = sg_response['SecurityGroups'][0]['GroupId']
    print(f"Using existing security group: {sg_id}")

# Create user data script for Ubuntu
user_data = f"""#!/bin/bash
# Update and install prerequisites
apt update -y
apt install -y apt-transport-https ca-certificates curl software-properties-common awscli

# Add Docker repository
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | apt-key add -
add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable"

# Install Docker
apt update -y
apt install -y docker-ce
systemctl start docker
systemctl enable docker

# Wait for AWS credentials to be available
sleep 60

# Explicitly authenticate with ECR before pulling
aws ecr get-login-password --region eu-west-2 | docker login --username AWS --password-stdin {account_id}.dkr.ecr.eu-west-2.amazonaws.com

# Pull and run the container
docker pull {image_uri}
docker run -d --name {service_name} -p 8080:8080 --restart always --privileged {image_uri}

# Create a status check file
echo "Container setup complete" > /tmp/container-setup-complete.log
"""

# Launch EC2 instance with your key pair and Ubuntu AMI
print("Launching Ubuntu EC2 instance...")
try:
    response = ec2.run_instances(
        ImageId='ami-0f540e9f488cfa27d',  # Ubuntu 20.04 LTS in eu-west-2
        InstanceType='t2.micro',
        MinCount=1,
        MaxCount=1,
        SecurityGroupIds=[sg_id],
        UserData=user_data,
        KeyName="vondermanzen-eu-west-2",  # Using your existing key pair
        IamInstanceProfile={'Name': role_name},
        TagSpecifications=[
            {
                'ResourceType': 'instance',
                'Tags': [
                    {
                        'Key': 'Name',
                        'Value': service_name
                    }
                ]
            }
        ]
    )
    
    instance_id = response['Instances'][0]['InstanceId']
    print(f"Instance launched: {instance_id}")
    
    # Wait for instance to be running
    print("Waiting for instance to start...")
    waiter = ec2.get_waiter('instance_running')
    waiter.wait(InstanceIds=[instance_id])
    
    # Get instance public IP
    instance_info = ec2.describe_instances(InstanceIds=[instance_id])
    public_ip = instance_info['Reservations'][0]['Instances'][0]['PublicIpAddress']
    
    print(f"\nDeployment complete!")
    print(f"Your application will be available at: http://{public_ip}:8080")
    print(f"You can SSH to troubleshoot: ssh ubuntu@{public_ip}")
    print(f"Note: It may take 5-10 minutes for the instance to fully initialize.")
    
except Exception as e:
    print(f"Error launching instance: {str(e)}")