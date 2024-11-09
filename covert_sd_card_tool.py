#!/usr/bin/env python3

import argparse
import subprocess
import sys
import os
import shutil
from datetime import datetime
import platform
import urllib.request
import tarfile
import time
import json

# Global variables
DEBUG = False
FAST_MODE = False
TIMESTAMP = datetime.now().strftime('%Y%m%d_%H%M%S')
LOG_FILE = f"covert_sd_setup_{TIMESTAMP}.log"
CREATE_KALI = False
CREATE_DOCS = False
CREATE_TAILS = False
KALI_ISO = ""
TAILS_ISO = ""
DRIVE = ""

def log(message):
    with open(LOG_FILE, "a") as log_file:
        log_file.write(message + "\n")
    print(message)

def run_command(command, shell=False, interactive=False):
    if DEBUG:
        log(f"Running command: {command}")
    try:
        if interactive:
            subprocess.run(command, shell=shell, check=True)
        else:
            result = subprocess.run(
                command,
                shell=shell,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True
            )
            if result.stdout:
                log(result.stdout.strip())
            if result.stderr:
                log(result.stderr.strip())
    except subprocess.CalledProcessError as e:
        log(f"Command failed: {e}\nOutput: {e.stdout}\nError: {e.stderr}")
        sys.exit(1)

def check_dependencies():
    dependencies = ["parted", "cryptsetup", "lsblk", "dd", "sgdisk", "wipefs", "bc", "fdisk"]
    missing = []
    for dep in dependencies:
        if not shutil.which(dep):
            missing.append(dep)
    if missing:
        log(f"Missing dependencies: {', '.join(missing)}")
        install = input(f"Do you want to install the missing dependencies? (y/n) [Default: y]: ") or "y"
        if install.lower() == "y":
            run_command(["sudo", "apt", "update"])
            run_command(["sudo", "apt", "install", "-y"] + missing)
        else:
            log("Cannot proceed without installing dependencies. Exiting.")
            sys.exit(1)

def list_drives():
    log("Available drives:")
    result = subprocess.run(["lsblk", "-J", "-o", "NAME,SIZE,TYPE"], capture_output=True, text=True)
    lsblk_output = json.loads(result.stdout)
    for device in lsblk_output['blockdevices']:
        if device['type'] == 'disk':
            name = device['name']
            size = device['size']
            drive = f"/dev/{name} {size}"
            log(drive)

def get_partition_name(drive, partition_number):
    if 'nvme' in drive or 'mmcblk' in drive:
        return f"{drive}p{partition_number}"
    else:
        return f"{drive}{partition_number}"

def prepare_drive(drive):
    result = subprocess.run(["lsblk", "-lnp", drive], capture_output=True, text=True)
    for line in result.stdout.strip().splitlines():
        parts = line.strip().split()
        if len(parts) >= 7 and parts[6]:  # If mountpoint is not empty
            part = parts[0]
            log(f"Unmounting {part}...")
            run_command(["sudo", "umount", "-l", part])

    with open("/proc/swaps") as swaps_file:
        for line in swaps_file:
            if drive in line:
                swap_part = line.strip().split()[0]
                log(f"Disabling swap on {swap_part}...")
                run_command(["sudo", "swapoff", swap_part])

    log(f"Checking for processes using {drive}...")
    result = subprocess.run(["sudo", "lsof", drive], capture_output=True, text=True)
    if result.stdout.strip():
        log(f"Processes using {drive}:\n{result.stdout}")
        kill = input(f"Do you want to kill these processes? (y/n) [Default: y]: ") or "y"
        if kill.lower() == "y":
            run_command(f"sudo fuser -k {drive}", shell=True)
            log(f"Killed processes using {drive}.")
        else:
            log("Cannot proceed while processes are using the drive. Exiting.")
            sys.exit(1)
    else:
        log(f"No processes are using {drive}.")

