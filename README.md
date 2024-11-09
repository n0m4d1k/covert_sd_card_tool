# Covert SD Card Tool

## Introduction

The **Covert SD Card Tool** is a Python script designed to automate the process of setting up a bootable USB drive with either Kali Linux or Tails OS. It includes options to create encrypted persistence partitions, encrypted documents partitions, and an unencrypted partition containing helpful scripts and instructions. This tool simplifies the complex steps involved in preparing a secure, portable operating system on a USB drive.

## Features

- **Install Kali Linux or Tails OS** on a USB drive.
- **Create an encrypted persistence partition** for Kali Linux.
- **Create an encrypted documents partition** using VeraCrypt.
- **Add an unencrypted partition** containing automount scripts and instructions.
- **Customizable encryption options** with a fast setup mode.
- **Automated dependency checking and installation**.

## Prerequisites

- **Operating System:** Linux (Debian-based distributions recommended).
- **Python Version:** Python 3.x.
- **Dependencies:**
  - `parted`
  - `cryptsetup`
  - `lsblk`
  - `dd`
  - `sgdisk`
  - `wipefs`
  - `bc`
  - `fdisk`
  - `veracrypt` (The script can install this if not present).

## Installation

1. **Clone the Repository or Download the Script:**

   ```bash
   git clone https://github.com/yourusername/covert_sd_card_tool.git
   cd covert_sd_card_tool
   ```

2. **Make the Script Executable:**

   ```bash
   chmod +x covert_sd_card_tool.py
   ```

## Usage

Run the script with appropriate options:

```bash
sudo ./covert_sd_card_tool.py [options]
```

### Command-Line Options

- `-a`, `--all` : Set up both the OS bootable USB and the documents partition.
- `-k`, `--kali` : Create a Kali bootable USB and persistence partition.
- `-t`, `--tails` : Create a Tails bootable USB (no persistence).
- `-d`, `--docs` : Create an encrypted documents partition.
- `-i`, `--iso` : Path to the Kali or Tails ISO file.
- `--fast` : Enable fast setup with less secure encryption.
- `--debug` : Enable debug mode.

### Examples

- **Install Kali with Encrypted Persistence and Encrypted Documents Partition:**

  ```bash
  sudo ./covert_sd_card_tool.py -a -i /path/to/kali.iso
  ```

- **Install Tails and Encrypted Documents Partition:**

  ```bash
  sudo ./covert_sd_card_tool.py -a -t -i /path/to/tails.iso
  ```

- **Install Tails Without Encrypted Documents Partition:**

  ```bash
  sudo ./covert_sd_card_tool.py -t -i /path/to/tails.iso
  ```

- **Install Encrypted Documents Partition Only:**

  ```bash
  sudo ./covert_sd_card_tool.py -d
  ```