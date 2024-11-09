#!/usr/bin/env python3

import argparse
import subprocess
import sys
import os
import shutil
from datetime import datetime
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
    dependencies = ["parted", "cryptsetup", "lsblk", "dd", "sgdisk", "wipefs", "bc", "fdisk", "veracrypt", "lsof", "fuser", "mountpoint"]
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
            run_command(["sudo", "fuser", "-k", drive])
            log(f"Killed processes using {drive}.")
        else:
            log("Cannot proceed while processes are using the drive. Exiting.")
            sys.exit(1)
    else:
        log(f"No processes are using {drive}.")

def setup_usb():
    global DRIVE
    log("Setting up bootable USB or preparing partitions...")
    list_drives()
    DRIVE = input("Enter the drive to use for USB (e.g., /dev/sda) [Default: /dev/sda]: ") or "/dev/sda"

    confirm = input(f"You have selected {DRIVE}. Is this correct? (y/n) [Default: y]: ") or "y"
    if confirm.lower() != "y":
        log("Drive selection canceled. Exiting.")
        sys.exit(1)

    prepare_drive(DRIVE)

    if CREATE_KALI or CREATE_TAILS or CREATE_DOCS:
        wipe = input(f"Do you want to wipe the drive {DRIVE} before starting? (y/n) [Default: n]: ") or "n"
        if wipe.lower() == "y":
            log(f"Wiping {DRIVE} and clearing any existing file system or encryption signatures...")
            run_command(["sudo", "wipefs", "--all", DRIVE])
            run_command(["sudo", "sgdisk", "--zap-all", DRIVE])
            run_command(["sudo", "dd", "if=/dev/zero", f"of={DRIVE}", "bs=1M", "count=10"])
            log(f"{DRIVE} wiped successfully.")

    if CREATE_KALI or CREATE_TAILS:
        global KALI_ISO, TAILS_ISO
        if CREATE_KALI:
            if not KALI_ISO:
                KALI_ISO = input("Enter the path to the Kali ISO file: ")
            if not os.path.isfile(KALI_ISO):
                log(f"Error: Kali ISO file not found at {KALI_ISO}")
                sys.exit(1)
            ISO_PATH = KALI_ISO
        elif CREATE_TAILS:
            if not TAILS_ISO:
                TAILS_ISO = input("Enter the path to the Tails ISO file: ")
            if not os.path.isfile(TAILS_ISO):
                log(f"Error: Tails ISO file not found at {TAILS_ISO}")
                sys.exit(1)
            ISO_PATH = TAILS_ISO

        log(f"Writing ISO to {DRIVE}...")
        run_command(f"sudo dd if='{ISO_PATH}' of='{DRIVE}' bs=64M status=progress", shell=True, interactive=True)
        log(f"ISO written to {DRIVE} successfully.")

        if CREATE_KALI:
            fix_partition_table()
        elif CREATE_TAILS:
            fix_partition_table_tails()
    elif CREATE_DOCS:
        fix_partition_table_docs_only()
    else:
        log("No valid setup option selected. Exiting.")
        sys.exit(1)