def setup_usb():
    global DRIVE
    log("Setting up bootable USB...")
    list_drives()
    DRIVE = input("Enter the drive to use for USB (e.g., /dev/sda) [Default: /dev/sda]: ") or "/dev/sda"

    confirm = input(f"You have selected {DRIVE}. Is this correct? (y/n) [Default: y]: ") or "y"
    if confirm.lower() != "y":
        log("Drive selection canceled. Exiting.")
        sys.exit(1)

    prepare_drive(DRIVE)
    wipe = input(f"Do you want to wipe the drive {DRIVE} before starting? (y/n) [Default: n]: ") or "n"
    if wipe.lower() == "y":
        log(f"Wiping {DRIVE} and clearing any existing file system or encryption signatures...")
        run_command(["sudo", "wipefs", "--all", DRIVE])
        run_command(["sudo", "sgdisk", "--zap-all", DRIVE])
        run_command(["sudo", "dd", "if=/dev/zero", f"of={DRIVE}", "bs=1M", "count=10"])
        log(f"{DRIVE} wiped successfully.")

    global KALI_ISO
    if CREATE_KALI:
        if not KALI_ISO:
            KALI_ISO = input("Enter the path to the Kali ISO file: ")
        if not os.path.isfile(KALI_ISO):
            log(f"Error: Kali ISO file not found at {KALI_ISO}")
            sys.exit(1)
        ISO_PATH = KALI_ISO
    else:
        log("No OS selected for installation. Exiting.")
        sys.exit(1)

    log(f"Writing ISO to {DRIVE}...")
    run_command(f"sudo dd if='{ISO_PATH}' of='{DRIVE}' bs=64M status=progress", shell=True, interactive=True)
    log(f"ISO written to {DRIVE} successfully.")

    if CREATE_KALI:
        fix_partition_table()
    else:
        log("Only basic setup is performed. Exiting.")
        sys.exit(1)

def fix_partition_table():
    log("Fixing partition table to reclaim remaining space...")

    run_command(f"sudo parted -a optimal -s {DRIVE} rm 2", shell=True)
    log("Deleted partition 2.")

    result = subprocess.run(["sudo", "parted", "-s", DRIVE, "unit", "MB", "print"], capture_output=True, text=True)
    end_of_p1 = None
    for line in result.stdout.strip().splitlines():
        if line.strip().startswith("1"):
            parts = line.strip().split()
            end_of_p1 = parts[2]
            break
    if end_of_p1 is None:
        log("Error: Could not find end of partition 1.")
        sys.exit(1)

    log(f"End of partition 1: {end_of_p1}")

    result = subprocess.run(["lsblk", "-bn", "-o", "SIZE", DRIVE], capture_output=True, text=True)
    sizes = result.stdout.strip().splitlines()
    total_size_bytes = int(sizes[0].strip())
    total_size_mb = total_size_bytes / (1024 * 1024)

    size_persistence = input("Enter size for persistence partition in GB (e.g., 4): ") or "4"
    try:
        size_persistence_gb = float(size_persistence)
    except ValueError:
        log("Invalid size entered for persistence partition. Exiting.")
        sys.exit(1)

    start_persistence_mb = float(end_of_p1.replace('MB', ''))
    end_persistence_mb = start_persistence_mb + (size_persistence_gb * 1024)

    if end_persistence_mb > total_size_mb:
        log("Error: Persistence partition size exceeds available space.")
        sys.exit(1)

    run_command(f"sudo parted -a optimal -s {DRIVE} mkpart primary {start_persistence_mb}MB {end_persistence_mb}MB", shell=True)
    log("Created persistence partition.")

    start_docs_mb = end_persistence_mb

    size_docs = input("Enter size for documents partition in GB (leave blank to use remaining space minus 1GB): ")
    if size_docs:
        try:
            size_docs_gb = float(size_docs)
            end_docs_mb = start_docs_mb + (size_docs_gb * 1024)
            if end_docs_mb > total_size_mb - 1024:
                log("Error: Documents partition size exceeds available space when reserving 1GB for unencrypted partition.")
                sys.exit(1)
        except ValueError:
            log("Invalid size entered for documents partition. Exiting.")
            sys.exit(1)
    else:
        end_docs_mb = total_size_mb - 1024

    run_command(f"sudo parted -a optimal -s {DRIVE} mkpart primary {start_docs_mb}MB {end_docs_mb}MB", shell=True)
    log("Created documents partition.")

    start_unencrypted_mb = end_docs_mb
    run_command(f"sudo parted -a optimal -s {DRIVE} mkpart primary {start_unencrypted_mb}MB 100%", shell=True)
    log("Created unencrypted partition for scripts/instructions.")

    run_command(f"sudo partprobe {DRIVE}", shell=True)
    time.sleep(2)

    setup_kali_partition()
    if CREATE_DOCS:
        setup_docs_partition()
    setup_unencrypted_partition()

