#!/usr/bin/env python3
"""
Helper script to format a GitHub App private key for use in environment variables.
This script takes a .pem file and outputs the key as a base64-encoded string.

Usage:
    python format_private_key.py /path/to/private-key.pem
"""

import sys
import os
import base64

def format_private_key(pem_file_path):
    """Format a private key file for use in environment variables."""
    try:
        with open(pem_file_path, 'r') as f:
            private_key = f.read()
        
        # Base64 encode the entire key
        encoded_key = base64.b64encode(private_key.encode('utf-8')).decode('utf-8')
        
        print("\nBase64-encoded private key for environment variables:\n")
        print(encoded_key)
        print("\nYou can now set this as the GITHUB_PRIVATE_KEY_BASE64 environment variable in Cloud Run.")
        
    except FileNotFoundError:
        print(f"Error: File {pem_file_path} not found.")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python format_private_key.py /path/to/private-key.pem")
        sys.exit(1)
    
    pem_file_path = sys.argv[1]
    format_private_key(pem_file_path) 