def fix_partition_table_docs_only():
    log("Setting up partitions for documents only...")

    # Clear existing partitions if any
    run_command(f"sudo parted -a optimal -s {DRIVE} mklabel gpt", shell=True)
    run_command(f"sudo partprobe {DRIVE}", shell=True)
    run_command("sudo udevadm settle", shell=True)
    time.sleep(5)  # Increased sleep to ensure partitions are recognized

    # Get the total size of the drive in bytes
    result = subprocess.run(["lsblk", "-b", "-n", "-o", "SIZE", DRIVE], capture_output=True, text=True)
    total_size_bytes = int(result.stdout.strip())
    total_size_mib = total_size_bytes / (1024 * 1024)  # Convert to MiB

    # Ask for document partition size
    size_docs = input("Enter size for documents partition in GB (leave blank to use remaining space minus 1GB): ")
    start_docs_mib = 1  # Starting immediately after the first MiB
    if size_docs:
        try:
            size_docs_gb = float(size_docs)
            end_docs_mib = start_docs_mib + (size_docs_gb * 1024)
            if end_docs_mib > (total_size_mib - 1024):
                log("Error: Documents partition size exceeds available space when reserving 1GB for unencrypted partition.")
                sys.exit(1)
        except ValueError:
            log("Invalid size entered for documents partition. Exiting.")
            sys.exit(1)
    else:
        end_docs_mib = total_size_mib - 1024  # Reserve 1GB for unencrypted partition

    # Create documents partition
    run_command(f"sudo parted -a optimal -s {DRIVE} mkpart primary {start_docs_mib}MiB {end_docs_mib}MiB", shell=True)
    log("Created documents partition.")

    # Create unencrypted partition
    start_unencrypted_mib = end_docs_mib
    run_command(f"sudo parted -a optimal -s {DRIVE} mkpart primary {start_unencrypted_mib}MiB 100%", shell=True)
    log("Created unencrypted partition for scripts/instructions.")

    # Refresh partition table to recognize new partitions
    run_command(f"sudo partprobe {DRIVE}", shell=True)
    run_command("sudo udevadm settle", shell=True)
    time.sleep(5)  # Increased sleep to ensure partitions are recognized

    setup_unencrypted_partition()
    setup_docs_partition()

def fix_partition_table():
    log("Fixing partition table to reclaim remaining space...")

    # Attempt to delete partition 2 if it exists
    try:
        run_command(f"sudo parted -a optimal -s {DRIVE} rm 2", shell=True)
        log("Deleted partition 2.")
    except SystemExit:
        log("No partition 2 to delete.")

    # Get the end of partition 1
    result = subprocess.run(["sudo", "parted", "-s", DRIVE, "unit", "MiB", "print"], capture_output=True, text=True)
    end_of_p1 = None
    for line in result.stdout.strip().splitlines():
        if line.strip().startswith("1"):
            parts = line.strip().split()
            if len(parts) >= 3:
                end_of_p1 = parts[2].replace('MiB', '')
                break
    if end_of_p1 is None:
        log("Error: Could not find end of partition 1.")
        sys.exit(1)

    log(f"End of partition 1: {end_of_p1}MiB")

    # Get the total size of the drive in bytes
    result = subprocess.run(["lsblk", "-b", "-n", "-o", "SIZE", DRIVE], capture_output=True, text=True)
    total_size_bytes = int(result.stdout.strip())
    total_size_mib = total_size_bytes / (1024 * 1024)  # Convert to MiB

    # Ask for persistence partition size
    size_persistence = input("Enter size for persistence partition in GB (e.g., 4): ") or "4"
    try:
        size_persistence_gb = float(size_persistence)
    except ValueError:
        log("Invalid size entered for persistence partition. Exiting.")
        sys.exit(1)

    start_persistence_mib = float(end_of_p1)
    end_persistence_mib = start_persistence_mib + (size_persistence_gb * 1024)

    if end_persistence_mib > total_size_mib:
        log("Error: Persistence partition size exceeds available space.")
        sys.exit(1)

    # Create persistence partition
    run_command(f"sudo parted -a optimal -s {DRIVE} mkpart primary {start_persistence_mib}MiB {end_persistence_mib}MiB", shell=True)
    log("Created persistence partition.")

    # Set up documents partition
    start_docs_mib = end_persistence_mib
    size_docs = input("Enter size for documents partition in GB (leave blank to use remaining space minus 1GB): ")
    if size_docs:
        try:
            size_docs_gb = float(size_docs)
            end_docs_mib = start_docs_mib + (size_docs_gb * 1024)
            if end_docs_mib > (total_size_mib - 1024):
                log("Error: Documents partition size exceeds available space when reserving 1GB for unencrypted partition.")
                sys.exit(1)
        except ValueError:
            log("Invalid size entered for documents partition. Exiting.")
            sys.exit(1)
    else:
        end_docs_mib = total_size_mib - 1024  # Reserve 1GB for unencrypted partition

    run_command(f"sudo parted -a optimal -s {DRIVE} mkpart primary {start_docs_mib}MiB {end_docs_mib}MiB", shell=True)
    log("Created documents partition.")

    # Create unencrypted partition
    start_unencrypted_mib = end_docs_mib
    run_command(f"sudo parted -a optimal -s {DRIVE} mkpart primary {start_unencrypted_mib}MiB 100%", shell=True)
    log("Created unencrypted partition for scripts/instructions.")

    # Refresh partition table to recognize new partitions
    run_command(f"sudo partprobe {DRIVE}", shell=True)
    run_command("sudo udevadm settle", shell=True)
    time.sleep(5)  # Increased sleep to ensure partitions are recognized

    setup_kali_partition()
    if CREATE_DOCS:
        setup_docs_partition()
    setup_unencrypted_partition()