def fix_partition_table_tails():
    log("Fixing partition table to reclaim remaining space...")

    run_command(f"sudo parted -a optimal -s {DRIVE} rm 2", shell=True)
    log("Deleted partition 2.")

    result = subprocess.run(["sudo", "parted", "-s", DRIVE, "unit", "MB", "print"], capture_output=True, text=True)
    end_of_p1 = None
    for line in result.stdout.strip().splitlines():
        if line.strip().startswith("1"):
            parts = line.strip().split()
            end_of_p1 = parts[2]
            break
    if end_of_p1 is None:
        log("Error: Could not find end of partition 1.")
        sys.exit(1)

    log(f"End of partition 1: {end_of_p1}")

    result = subprocess.run(["lsblk", "-bn", "-o", "SIZE", DRIVE], capture_output=True, text=True)
    sizes = result.stdout.strip().splitlines()
    total_size_bytes = int(sizes[0].strip())
    total_size_mb = total_size_bytes / (1024 * 1024)

    start_docs_mb = float(end_of_p1.replace('MB', ''))
    end_docs_mb = start_docs_mb + (size_docs_gb * 1024)

    size_docs = input("Enter size for documents partition in GB (leave blank to use remaining space minus 1GB): ")
    if size_docs:
        try:
            size_docs_gb = float(size_docs)
            end_docs_mb = start_docs_mb + (size_docs_gb * 1024)
            if end_docs_mb > total_size_mb - 1024:
                log("Error: Documents partition size exceeds available space when reserving 1GB for unencrypted partition.")
                sys.exit(1)
        except ValueError:
            log("Invalid size entered for documents partition. Exiting.")
            sys.exit(1)
    else:
        end_docs_mb = total_size_mb - 1024

    run_command(f"sudo parted -a optimal -s {DRIVE} mkpart primary {start_docs_mb}MB {end_docs_mb}MB", shell=True)
    log("Created documents partition.")

    start_unencrypted_mb = end_docs_mb
    run_command(f"sudo parted -a optimal -s {DRIVE} mkpart primary {start_unencrypted_mb}MB 100%", shell=True)
    log("Created unencrypted partition for scripts/instructions.")

    run_command(f"sudo partprobe {DRIVE}", shell=True)
    time.sleep(2)

    setup_kali_partition()
    if CREATE_DOCS:
        setup_docs_partition()
    setup_unencrypted_partition()

