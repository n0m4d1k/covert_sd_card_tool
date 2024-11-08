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

# Global variables
DEBUG = False
TIMESTAMP = datetime.now().strftime('%Y%m%d_%H%M%S')
LOG_FILE = f"covert_sd_setup_{TIMESTAMP}.log"
CREATE_KALI = False
CREATE_DOCS = False
KALI_ISO = ""
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
            # Run the command without capturing output, allowing interaction
            result = subprocess.run(command, shell=shell, check=True)
        else:
            # Run the command and capture output
            result = subprocess.run(command, shell=shell, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
            if result.stdout:
                log(result.stdout.strip())
    except subprocess.CalledProcessError as e:
        if interactive:
            log(f"Command failed: {e}")
        else:
            log(f"Command failed: {e}\nOutput: {e.output}")
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
    # Check for VeraCrypt separately
    if not shutil.which("veracrypt"):
        log("VeraCrypt is not installed. Attempting to install VeraCrypt...")
        install_veracrypt()

def install_veracrypt():
    # Determine system architecture
    arch = platform.machine()
    if arch == "x86_64":
        veracrypt_arch = "x64"
    elif arch == "i386" or arch == "i686":
        veracrypt_arch = "x86"
    else:
        log(f"Unsupported architecture: {arch}. Please install VeraCrypt manually.")
        sys.exit(1)

    # Set VeraCrypt version
    veracrypt_version = "1.25.9"

    # Construct download URL
    download_url = f"https://launchpad.net/veracrypt/trunk/{veracrypt_version}/+download/veracrypt-{veracrypt_version}-setup-console-{veracrypt_arch}.tar.bz2"

    # Download VeraCrypt installer
    log(f"Downloading VeraCrypt {veracrypt_version} for {veracrypt_arch}...")
    installer_filename = f"veracrypt-{veracrypt_version}-setup-console-{veracrypt_arch}.tar.bz2"
    try:
        urllib.request.urlretrieve(download_url, installer_filename)
    except Exception as e:
        log(f"Failed to download VeraCrypt: {e}")
        sys.exit(1)

    # Extract the installer
    log("Extracting VeraCrypt installer...")
    try:
        with tarfile.open(installer_filename, 'r:bz2') as tar:
            tar.extractall()
    except Exception as e:
        log(f"Failed to extract VeraCrypt installer: {e}")
        sys.exit(1)

    # Run the installer silently
    installer_script = f"veracrypt-{veracrypt_version}-setup-console-{veracrypt_arch}"
    if not os.path.exists(installer_script):
        log(f"Installer script not found: {installer_script}")
        sys.exit(1)

    log("Installing VeraCrypt...")
    try:
        # Automate license acceptance and install VeraCrypt
        run_command(f"echo -e 'yes\n' | sudo ./{installer_script} --accept-license", shell=True)
    except Exception as e:
        log(f"Failed to install VeraCrypt: {e}")
        sys.exit(1)

    # Clean up installer files
    os.remove(installer_filename)
    os.remove(installer_script)

    log("VeraCrypt installed successfully.")

def list_drives():
    log("Available drives:")
    result = subprocess.run(["lsblk", "-d", "-o", "NAME,SIZE,TYPE"], capture_output=True, text=True)
    for line in result.stdout.strip().splitlines():
        if "disk" in line:
            name_size = line.strip().split()
            drive = f"/dev/{name_size[0]} {name_size[1]}"
            log(drive)

def prepare_drive(drive):
    # Unmount all mounted partitions on the drive
    result = subprocess.run(["lsblk", "-lnp", drive], capture_output=True, text=True)
    for line in result.stdout.strip().splitlines():
        parts = line.strip().split()
        if len(parts) >= 7 and parts[6]:  # If mountpoint is not empty
            part = parts[0]
            log(f"Unmounting {part}...")
            run_command(["sudo", "umount", part])
    # Disable swap on any swap partitions on the drive
    with open("/proc/swaps") as swaps_file:
        for line in swaps_file:
            if drive in line:
                swap_part = line.strip().split()[0]
                log(f"Disabling swap on {swap_part}...")
                run_command(["sudo", "swapoff", swap_part])

def setup_kali_usb():
    global DRIVE
    log("Setting up Kali bootable USB...")
    list_drives()
    DRIVE = input("Enter the drive to use for Kali USB (e.g., /dev/sda) [Default: /dev/sda]: ") or "/dev/sda"

    # Confirm the selected drive
    confirm = input(f"You have selected {DRIVE}. Is this correct? (y/n) [Default: y]: ") or "y"
    if confirm.lower() != "y":
        log("Drive selection canceled. Exiting.")
        sys.exit(1)

    prepare_drive(DRIVE)

    # Wipe drive if needed
    wipe = input(f"Do you want to wipe the drive {DRIVE} before starting? (y/n) [Default: n]: ") or "n"
    if wipe.lower() == "y":
        log(f"Wiping {DRIVE} and clearing any existing file system or encryption signatures...")
        run_command(["sudo", "wipefs", "--all", DRIVE])
        run_command(["sudo", "sgdisk", "--zap-all", DRIVE])
        run_command(["sudo", "dd", "if=/dev/zero", f"of={DRIVE}", "bs=1M", "count=10"])
        log(f"{DRIVE} wiped successfully.")

    # Get Kali ISO path if not already provided
    global KALI_ISO
    if not KALI_ISO:
        KALI_ISO = input("Enter the path to the Kali ISO file: ")
    if not os.path.isfile(KALI_ISO):
        log(f"Error: Kali ISO file not found at {KALI_ISO}")
        sys.exit(1)

    # Write the ISO to the USB drive
    log(f"Writing Kali ISO to {DRIVE}...")
    run_command(f"sudo dd if='{KALI_ISO}' of='{DRIVE}' bs=4M status=progress", shell=True, interactive=True)
    log(f"Kali ISO written to {DRIVE} successfully.")

    # Fix the partition table to reclaim remaining space
    fix_partition_table()

def fix_partition_table():
    log("Fixing partition table to reclaim remaining space...")

    # Delete partition 2 (created by the ISO)
    run_command(f"sudo parted -s {DRIVE} rm 2", shell=True)
    log("Deleted partition 2.")

    # Get the end of partition 1
    result = subprocess.run(["sudo", "parted", "-s", DRIVE, "unit", "MB", "print"], capture_output=True, text=True)
    end_of_p1 = None
    for line in result.stdout.strip().splitlines():
        if line.strip().startswith("1"):
            parts = line.strip().split()
            end_of_p1 = parts[2]  # End of partition 1
            break
    if end_of_p1 is None:
        log("Error: Could not find end of partition 1.")
        sys.exit(1)

    log(f"End of partition 1: {end_of_p1}")

    # Ask for the size of the persistence partition
    size_persistence = input("Enter size for persistence partition in GB (e.g., 4): ") or "4"
    try:
        size_persistence_gb = float(size_persistence)
    except ValueError:
        log("Invalid size entered for persistence partition. Exiting.")
        sys.exit(1)

    # Calculate the end point of the persistence partition
    start_persistence_mb = float(end_of_p1.replace('MB', ''))
    end_persistence_mb = start_persistence_mb + (size_persistence_gb * 1024)
    end_persistence = f"{end_persistence_mb}MB"

    # Get the total size of the drive in MB
    result = subprocess.run(["sudo", "parted", "-s", DRIVE, "unit", "MB", "print", "free"], capture_output=True, text=True)
    total_size_mb = None
    for line in result.stdout.strip().splitlines():
        if "Disk" in line and "MB" in line:
            total_size_mb = float(line.strip().split()[2].replace('MB', ''))
            break
    if total_size_mb is None:
        log("Error: Could not determine total drive size.")
        sys.exit(1)

    # Ensure the end_persistence_mb does not exceed the total drive size
    if end_persistence_mb > total_size_mb:
        log("Error: Persistence partition size exceeds available space.")
        sys.exit(1)

    # Create persistence partition (partition 2)
    run_command(f"sudo parted -s {DRIVE} mkpart primary {start_persistence_mb}MB {end_persistence_mb}MB", shell=True)
    log("Created persistence partition.")

    # If creating documents partition
    if CREATE_DOCS:
        # Documents partition starts where persistence partition ends
        start_docs_mb = end_persistence_mb
        end_docs = "100%"

        # Create documents partition (partition 3)
        run_command(f"sudo parted -s {DRIVE} mkpart primary {start_docs_mb}MB {end_docs}", shell=True)
        log("Created documents partition.")

    run_command(f"sudo partprobe {DRIVE}", shell=True)

    # Proceed to set up the persistence partition
    setup_kali_partition()

    # Proceed to set up the documents partition if required
    if CREATE_DOCS:
        setup_docs_partition()

def setup_kali_partition():
    global DRIVE
    # The persistence partition is partition 2
    PERSIST_PART = f"{DRIVE}2"

    # Wipe existing signatures on the partition
    run_command(["sudo", "wipefs", "--all", PERSIST_PART])

    # Encrypt and format persistence partition with stronger encryption
    log("Configuring encrypted persistence partition...")

    # Specify stronger encryption options
    luks_format_cmd = (
        f"sudo cryptsetup luksFormat "
        f"--cipher aes-xts-plain64 "
        f"--key-size 512 "
        f"--hash sha512 "
        f"--iter-time 5000 "
        f"'{PERSIST_PART}'"
    )
    run_command(luks_format_cmd, shell=True, interactive=True)

    run_command(f"sudo cryptsetup luksOpen '{PERSIST_PART}' kali_USB", shell=True, interactive=True)
    run_command("sudo mkfs.ext4 -L persistence /dev/mapper/kali_USB", shell=True)

    # Create persistence.conf
    run_command("sudo mkdir -p /mnt/kali_USB", shell=True)
    run_command("sudo mount /dev/mapper/kali_USB /mnt/kali_USB", shell=True)
    run_command('echo "/ union" | sudo tee /mnt/kali_USB/persistence.conf', shell=True)
    run_command("sudo umount /dev/mapper/kali_USB", shell=True)
    run_command("sudo cryptsetup luksClose kali_USB", shell=True)

    log("Kali persistence setup complete.")

def setup_docs_partition():
    global DRIVE
    # The documents partition is partition 3
    DOCS_PART = f"{DRIVE}3"

    # Wipe existing signatures on the partition
    run_command(["sudo", "wipefs", "--all", DOCS_PART])

    log("Configuring VeraCrypt encryption for documents partition...")

    # Specify stronger encryption options
    veracrypt_create_cmd = (
        f"veracrypt --text --create '{DOCS_PART}' "
        f"--encryption AES-Twofish-Serpent "
        f"--hash whirlpool "
        f"--filesystem exfat "
        f"--volume-type normal "
        f"--size=100%"
    )
    run_command(veracrypt_create_cmd, shell=True, interactive=True)

    log("Encrypted documents partition setup complete.")

def main():
    global DEBUG, CREATE_KALI, CREATE_DOCS, KALI_ISO, DRIVE

    parser = argparse.ArgumentParser(description="Covert SD Card Tool")
    parser.add_argument("-a", "--all", action="store_true", help="Set up both Kali bootable USB and documents partition")
    parser.add_argument("-k", "--kali", action="store_true", help="Create Kali bootable USB and persistence partition")
    parser.add_argument("-d", "--docs", action="store_true", help="Create encrypted documents partition")
    parser.add_argument("-i", "--iso", help="Path to the Kali ISO file")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")

    args = parser.parse_args()

    if not any([args.all, args.kali, args.docs]):
        parser.print_help()
        sys.exit(1)

    DEBUG = args.debug
    if DEBUG:
        log("Debug mode enabled")

    CREATE_KALI = args.all or args.kali
    CREATE_DOCS = args.all or args.docs
    if args.iso:
        KALI_ISO = args.iso

    check_dependencies()

    if CREATE_KALI:
        setup_kali_usb()
    else:
        # If not creating Kali USB, we still need to set the DRIVE variable
        list_drives()
        DRIVE = input("Enter the drive to use (e.g., /dev/sda) [Default: /dev/sda]: ") or "/dev/sda"
        prepare_drive(DRIVE)

        # If creating documents partition only
        if CREATE_DOCS:
            fix_partition_table()
            setup_docs_partition()

    log("Partition setup complete.")

if __name__ == "__main__":
    main()