def fix_partition_table_tails():
    log("Setting up partition table for Tails...")

    # Clear existing partitions if any
    run_command(f"sudo parted -a optimal -s {DRIVE} mklabel gpt", shell=True)
    run_command(f"sudo partprobe {DRIVE}", shell=True)
    run_command("sudo udevadm settle", shell=True)
    time.sleep(5)  # Increased sleep to ensure partitions are recognized

    # Tails typically does not require a persistence partition, but we'll create an unencrypted partition for scripts/instructions
    run_command(f"sudo parted -a optimal -s {DRIVE} mkpart primary 1MiB 100%", shell=True)
    log("Created unencrypted partition for scripts/instructions.")

    # Refresh partition table to recognize new partitions
    run_command(f"sudo partprobe {DRIVE}", shell=True)
    run_command("sudo udevadm settle", shell=True)
    time.sleep(5)

    setup_unencrypted_partition()

def setup_kali_partition():
    global DRIVE
    PERSIST_PART = get_partition_name(DRIVE, 2)

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
    DOCS_PART = get_partition_name(DRIVE, get_last_partition_number() - 1)

    # Check if the partition exists
    if not os.path.exists(DOCS_PART):
        log(f"Error: Partition {DOCS_PART} does not exist.")
        sys.exit(1)

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
    UNENCRYPTED_PART = get_partition_name(DRIVE, get_last_partition_number())

    # Check if the partition exists
    if not os.path.exists(UNENCRYPTED_PART):
        log(f"Error: Partition {UNENCRYPTED_PART} does not exist.")
        sys.exit(1)

    log(f"Attempting to format partition {UNENCRYPTED_PART} with FAT32 filesystem.")
    run_command(f"sudo mkfs.vfat -n 'TOOLS' {UNENCRYPTED_PART}", shell=True)
    log("Formatted unencrypted partition with FAT32 filesystem.")

    run_command("sudo mkdir -p /mnt/unencrypted", shell=True)
    run_command(f"sudo mount {UNENCRYPTED_PART} /mnt/unencrypted", shell=True)

    instructions = f"""
To mount the encrypted documents partition, use the provided 'mount_encrypted_partitions.sh' script.
To unmount and lock it, use the 'cleanup_encrypted_partitions.sh' script.

**Automount Script:**
Run: sudo ./mount_encrypted_partitions.sh

**Cleanup Script:**
Run: sudo ./cleanup_encrypted_partitions.sh
"""

    with open("/tmp/README.txt", "w") as readme_file:
        readme_file.write(instructions)
    run_command("sudo cp /tmp/README.txt /mnt/unencrypted/README.txt", shell=True)
    run_command("sudo rm /tmp/README.txt", shell=True)
    log("Created README.txt with mounting instructions.")

    mount_script = """#!/bin/bash
# Script to mount encrypted documents partition

echo "Available drives:"
lsblk -o NAME,SIZE,TYPE | grep disk
read -p "Enter the drive path for the documents partition (default: /dev/sdc1): " DRIVE_PATH
DRIVE_PATH=${DRIVE_PATH:-/dev/sdc1}

if [ -b "$DRIVE_PATH" ]; then
    echo "Mounting VeraCrypt documents partition at $DRIVE_PATH..."
    sudo mkdir -p /mnt/veracrypt_docs
    sudo veracrypt --text --mount "$DRIVE_PATH" /mnt/veracrypt_docs
    echo "Documents partition mounted at /mnt/veracrypt_docs."
else
    echo "Error: Partition $DRIVE_PATH not found."
fi
"""

    with open("/tmp/mount_encrypted_partitions.sh", "w") as script_file:
        script_file.write(mount_script)
    run_command("sudo cp /tmp/mount_encrypted_partitions.sh /mnt/unencrypted/mount_encrypted_partitions.sh", shell=True)
    run_command("sudo chmod +x /mnt/unencrypted/mount_encrypted_partitions.sh", shell=True)
    run_command("sudo rm /tmp/mount_encrypted_partitions.sh", shell=True)
    log("Created mount_encrypted_partitions.sh script.")

    cleanup_script = """#!/bin/bash
# Script to unmount and lock encrypted documents partition

echo "Available drives:"
lsblk -o NAME,SIZE,TYPE | grep disk
read -p "Enter the drive path for the documents partition (default: /dev/sdc1): " DRIVE_PATH
DRIVE_PATH=${DRIVE_PATH:-/dev/sdc1}

echo "Unmounting and locking encrypted documents partition at $DRIVE_PATH..."

if mountpoint -q /mnt/veracrypt_docs; then
    sudo veracrypt --text --dismount /mnt/veracrypt_docs
    echo "VeraCrypt documents partition unmounted."
else
    echo "Documents partition is not currently mounted."
fi
"""

    with open("/tmp/cleanup_encrypted_partitions.sh", "w") as script_file:
        script_file.write(cleanup_script)
    run_command("sudo cp /tmp/cleanup_encrypted_partitions.sh /mnt/unencrypted/cleanup_encrypted_partitions.sh", shell=True)
    run_command("sudo chmod +x /mnt/unencrypted/cleanup_encrypted_partitions.sh", shell=True)
    run_command("sudo rm /tmp/cleanup_encrypted_partitions.sh", shell=True)
    log("Created cleanup_encrypted_partitions.sh script.")

    run_command("sudo umount /mnt/unencrypted", shell=True)
    log("Unencrypted partition setup complete.")