def setup_kali_partition():
    global DRIVE
    PERSIST_PART = get_partition_name(DRIVE, 2)

    # Wipe existing signatures on the partition
    run_command(["sudo", "wipefs", "--all", PERSIST_PART])

    log("Configuring encrypted persistence partition...")

    if FAST_MODE:
        luks_format_cmd = (
            f"sudo cryptsetup luksFormat '{PERSIST_PART}' "
            f"--type luks1 "
            f"--cipher aes-cbc-essiv:sha256 "
            f"--key-size 256 "
            f"--hash sha256 "
            f"--iter-time 1000"
        )
        mkfs_cmd = f"sudo mkfs.ext3 -L persistence /dev/mapper/kali_USB"
    else:
        luks_format_cmd = (
            f"sudo cryptsetup luksFormat '{PERSIST_PART}' "
            f"--cipher aes-xts-plain64 "
            f"--key-size 512 "
            f"--hash sha512 "
            f"--iter-time 5000"
        )
        mkfs_cmd = f"sudo mkfs.ext4 -L persistence /dev/mapper/kali_USB"

    run_command(luks_format_cmd, shell=True, interactive=True)
    time.sleep(2)
    run_command(f"sudo cryptsetup luksOpen '{PERSIST_PART}' kali_USB", shell=True, interactive=True)
    run_command(mkfs_cmd, shell=True)

    run_command("sudo mkdir -p /mnt/kali_USB", shell=True)
    run_command("sudo mount /dev/mapper/kali_USB /mnt/kali_USB", shell=True)
    run_command('echo "/ union" | sudo tee /mnt/kali_USB/persistence.conf', shell=True)
    run_command("sudo umount /mnt/kali_USB", shell=True)
    run_command("sudo cryptsetup luksClose kali_USB", shell=True)

    log("Kali persistence setup complete.")

def setup_docs_partition():
    global DRIVE
    DOCS_PART = get_partition_name(DRIVE, 3)

    # Wipe existing signatures on the partition
    run_command(["sudo", "wipefs", "--all", DOCS_PART])

    log("Configuring VeraCrypt encryption for documents partition...")

    if FAST_MODE:
        veracrypt_create_cmd = (
            f"veracrypt --text --create '{DOCS_PART}' "
            f"--encryption AES "
            f"--hash SHA-256 "
            f"--filesystem exfat "
            f"--volume-type normal "
            f"--quick "
        )
    else:
        veracrypt_create_cmd = (
            f"veracrypt --text --create '{DOCS_PART}' "
            f"--encryption AES-Twofish-Serpent "
            f"--hash whirlpool "
            f"--filesystem exfat "
            f"--volume-type normal "
        )

    run_command(veracrypt_create_cmd, shell=True, interactive=True)
    log("Encrypted documents partition setup complete.")

def setup_unencrypted_partition():
    global DRIVE
    UNENCRYPTED_PART = get_partition_name(DRIVE, 4)

    # Format the partition with FAT32
    run_command(f"sudo mkfs.vfat -n 'TOOLS' {UNENCRYPTED_PART}", shell=True)
    log("Formatted unencrypted partition with FAT32 filesystem.")

    run_command("sudo mkdir -p /mnt/unencrypted", shell=True)
    run_command(f"sudo mount {UNENCRYPTED_PART} /mnt/unencrypted", shell=True)

    instructions = f"""
To mount the encrypted documents partition:

1. Open a terminal.
2. Run: sudo veracrypt --text --mount {get_partition_name(DRIVE, 3)} /mnt/veracrypt_docs

**Automount Script:**
You can use the provided script 'mount_encrypted_partitions.sh' to automate this process.

Usage:
sudo ./mount_encrypted_partitions.sh

**Cleanup Script:**
To unmount and lock the encrypted documents partition, run:
sudo ./cleanup_encrypted_partitions.sh
"""

    # Write README.txt
    with open("/tmp/README.txt", "w") as readme_file:
        readme_file.write(instructions)
    run_command("sudo cp /tmp/README.txt /mnt/unencrypted/README.txt", shell=True)
    run_command("sudo rm /tmp/README.txt", shell=True)
    log("Created README.txt with mounting instructions.")

    # Write mount script for documents partition
    mount_script = f"""#!/bin/bash
# Script to mount encrypted documents partition

if [ -b "{get_partition_name(DRIVE, 3)}" ]; then
    echo "Mounting VeraCrypt documents partition..."
    sudo mkdir -p /mnt/veracrypt_docs
    sudo veracrypt --text --mount {get_partition_name(DRIVE, 3)} /mnt/veracrypt_docs
    echo "Documents partition mounted at /mnt/veracrypt_docs."
else
    echo "Documents partition not found."
fi
"""

    with open("/tmp/mount_encrypted_partitions.sh", "w") as script_file:
        script_file.write(mount_script)
    run_command("sudo cp /tmp/mount_encrypted_partitions.sh /mnt/unencrypted/mount_encrypted_partitions.sh", shell=True)
    run_command("sudo chmod +x /mnt/unencrypted/mount_encrypted_partitions.sh", shell=True)
    run_command("sudo rm /tmp/mount_encrypted_partitions.sh", shell=True)
    log("Created mount_encrypted_partitions.sh script.")

    # Write cleanup script for documents partition
    cleanup_script = """#!/bin/bash
# Script to unmount and lock encrypted documents partition

echo "Unmounting and locking encrypted documents partition..."

if mountpoint -q /mnt/veracrypt_docs; then
    echo "Unmounting VeraCrypt documents partition..."
    sudo veracrypt --text --dismount /mnt/veracrypt_docs
    echo "VeraCrypt documents partition unmounted."
else
    echo "Documents partition is not mounted."
fi

echo "Cleanup complete. Encrypted documents partition is locked and unmounted."
"""

    with open("/tmp/cleanup_encrypted_partitions.sh", "w") as script_file:
        script_file.write(cleanup_script)
    run_command("sudo cp /tmp/cleanup_encrypted_partitions.sh /mnt/unencrypted/cleanup_encrypted_partitions.sh", shell=True)
    run_command("sudo chmod +x /mnt/unencrypted/cleanup_encrypted_partitions.sh", shell=True)
    run_command("sudo rm /tmp/cleanup_encrypted_partitions.sh", shell=True)
    log("Created cleanup_encrypted_partitions.sh script.")

    run_command("sudo umount /mnt/unencrypted", shell=True)
    log("Unencrypted partition setup complete.")

