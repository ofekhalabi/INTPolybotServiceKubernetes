import json
import boto3
import paramiko
import subprocess

# AWS clients
ec2_client = boto3.client("ec2")
secrets_client = boto3.client("secretsmanager")

def get_control_plane_ip(instance_id):
    """Retrieve the Public or Private IP of the Control Plane."""
    try:
        response = ec2_client.describe_instances(InstanceIds=[instance_id])
        instance = response['Reservations'][0]['Instances'][0]

        public_ip = instance.get("PublicIpAddress")
        private_ip = instance.get("PrivateIpAddress")

        if public_ip:
            print(f"✅ Using Public IP: {public_ip}")
            return public_ip
        else:
            print(f"✅ No Public IP found. Using Private IP: {private_ip}")
            return private_ip
    except Exception as e:
        print(f"🔴 Error retrieving Control Plane IP: {e}")
        return None

# define the control plane details
CONTROL_PLANE_INSTANCE_ID = "i-0cde49ef5984afb9e"  
CONTROL_PLANE_IP = get_control_plane_ip(CONTROL_PLANE_INSTANCE_ID)
CONTROL_PLANE_USER = "ubuntu"

def get_private_key():
    """Retrieve private SSH key from AWS Secrets Manager."""
    try:
        secret_response = secrets_client.get_secret_value(SecretId="ofekh-control-plane-key")
        private_key_data = secret_response["SecretString"]

        # Save key to a temporary file
        key_path = "/tmp/control-plane-key.pem"
        with open(key_path, "w") as key_file:
            key_file.write(private_key_data)
        subprocess.run(["chmod", "400", key_path])  # Set correct permissions

        return key_path
    except Exception as e:
        print(f"🔴 Error retrieving SSH key: {e}")
        return None

def generate_kubeadm_token():
    """Generate a fresh Kubernetes join token on the Control Plane."""
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    private_key_path = get_private_key()
    if not private_key_path:
        return None

    try:
        private_key = paramiko.RSAKey(filename=private_key_path)
        ssh.connect(CONTROL_PLANE_IP, username=CONTROL_PLANE_USER, pkey=private_key)
        stdin, stdout, stderr = ssh.exec_command("sudo kubeadm token create --print-join-command")
        join_command = stdout.read().decode().strip()
        ssh.close()
        return join_command
    except Exception as e:
        print(f"🔴 Error generating token: {e}")
        return None

def run_join_command(instance_id, join_command):
    """SSH into the worker node and run the join command."""
    try:
        response = ec2_client.describe_instances(InstanceIds=[instance_id])
        worker_ip = response['Reservations'][0]['Instances'][0]['PrivateIpAddress']
    except Exception as e:
        print(f"🔴 Error fetching worker IP: {e}")
        return

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    private_key_path = get_private_key()
    if not private_key_path:
        return

    try:
        private_key = paramiko.RSAKey(filename=private_key_path)
        ssh.connect(worker_ip, username="ubuntu", pkey=private_key)
        stdin, stdout, stderr = ssh.exec_command(f"sudo {join_command}")
        print(stdout.read().decode())
        ssh.close()
    except Exception as e:
        print(f"🔴 Error joining worker node: {e}")

def remove_worker_node(node_name):
    """Drain and remove a worker node from Kubernetes."""
    try:
        subprocess.run(["kubectl", "cordon", node_name], check=True)
        subprocess.run(["kubectl", "drain", node_name, "--ignore-daemonsets", "--delete-emptydir-data", "--force"], check=True)
        subprocess.run(["kubectl", "delete", "node", node_name], check=True)
        print(f"✅ Successfully removed worker node: {node_name}")
    except subprocess.CalledProcessError as e:
        print(f"🔴 Error removing node {node_name}: {e}")

def lambda_handler(event, context):
    print("Lambda handler started")
    print(f"Event: {json.dumps(event)}")
    sns_message = json.loads(event['Records'][0]['Sns']['Message'])
    instance_id = sns_message.get("EC2InstanceId", "Unknown")
    lifecycle_transition = sns_message.get("LifecycleTransition", "Unknown")
    print (f"Lifecycle Transition: {lifecycle_transition}")

    if "EC2_INSTANCE_LAUNCHING" in lifecycle_transition:
        print(f"New worker node detected: {instance_id}")

        join_command = generate_kubeadm_token() 
        if not join_command:
            return {"statusCode": 500, "body": "Failed to generate join token"}

        print(f"🔹 Join Command: {join_command}")
        run_join_command(instance_id, join_command)

    elif "EC2_INSTANCE_TERMINATING" in lifecycle_transition:
        print(f"Worker node terminating: {instance_id}")
        try:
            response = ec2_client.describe_instances(InstanceIds=[instance_id])
            node_name = response['Reservations'][0]['Instances'][0]['PrivateDnsName']
            print (f"Node name: {node_name}")
            remove_worker_node(node_name)
        except Exception as e:
            print(f"Error removing node: {e}")


    return {"statusCode": 200, "body": "Worker node processed successfully"}