def get_last_partition_number():
    """Returns the highest partition number on the DRIVE."""
    result = subprocess.run(["lsblk", "-ln", "-o", "NAME", DRIVE], capture_output=True, text=True)
    partitions = [line.strip() for line in result.stdout.strip().splitlines() if line.strip()]
    partition_numbers = []
    for part in partitions:
        if 'p' in part:
            # Handle /dev/nvme0n1p1 format
            if part.startswith(os.path.basename(DRIVE)):
                num = part.replace(os.path.basename(DRIVE), '').replace('p', '')
                if num.isdigit():
                    partition_numbers.append(int(num))
        else:
            # Handle /dev/sda1 format
            if part.startswith(os.path.basename(DRIVE)):
                num = part.replace(os.path.basename(DRIVE), '')
                if num.isdigit():
                    partition_numbers.append(int(num))
    if not partition_numbers:
        log(f"No partitions found on {DRIVE}.")
        sys.exit(1)
    return max(partition_numbers)

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

    if CREATE_KALI or CREATE_TAILS or CREATE_DOCS:
        setup_usb()
    else:
        list_drives()
        DRIVE = input("Enter the drive to use (e.g., /dev/sda) [Default: /dev/sda]: ") or "/dev/sda"
        prepare_drive(DRIVE)

        if CREATE_DOCS:
            fix_partition_table_docs_only()
        else:
            setup_unencrypted_partition()

    log("Partition setup complete.")

if __name__ == "__main__":
    main()