def main():
    global DEBUG, FAST_MODE, CREATE_KALI, CREATE_DOCS, CREATE_TAILS, KALI_ISO, TAILS_ISO, DRIVE

    parser = argparse.ArgumentParser(description="Covert SD Card Tool")
    parser.add_argument("-a", "--all", action="store_true", help="Set up both OS bootable USB and documents partition")
    parser.add_argument("-k", "--kali", action="store_true", help="Create Kali bootable USB and persistence partition")
    parser.add_argument("-d", "--docs", action="store_true", help="Create encrypted documents partition")
    parser.add_argument("-t", "--tails", action="store_true", help="Create Tails bootable USB (no persistence)")
    parser.add_argument("-i", "--iso", help="Path to the Kali or Tails ISO file")
    parser.add_argument("--fast", action="store_true", help="Enable fast setup with less secure encryption")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")

    args = parser.parse_args()

    if not any([args.all, args.kali, args.docs, args.tails]):
        parser.print_help()
        sys.exit(1)

    DEBUG = args.debug
    if DEBUG:
        log("Debug mode enabled")

    FAST_MODE = args.fast
    if FAST_MODE:
        log("Fast mode enabled: Using less secure encryption for quicker setup.")

    if args.all:
        CREATE_DOCS = True
        if args.tails:
            CREATE_TAILS = True
        else:
            CREATE_KALI = True
    else:
        CREATE_KALI = args.kali
        CREATE_DOCS = args.docs
        CREATE_TAILS = args.tails

    if args.iso:
        if CREATE_KALI:
            KALI_ISO = args.iso
        elif CREATE_TAILS:
            TAILS_ISO = args.iso

    check_dependencies()

    if CREATE_KALI or CREATE_TAILS:
        setup_usb()
    else:
        list_drives()
        DRIVE = input("Enter the drive to use (e.g., /dev/sda) [Default: /dev/sda]: ") or "/dev/sda"
        prepare_drive(DRIVE)

        if CREATE_DOCS:
            if CREATE_TAILS:
                fix_partition_table_tails()
            else:
                fix_partition_table()
                setup_docs_partition()
        else:
            setup_unencrypted_partition()

    log("Partition setup complete.")

if __name__ == "__main__":
    main()
