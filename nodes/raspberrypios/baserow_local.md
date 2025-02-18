# Self-host Baserow


Confirm CPU architecture
dpkg --print-architecture
armhf
arm64

https://docs.docker.com/engine/install/raspberry-pi-os/#install-using-the-repository

```bash
# Add Docker's official GPG key:
sudo apt-get update
sudo apt-get install ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/raspbian/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

# Add the repository to Apt sources:
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/raspbian \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update

sudo apt-get install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```
https://download.docker.com/linux/raspbian/dists/bookworm/pool/stable/armhf/

https://download.docker.com/linux/debian/dists/bookworm/pool/stable/arm64/

```bash
sudo dpkg -i /home/fullstackfood/Downloads/libip6tc2_1.8.9-2_arm64.deb

sudo dpkg -i /home/fullstackfood/Downloads/iptables_1.8.9-2_arm64.deb

sudo dpkg -i /home/fullstackfood/Downloads/containerd.io_1.7.25-1_arm64.deb /home/fullstackfood/Downloads/docker-buildx-plugin_0.20.0-1~debian.12~bookworm_arm64.deb /home/fullstackfood/Downloads/docker-ce_27.5.1-1~debian.12~bookworm_arm64.deb /home/fullstackfood/Downloads/docker-ce-cli_27.5.1-1~debian.12~bookworm_arm64.deb /home/fullstackfood/Downloads/docker-ce-rootless-extras_27.5.1-1~debian.12~bookworm_arm64.deb /home/fullstackfood/Downloads/docker-compose-plugin_2.32.4-1~debian.12~bookworm_arm64.deb

```

https://baserow.io/docs/installation/install-on-ubuntu
```bash
# Ensure your system is upto date
sudo apt update
# Docker Setup
sudo apt install docker
# Your user must be in the Docker group to run docker commands
sudo usermod -aG docker $USER
# Refresh the group so you don't need to relog to get docker permissions
newgrp docker 
# Change BASEROW_PUBLIC_URL to your domain name or http://YOUR_SERVERS_IP if you want
# to access Baserow remotely.
# This command will run Baserow with it's data stored in the new baserow_data docker 
# volume.
docker run -e BASEROW_PUBLIC_URL=http://localhost \
--name baserow \
-d \
--restart unless-stopped \
-v baserow_data:/baserow/data \
-p 80:80 \
-p 443:443 \
baserow/baserow:1.31.1
# Watch the logs for Baserow to come available by running:
docker logs baserow
```


https://caddyserver.com/docs/automatic-https
