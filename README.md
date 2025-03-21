# aws-seismic-data-pipeline

Porting https://github.com/Jasplet/seismic-data-pipeline to AWS

The dashboard: 

- Displays time until the next trigger 
- Has a button for manual trigger 
- Displays VPN authorization status 

![Dashboard](README_images/dashboard.png)

<details>
<summary><h2>Variables to adjust</h2></summary>

See in config.json: 
- S3 bucket name
- zero tier network id 
- repository name (ECR) 
- AWS service name

</details>

<details>
<summary><h2>Setup the AWS CLI</h2></summary>

<details>
<summary>Step 1. Install the AWS CLI on your local machine</summary>

https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html

***
</details>

<details>
<summary>Step 2. In the AWS Console, go to security credentials </summary>

![Security credentials](README_images/security_credentials.png)

***
</details>

<details>
<summary>Step 3. Create an access key </summary>

![Access key](README_images/create_access_key.png)

![Access key](README_images/access_key.png)

***
</details>

<details>
<summary>Step 4. Configure AWS on your local machine</summary>

Command: aws configure

![Access key](README_images/aws_configure.png)

***
</details>
</details>


<details>
<summary><h2>Upload the app to Elastic Container Registry</h2></summary>

<details>
<summary>Step 1. Install Python on your local machine </summary>

https://www.python.org/downloads/

***
</details>

<details>
<summary>Step 2. Install Docker on your local machine </summary>

https://www.docker.com/get-started/

***
</details>

<details>
<summary>Step 3. Run script upload_ecr_image.py </summary>

![Access key](README_images/upload_ecr_image.png)

***
</details>

<details>
<summary>Step 4. In the AWS Console search bar, type "ecr" </summary>

![Access key](README_images/search_ecr.png)

***
</details>

<details>
<summary>Step 5. Check that the repository appears </summary>

![ECR repository](README_images/ecr_repositories.png)

***
</details>

</details>


<details>
<summary><h2>Creating the service</h2></summary>

Run create_service.py

</details>

<details>
<summary><h2>Connect to VPN</h2></summary>

The service will automatically attempt to join the VPN. 

Login to zerotier.com and authorize it. 

![VPN](README_images/vpn.png)

</details>

